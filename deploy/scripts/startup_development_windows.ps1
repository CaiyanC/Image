param(
    [string]$RuntimeRoot = "",
    [string]$LogPath = "",
    [int]$LockWaitSeconds = 0
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeRoot) {
    $RuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)

$envFile = Join-Path $RuntimeRoot "backend\.env.dev"
$devBackendRoot = Join-Path $RuntimeRoot "backend"
$devFrontendRoot = Join-Path $RuntimeRoot "frontend"
$devLogDir = Join-Path $RuntimeRoot "logs\dev"
$devPidFile = Join-Path $devLogDir "celery.pid"
$devWorkerLog = Join-Path $devLogDir "celery.log"
$devBackendStdout = Join-Path $devLogDir "startup-backend.stdout.log"
$devBackendStderr = Join-Path $devLogDir "startup-backend.stderr.log"
$devWorkerStdout = Join-Path $devLogDir "startup-worker.stdout.log"
$devWorkerStderr = Join-Path $devLogDir "startup-worker.stderr.log"
$devFrontendStdout = Join-Path $devLogDir "startup-frontend.stdout.log"
$devFrontendStderr = Join-Path $devLogDir "startup-frontend.stderr.log"

if (-not $LogPath) {
    $LogPath = Join-Path $devLogDir "startup.log"
}
New-Item -ItemType Directory -Force -Path $devLogDir | Out-Null

function Write-StartupLog {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "$timestamp [$Level] $Message" -Encoding utf8
}

function Import-EnvironmentFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "development environment file is missing: $Path"
    }

    foreach ($line in Get-Content -LiteralPath $Path -Encoding utf8) {
        $text = [string]$line
        if ($text -match '^\s*(?:#|$)') {
            continue
        }
        if ($text -notmatch '^\s*([^=\s][^=]*)=(.*)$') {
            continue
        }
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Test-ListeningPort {
    param([int]$Port)
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
    } catch {
        return $false
    }
}

function Wait-TcpPort {
    param([int]$Port, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        # A service may bind to 0.0.0.0 or the machine's LAN address rather
        # than 127.0.0.1.  Check the Windows listener table so startup does
        # not report a healthy LAN-bound frontend as failed.
        if (Test-ListeningPort -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Ensure-Redis {
    if (Test-ListeningPort -Port 6379) {
        return
    }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw "Redis is not listening and docker.exe is unavailable"
    }

    $dockerReady = $false
    try {
        docker info *> $null
        $dockerReady = $LASTEXITCODE -eq 0
    } catch {
        $dockerReady = $false
    }

    if (-not $dockerReady) {
        $desktopCandidates = @(
            (Join-Path ${env:ProgramFiles} "Docker\Docker\Docker Desktop.exe"),
            (Join-Path ${env:LOCALAPPDATA} "Docker\Docker Desktop.exe")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        if ($desktopCandidates.Count -gt 0) {
            Start-Process -FilePath $desktopCandidates[0] -WindowStyle Hidden | Out-Null
        }

        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            try {
                docker info *> $null
                if ($LASTEXITCODE -eq 0) {
                    $dockerReady = $true
                    break
                }
            } catch { }
            Start-Sleep -Seconds 3
        }
    }
    if (-not $dockerReady) {
        throw "Docker Desktop did not become ready while starting the development environment"
    }

    $existing = @(docker ps -a --filter "name=^/caiyan-redis$" --format "{{.Names}}" 2>$null)
    if ($existing -contains "caiyan-redis") {
        $running = @(docker ps --filter "name=^/caiyan-redis$" --format "{{.Names}}" 2>$null)
        if ($running -notcontains "caiyan-redis") {
            docker start caiyan-redis | Out-Null
        }
    } else {
        docker run --name caiyan-redis -p 6379:6379 -d redis:7 | Out-Null
    }

    if (-not (Wait-TcpPort -Port 6379 -TimeoutSeconds 120)) {
        throw "Redis did not become reachable on 127.0.0.1:6379"
    }
}

function Get-ProcessByIdSafe {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Get-DevWorkerProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $cmd = [string]$_.CommandLine
        $cmd -and $_.Name -like "python*" -and $cmd -like "*celery*" -and
            ($cmd -like "*-Q celery_dev*" -or $cmd -like "*worker_dev@*")
    })
}

function Move-StalePidFile {
    if (-not (Test-Path -LiteralPath $devPidFile)) {
        return
    }
    $raw = (Get-Content -LiteralPath $devPidFile -Raw -ErrorAction SilentlyContinue).Trim()
    $pidValue = 0
    if ([int]::TryParse($raw, [ref]$pidValue)) {
        $process = Get-ProcessByIdSafe -ProcessId $pidValue
        if ($process) {
            $commandLine = [string]$process.CommandLine
            if ($process.Name -like "python*" -and $commandLine -like "*celery*" -and
                ($commandLine -like "*-Q celery_dev*" -or $commandLine -like "*worker_dev@*")) {
                return
            }
        }
    }
    $stalePath = "$devPidFile.stale-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Move-Item -LiteralPath $devPidFile -Destination $stalePath -Force
    Write-StartupLog "WARN" "moved stale development worker pid file to $stalePath"
}

function Start-DevBackend {
    param([string]$PythonExe)
    $listeners = @(Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        Write-StartupLog "INFO" "development backend port 8001 is already listening"
        return
    }
    $args = @(
        "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001",
        "--workers", "1", "--timeout-keep-alive", "120"
    )
    Start-Process -FilePath $PythonExe -ArgumentList $args -WorkingDirectory $devBackendRoot `
        -RedirectStandardOutput $devBackendStdout -RedirectStandardError $devBackendStderr -WindowStyle Hidden | Out-Null
    # Cold imports can exceed 90 seconds on Windows when Python dependencies
    # and database bootstrap code are not yet in the filesystem cache.
    if (-not (Wait-TcpPort -Port 8001 -TimeoutSeconds 180)) {
        throw "development backend did not start listening on port 8001"
    }
    Write-StartupLog "INFO" "development backend started on port 8001"
}

function Test-DevBackend {
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health/version" -TimeoutSec 5
        return [string]$version.env -eq "dev"
    } catch {
        return $false
    }
}

function Start-DevWorker {
    param([string]$PythonExe)
    $existing = Get-DevWorkerProcesses
    if ($existing.Count -gt 0) {
        Write-StartupLog "INFO" "development Celery worker is already running"
        return
    }

    Move-StalePidFile
    $machineName = [Environment]::MachineName
    if (-not $machineName) {
        $machineName = "localhost"
    }
    $args = @(
        "-m", "celery", "-A", "app.core.celery_app.celery_app", "worker",
        "--loglevel=info", "--pool=solo", "-Q", "celery_dev", "-n", "worker_dev@$machineName",
        "--pidfile=$devPidFile", "--logfile=$devWorkerLog"
    )
    Start-Process -FilePath $PythonExe -ArgumentList $args -WorkingDirectory $devBackendRoot `
        -RedirectStandardOutput $devWorkerStdout -RedirectStandardError $devWorkerStderr -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if ((Get-DevWorkerProcesses).Count -gt 0) {
            Write-StartupLog "INFO" "development Celery worker started on celery_dev"
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "development Celery worker did not become visible on celery_dev"
}

function Start-DevFrontend {
    $listeners = @(Get-NetTCPConnection -LocalPort 5276 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        Write-StartupLog "INFO" "development frontend port 5276 is already listening"
        return
    }
    # Scheduled tasks do not always inherit the interactive user's PATH.  A
    # prior version found npm through Get-Command and then failed with
    # "file not found" at logon even though Node was installed.  Resolve the
    # command and fall back to the standard per-machine/per-user locations.
    $npmCandidates = @()
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npm) {
        $npmCandidates += [string]$npm.Source
        if (-not [string]$npm.Source) {
            $npmCandidates += [string]$npm.Path
        }
    }
    $npmCandidates += @(
        (Join-Path ${env:ProgramFiles} "nodejs\npm.cmd"),
        (Join-Path ${env:APPDATA} "npm\npm.cmd")
    )
    $npmPath = @($npmCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1)[0]
    if (-not $npmPath) {
        throw "npm.cmd is unavailable while starting the development frontend"
    }
    $cmdExe = Join-Path $env:SystemRoot "System32\cmd.exe"
    if (-not (Test-Path -LiteralPath $cmdExe)) {
        throw "cmd.exe is unavailable while starting the development frontend"
    }
    $npmInvocation = '"' + $npmPath + '" run dev:dev'
    Start-Process -FilePath $cmdExe -ArgumentList @("/d", "/c", $npmInvocation) -WorkingDirectory $devFrontendRoot `
        -RedirectStandardOutput $devFrontendStdout -RedirectStandardError $devFrontendStderr -WindowStyle Hidden | Out-Null
    # Vite may also need more than 90 seconds during a cold dependency scan.
    if (-not (Wait-TcpPort -Port 5276 -TimeoutSeconds 180)) {
        throw "development frontend did not start listening on port 5276"
    }
    Write-StartupLog "INFO" "development frontend started on port 5276"
}

$mutex = New-Object System.Threading.Mutex($false, "Local\CaiYanDevelopmentServiceControl")
$lockAcquired = $false

try {
    try {
        $lockAcquired = $mutex.WaitOne([TimeSpan]::FromSeconds([Math]::Max(0, $LockWaitSeconds)))
    } catch [System.Threading.AbandonedMutexException] {
        $lockAcquired = $true
        Write-StartupLog "WARN" "recovered abandoned development service-control lock"
    }
    if (-not $lockAcquired) {
        Write-StartupLog "INFO" "another development startup is already running; skip duplicate launch"
        exit 0
    }

    Import-EnvironmentFile -Path $envFile
    if ([string]$env:APP_ENV -ne "dev" -or [string]$env:BACKEND_PORT -ne "8001" -or
        [string]$env:CELERY_QUEUE -ne "celery_dev" -or [string]$env:CELERY_WORKER_NAME -ne "worker_dev") {
        throw "development environment validation failed: APP_ENV/port/queue/worker do not match dev"
    }
    $env:CAIYAN_ENV_FILE = $envFile
    if ([string]$env:DATABASE_URL -match "product_knowledge(?:[/?#]|$)") {
        throw "refusing to start development environment with production database"
    }

    $pythonExe = Join-Path $devBackendRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "development Python executable is missing: $pythonExe"
    }
    Ensure-Redis
    Start-DevBackend -PythonExe $pythonExe
    if (-not (Test-DevBackend)) {
        throw "development backend responded but did not identify as APP_ENV=dev"
    }
    Start-DevWorker -PythonExe $pythonExe
    Start-DevFrontend

    Write-StartupLog "INFO" "development startup completed successfully"
    Write-Output "STARTUP OK env=dev backend=8001 frontend=5276 queue=celery_dev"
    exit 0
} catch {
    Write-StartupLog "ERROR" $_.Exception.Message
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($lockAcquired) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    $mutex.Dispose()
}
