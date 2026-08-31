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

if (-not $LogPath) {
    $LogPath = Join-Path $RuntimeRoot "logs\startup.log"
}
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null

function Write-StartupLog {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "$timestamp [$Level] $Message" -Encoding utf8
}

function Remove-OrphanedBackendWorkers {
    $prodPython = [System.IO.Path]::GetFullPath(
        (Join-Path $RuntimeRoot "backend\runtime\prod-venv\Scripts\python.exe")
    )
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $ownerPid = [int]$listener.OwningProcess
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($owner) {
            continue
        }

        $orphans = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $cmd = [string]$_.CommandLine
            $_.ParentProcessId -eq $ownerPid -and
            $_.Name -like "python*" -and
            $cmd -like "*$prodPython*" -and
            $cmd -like "*multiprocessing.spawn*" -and
            $cmd -like "*--multiprocessing-fork*"
        })
        if (-not $orphans) {
            throw "port 8000 has an unresolved listener pid=$ownerPid without validated production worker children"
        }

        foreach ($orphan in $orphans) {
            Write-StartupLog "WARN" "stopping orphaned production backend worker pid=$($orphan.ProcessId) phantom_parent=$ownerPid"
            Stop-Process -Id ([int]$orphan.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $listeners) {
        return
    }
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        $unresolved = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Where-Object {
            -not (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue)
        })
        if (-not $unresolved) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "port 8000 still has an unresolved listener after orphan cleanup"
}

$mutex = New-Object System.Threading.Mutex($false, "Local\CaiYanProductionServiceControl")
$lockAcquired = $false

try {
    try {
        $lockAcquired = $mutex.WaitOne([TimeSpan]::FromSeconds([Math]::Max(0, $LockWaitSeconds)))
    } catch [System.Threading.AbandonedMutexException] {
        $lockAcquired = $true
        Write-StartupLog "WARN" "recovered abandoned production service-control lock"
    }

    if (-not $lockAcquired) {
        Write-StartupLog "INFO" "another production startup or health-recovery action is already running; skip duplicate launch"
        Write-Output "STARTUP SKIPPED already running"
        exit 0
    }

    Remove-OrphanedBackendWorkers

    $pointerPath = Join-Path $RuntimeRoot "backend\runtime\production-release.json"
    if (-not (Test-Path -LiteralPath $pointerPath)) {
        throw "active production release pointer is missing: $pointerPath"
    }

    $pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding utf8 | ConvertFrom-Json
    $releaseRoot = [System.IO.Path]::GetFullPath([string]$pointer.release_root)
    $expectedCommit = [string]$pointer.commit
    if (-not $expectedCommit -or $expectedCommit -notmatch "^[0-9a-fA-F]{40}$") {
        throw "active production release commit is missing or invalid"
    }

    $serviceScript = Join-Path $releaseRoot "deploy\scripts\service_control_windows.ps1"
    if (-not (Test-Path -LiteralPath $serviceScript)) {
        throw "active production service controller is missing: $serviceScript"
    }

    $envFile = Join-Path $RuntimeRoot "backend\.env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw "production environment file is missing: $envFile"
    }

    Write-StartupLog "INFO" "starting active production release commit=$expectedCommit root=$releaseRoot"
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $serviceScript,
        "-Action", "All",
        "-RepoRoot", $releaseRoot,
        "-RuntimeRoot", $RuntimeRoot,
        "-DependencyRoot", $RuntimeRoot,
        "-EnvFile", $envFile,
        "-LogPath", (Join-Path $RuntimeRoot "logs\watchdog.log"),
        "-ExpectedCommit", $expectedCommit
    )
    & powershell.exe @arguments
    $serviceExitCode = $LASTEXITCODE
    if ($serviceExitCode -ne 0) {
        throw "production service controller exited with code $serviceExitCode"
    }

    Write-StartupLog "INFO" "production startup completed successfully"
    Write-Output "STARTUP OK commit=$expectedCommit"
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
