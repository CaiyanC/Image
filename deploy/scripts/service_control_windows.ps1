param(
    [ValidateSet("Redis", "Backend", "RestartBackend", "DeployBackend", "Frontend", "Worker", "All", "Watchdog")]
    [string]$Action = "All",
    [string]$RepoRoot = "",
    [string]$LogPath = "",
    [string]$ExpectedCommit = ""
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
$ExpectedBackendRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "backend"))

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

function Get-BackendListeners {
    return @(Get-NetTCPConnection -LocalPort $ProdBackendPort -State Listen -ErrorAction SilentlyContinue)
}

function Get-ProcessById {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-BackendListenerIntegrity {
    $listeners = @(Get-BackendListeners)
    if ($listeners.Count -ne 1) {
        Write-WatchdogLog "ERROR" "expected exactly one backend listener on port $ProdBackendPort, found $($listeners.Count)"
        return $false
    }
    $pidValue = [int]$listeners[0].OwningProcess
    $proc = Get-ProcessById -ProcessId $pidValue
    if (-not $proc) {
        Write-WatchdogLog "ERROR" "backend listener pid=$pidValue cannot be resolved"
        return $false
    }
    $cmd = [string]$proc.CommandLine
    if (-not ($cmd -like "*uvicorn app.main:app*" -and $cmd -like "*--port $ProdBackendPort*")) {
        Write-WatchdogLog "ERROR" "backend listener pid=$pidValue has unexpected command line: $cmd"
        return $false
    }
    Write-WatchdogLog "INFO" "backend listener verified pid=$pidValue exe=$($proc.ExecutablePath)"
    return $true
}

function Test-BackendVersion {
    param([string]$Commit = "")
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:$ProdBackendPort/api/health/version" -TimeoutSec 5
    } catch {
        Write-WatchdogLog "ERROR" "backend version endpoint failed: $($_.Exception.Message)"
        return $false
    }
    $codeRoot = [System.IO.Path]::GetFullPath([string]$version.code_root)
    $cwd = [System.IO.Path]::GetFullPath([string]$version.cwd)
    if ($codeRoot -ne $ExpectedBackendRoot) {
        Write-WatchdogLog "ERROR" "backend code_root mismatch: expected=$ExpectedBackendRoot actual=$codeRoot"
        return $false
    }
    if ($cwd -ne $ExpectedBackendRoot) {
        Write-WatchdogLog "ERROR" "backend cwd mismatch: expected=$ExpectedBackendRoot actual=$cwd"
        return $false
    }
    if ($Commit -and ([string]$version.commit) -ne $Commit) {
        Write-WatchdogLog "ERROR" "backend commit mismatch: expected=$Commit actual=$($version.commit)"
        return $false
    }
    Write-WatchdogLog "INFO" "backend version verified commit=$($version.commit) code_root=$codeRoot cwd=$cwd pid=$($version.pid)"
    return $true
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

function Stop-Backend {
    $listeners = @(Get-BackendListeners)
    if (-not $listeners) {
        Write-WatchdogLog "INFO" "backend port $ProdBackendPort has no listener"
        return $true
    }
    return Stop-ListenerTree -Port $ProdBackendPort
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
    param([bool]$SkipIfHealthy = $true)
    if ($SkipIfHealthy -and (Test-BackendReady)) {
        Write-WatchdogLog "INFO" "Backend already healthy; skip start"
        return $true
    }
    if (Get-BackendListeners) {
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

function Restart-Backend {
    param([string]$Commit = "")
    Write-WatchdogLog "WARN" "deploy restart requested for prod backend"
    if (-not (Stop-Backend)) {
        return $false
    }
    if (Get-BackendListeners) {
        Write-WatchdogLog "ERROR" "backend port $ProdBackendPort still listening after stop"
        return $false
    }
    if (-not (Start-Backend -SkipIfHealthy $false)) {
        return $false
    }
    if (-not (Test-BackendListenerIntegrity)) {
        return $false
    }
    if (-not (Test-BackendReady)) {
        Write-WatchdogLog "ERROR" "backend ready check failed after deploy restart"
        return $false
    }
    if (-not (Test-BackendVersion -Commit $Commit)) {
        return $false
    }
    return $true
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
    "RestartBackend" { $r = Ensure-Redis; $p = Ensure-Postgres; if ($r -and $p) { Restart-Backend -Commit $ExpectedCommit } else { $false } }
    "DeployBackend" { $r = Ensure-Redis; $p = Ensure-Postgres; if ($r -and $p) { Restart-Backend -Commit $ExpectedCommit } else { $false } }
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
