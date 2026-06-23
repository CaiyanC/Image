param(
    [ValidateSet("Redis", "Backend", "Frontend", "Worker", "All", "Watchdog")]
    [string]$Action = "All",
    [string]$RepoRoot = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
if (-not $LogPath) {
    $LogPath = Join-Path $RepoRoot "logs\watchdog.log"
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

$ProdBackendPort = 8000
$ProdFrontendPort = 5275
$ProdQueue = "celery_prod"
$ProdWorkerName = "worker_prod"
$ProdLogDir = Join-Path $RepoRoot "logs\prod"
$ProdWorkerPidFile = Join-Path $ProdLogDir "celery.pid"

function Write-WatchdogLog {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "$timestamp [$Level] $Message" -Encoding utf8
}

function Test-HttpOk {
    param([string]$Url, [int]$TimeoutSeconds = 5)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return [int]$resp.StatusCode -ge 200 -and [int]$resp.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Test-BackendReady {
    try {
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$ProdBackendPort/api/health/ready" -TimeoutSec 5
        return $ready.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-ProdWorker {
    $workers = Get-CimInstance Win32_Process | Where-Object {
        $cmd = $_.CommandLine
        $cmd -and (
            $cmd -like "*$ProdWorkerName@*" -or
            $cmd -like "*-Q $ProdQueue*"
        )
    }
    return [bool]$workers
}

function Wait-PortReleased {
    param([int]$Port, [int]$TimeoutSeconds = 20)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $listener) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-ListenerTree {
    param([int]$Port)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $pidValue = [int]$listener.OwningProcess
        Write-WatchdogLog "WARN" "cleaning listener on port $Port pid=$pidValue before restart"
        $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $pidValue }
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            Write-WatchdogLog "WARN" "stopped child pid=$($child.ProcessId) of port $Port listener"
        }
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        & taskkill.exe /F /T /PID $pidValue 2>$null | Out-Null
    }
    if (-not (Wait-PortReleased -Port $Port -TimeoutSeconds 20)) {
        Write-WatchdogLog "ERROR" "port $Port is still occupied after cleanup; skip restart"
        return $false
    }
    return $true
}

function Ensure-Docker {
    try {
        docker info 2>$null | Out-Null
        return $true
    } catch {
        $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path $dockerDesktop) {
            Write-WatchdogLog "WARN" "Docker is not ready; starting Docker Desktop"
            Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        } else {
            Write-WatchdogLog "ERROR" "Docker Desktop executable not found"
            return $false
        }
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            try {
                docker info 2>$null | Out-Null
                Write-WatchdogLog "INFO" "Docker is ready"
                return $true
            } catch {
            }
        }
        Write-WatchdogLog "ERROR" "Docker did not become ready within timeout"
        return $false
    }
}

function Ensure-Redis {
    if (-not (Ensure-Docker)) {
        return $false
    }
    $exists = docker ps -a --filter "name=^/caiyan-redis$" --format "{{.Names}}"
    if (-not $exists) {
        Write-WatchdogLog "WARN" "Redis container caiyan-redis does not exist; creating"
        docker run --name caiyan-redis -p 6379:6379 -d redis:7 | Out-Null
    } else {
        $running = docker ps --filter "name=^/caiyan-redis$" --format "{{.Names}}"
        if (-not $running) {
            Write-WatchdogLog "WARN" "Redis container is stopped; starting"
            docker start caiyan-redis | Out-Null
        }
    }
    try {
        $pong = docker exec caiyan-redis redis-cli ping
        if ($pong -eq "PONG") {
            Write-WatchdogLog "INFO" "Redis is healthy"
            return $true
        }
    } catch {
    }
    Write-WatchdogLog "ERROR" "Redis did not respond to ping"
    return $false
}

function Ensure-Postgres {
    $service = Get-Service -Name "postgresql-x64-18" -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-WatchdogLog "WARN" "PostgreSQL service postgresql-x64-18 not found; assuming external database"
        return $true
    }
    if ($service.Status -ne "Running") {
        Write-WatchdogLog "WARN" "PostgreSQL service is $($service.Status); starting"
        Start-Service postgresql-x64-18
        $service.WaitForStatus("Running", "00:00:30")
    }
    Write-WatchdogLog "INFO" "PostgreSQL service is running"
    return $true
}

function Start-Backend {
    if (Test-BackendReady) {
        Write-WatchdogLog "INFO" "Backend already healthy; skip start"
        return $true
    }
    if (Get-NetTCPConnection -LocalPort $ProdBackendPort -State Listen -ErrorAction SilentlyContinue) {
        if (-not (Stop-ListenerTree -Port $ProdBackendPort)) {
            return $false
        }
    }
    Write-WatchdogLog "WARN" "starting prod backend via start-all.bat backend"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$RepoRoot\start-all.bat`" backend") -WorkingDirectory $RepoRoot -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if (Test-BackendReady) {
            Write-WatchdogLog "INFO" "Backend started and ready"
            return $true
        }
    }
    Write-WatchdogLog "ERROR" "Backend did not become ready after restart"
    return $false
}

function Start-Frontend {
    if (Test-HttpOk "http://127.0.0.1:$ProdFrontendPort") {
        Write-WatchdogLog "INFO" "Frontend already reachable; skip start"
        return $true
    }
    if (Get-NetTCPConnection -LocalPort $ProdFrontendPort -State Listen -ErrorAction SilentlyContinue) {
        if (-not (Stop-ListenerTree -Port $ProdFrontendPort)) {
            return $false
        }
    }
    Write-WatchdogLog "WARN" "starting prod frontend via start-all.bat frontend"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$RepoRoot\start-all.bat`" frontend") -WorkingDirectory $RepoRoot -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if (Test-HttpOk "http://127.0.0.1:$ProdFrontendPort") {
            Write-WatchdogLog "INFO" "Frontend started and reachable"
            return $true
        }
    }
    Write-WatchdogLog "ERROR" "Frontend did not become reachable after restart"
    return $false
}

function Stop-StaleProdWorkerPidFile {
    if (-not (Test-Path $ProdWorkerPidFile)) {
        return
    }
    $pidLine = Get-Content $ProdWorkerPidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $pidValue = if ($pidLine) { $pidLine.Trim() } else { "" }
    if ($pidValue -and $pidValue -match "^\d+$") {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
        if (-not $proc) {
            Remove-Item -LiteralPath $ProdWorkerPidFile -Force -ErrorAction SilentlyContinue
            Write-WatchdogLog "WARN" "removed stale prod worker pidfile pid=$pidValue"
        }
    }
}

function Start-Worker {
    if (Test-ProdWorker) {
        Write-WatchdogLog "INFO" "Prod worker already running; skip start"
        return $true
    }
    if (-not (Ensure-Redis)) {
        Write-WatchdogLog "ERROR" "Prod worker start skipped because Redis is not ready"
        return $false
    }
    New-Item -ItemType Directory -Force -Path $ProdLogDir | Out-Null
    Stop-StaleProdWorkerPidFile
    Write-WatchdogLog "WARN" "starting prod worker via start-all.bat worker"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$RepoRoot\start-all.bat`" worker") -WorkingDirectory $RepoRoot -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        if (Test-ProdWorker) {
            Write-WatchdogLog "INFO" "Prod worker started"
            return $true
        }
    }
    Write-WatchdogLog "ERROR" "Prod worker did not start"
    return $false
}

function Ensure-All {
    $redisOk = Ensure-Redis
    $postgresOk = Ensure-Postgres
    $backendOk = $false
    if ($redisOk -and $postgresOk) {
        $backendOk = Start-Backend
    } else {
        Write-WatchdogLog "ERROR" "Backend start skipped because Redis or PostgreSQL is not ready"
    }
    $frontendOk = Start-Frontend
    $workerOk = Start-Worker
    return $redisOk -and $postgresOk -and $backendOk -and $frontendOk -and $workerOk
}

$ok = switch ($Action) {
    "Redis" { Ensure-Redis }
    "Backend" { $r = Ensure-Redis; $p = Ensure-Postgres; if ($r -and $p) { Start-Backend } else { $false } }
    "Frontend" { Start-Frontend }
    "Worker" { Start-Worker }
    "All" { Ensure-All }
    "Watchdog" { Ensure-All }
}

if ($ok) {
    Write-Output "$Action OK"
    exit 0
}

Write-Output "$Action FAILED"
exit 1
