param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$FrontendUrl = "http://127.0.0.1:5275",
    [string]$LogPath = "",
    [string]$StatePath = "",
    [int]$NotifyCooldownMinutes = 30,
    [int]$TimeoutSeconds = 8,
    [bool]$EnableWatchdog = $true
)

$ErrorActionPreference = "Stop"

if (-not $LogPath) {
    $LogPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\logs\health_check.log"))
}
if (-not $StatePath) {
    $StatePath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backend\runtime\health_check_state.json"))
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $StatePath -Parent) | Out-Null

$ProdQueue = "celery_prod"
$ProdWorkerName = "worker_prod"

function Write-HealthLog {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "$timestamp [$Level] $Message" -Encoding utf8
}

function Read-State {
    if (-not (Test-Path $StatePath)) {
        return [pscustomobject]@{
            status = "unknown"
            first_failure_at = $null
            last_notify_at = $null
            last_reason = $null
        }
    }
    try {
        return Get-Content $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            status = "unknown"
            first_failure_at = $null
            last_notify_at = $null
            last_reason = "state file unreadable: $($_.Exception.Message)"
        }
    }
}

function Save-State {
    param([object]$State)
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $StatePath -Encoding utf8
}

function Send-HealthNotification {
    param([string]$Title, [string]$Message)

    $text = "$Title`n$Message"
    $msg = Get-Command msg.exe -ErrorAction SilentlyContinue
    if ($msg) {
        & msg.exe $env:USERNAME /TIME:60 $text
        if ($LASTEXITCODE -eq 0) {
            Write-HealthLog "INFO" "notification sent via msg.exe: $Title"
            return
        }
        Write-HealthLog "WARN" "msg.exe notification failed with exit code $LASTEXITCODE"
    } else {
        Write-HealthLog "WARN" "msg.exe not found; notification not sent"
    }
}

function Test-Endpoint {
    param([string]$Path)
    $url = "$BaseUrl$Path"
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec $TimeoutSeconds
        if ($Path -eq "/api/health/ready" -and $response.status -ne "ok") {
            return [pscustomobject]@{
                ok = $false
                detail = "$Path returned status=$($response.status)"
            }
        }
        return [pscustomobject]@{
            ok = $true
            detail = "$Path ok"
        }
    } catch {
        return [pscustomobject]@{
            ok = $false
            detail = "$Path failed: $($_.Exception.Message)"
        }
    }
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return [pscustomobject]@{
            ok = ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500)
            detail = "$Url status=$([int]$response.StatusCode)"
        }
    } catch {
        return [pscustomobject]@{
            ok = $false
            detail = "$Url failed: $($_.Exception.Message)"
        }
    }
}

function Test-Redis {
    try {
        $pong = docker exec caiyan-redis redis-cli ping 2>$null
        return [pscustomobject]@{
            ok = ($pong -eq "PONG")
            detail = "redis ping=$pong"
        }
    } catch {
        return [pscustomobject]@{
            ok = $false
            detail = "redis failed: $($_.Exception.Message)"
        }
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
    if ($workers) {
        return [pscustomobject]@{
            ok = $true
            detail = "prod worker running"
        }
    }
    return [pscustomobject]@{
        ok = $false
        detail = "prod worker not found"
    }
}

function Invoke-WatchdogAction {
    param([string]$Action)
    $watchdogScript = Join-Path $PSScriptRoot "service_control_windows.ps1"
    if (-not (Test-Path $watchdogScript)) {
        Write-HealthLog "ERROR" "watchdog script not found: $watchdogScript"
        return
    }
    Write-HealthLog "WARN" "invoking prod watchdog action: $Action"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $watchdogScript -Action $Action | Out-Null
}

$state = Read-State
$now = Get-Date
$live = Test-Endpoint "/api/health/live"
$ready = Test-Endpoint "/api/health/ready"
$frontend = Test-HttpOk $FrontendUrl
$redis = Test-Redis
$worker = Test-ProdWorker
$backendHealthy = $live.ok -and $ready.ok
$healthy = $backendHealthy -and $frontend.ok -and $redis.ok -and $worker.ok

if (-not $healthy -and $EnableWatchdog) {
    if (-not $redis.ok) {
        Invoke-WatchdogAction "Redis"
    }
    if (-not $backendHealthy) {
        Invoke-WatchdogAction "Backend"
    }
    if (-not $frontend.ok) {
        Invoke-WatchdogAction "Frontend"
    }
    if (-not $worker.ok) {
        Invoke-WatchdogAction "Worker"
    }

    $live = Test-Endpoint "/api/health/live"
    $ready = Test-Endpoint "/api/health/ready"
    $frontend = Test-HttpOk $FrontendUrl
    $redis = Test-Redis
    $worker = Test-ProdWorker
    $backendHealthy = $live.ok -and $ready.ok
    $healthy = $backendHealthy -and $frontend.ok -and $redis.ok -and $worker.ok
}

if ($healthy) {
    if ($state.status -eq "unhealthy") {
        $message = "CaiYan prod health recovered. backend=ok frontend=ok redis=ok worker=ok"
        Write-HealthLog "INFO" $message
        Send-HealthNotification "CaiYan service recovered" $message
    }
    Save-State ([pscustomobject]@{
        status = "healthy"
        first_failure_at = $null
        last_notify_at = $state.last_notify_at
        last_reason = $null
        checked_at = $now.ToString("o")
    })
    Write-Output "HEALTHY prod backend=ok frontend=ok redis=ok worker=ok"
    exit 0
}

$reason = @($live.detail, $ready.detail, $frontend.detail, $redis.detail, $worker.detail) -join "; "
Write-HealthLog "ERROR" "health check failed: $reason"

$lastNotifyAt = $null
if ($state.last_notify_at) {
    try { $lastNotifyAt = [datetime]::Parse($state.last_notify_at) } catch { $lastNotifyAt = $null }
}
$shouldNotify = $state.status -ne "unhealthy" -or -not $lastNotifyAt -or (($now - $lastNotifyAt).TotalMinutes -ge $NotifyCooldownMinutes)

if ($shouldNotify) {
    Send-HealthNotification "CaiYan service health check failed" $reason
    $lastNotifyAtValue = $now.ToString("o")
} else {
    $lastNotifyAtValue = $state.last_notify_at
}

$firstFailureAt = if ($state.status -eq "unhealthy" -and $state.first_failure_at) { $state.first_failure_at } else { $now.ToString("o") }
Save-State ([pscustomobject]@{
    status = "unhealthy"
    first_failure_at = $firstFailureAt
    last_notify_at = $lastNotifyAtValue
    last_reason = $reason
    checked_at = $now.ToString("o")
})

Write-Output "UNHEALTHY $reason"
exit 1
