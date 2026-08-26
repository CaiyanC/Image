param(
    [string]$RuntimeRoot = "",
    [string]$UserId = $env:USERNAME,
    [string]$TaskName = "CaiYanStartupProduction",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

if (-not $RuntimeRoot) {
    $RuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)

$sourceScript = Join-Path $RuntimeRoot "deploy\scripts\startup_production_windows.ps1"
if (-not (Test-Path -LiteralPath $sourceScript)) {
    throw "startup source script is missing: $sourceScript"
}

# The scheduled task uses a runtime copy so a temporary git branch switch cannot
# make the boot entry point disappear. Re-running this installer refreshes it.
$runtimeScriptDir = Join-Path $RuntimeRoot "backend\runtime\startup"
$runtimeScript = Join-Path $runtimeScriptDir "startup_production_windows.ps1"
New-Item -ItemType Directory -Force -Path $runtimeScriptDir | Out-Null
Copy-Item -LiteralPath $sourceScript -Destination $runtimeScript -Force

$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $powerShellExe)) {
    throw "Windows PowerShell executable is missing: $powerShellExe"
}

$quotedScript = '"' + $runtimeScript + '"'
$quotedRoot = '"' + $RuntimeRoot + '"'
$action = New-ScheduledTaskAction `
    -Execute $powerShellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File $quotedScript -RuntimeRoot $quotedRoot"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$trigger.Delay = "PT15S"
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start the active immutable CaiYan production release after Windows logon." `
    -Force | Out-Null

$legacyTasks = @(
    "CaiYanStartupRedis",
    "CaiYanStartupBackend",
    "CaiYanStartupWorker",
    "CaiYanStartupFrontend"
)
foreach ($legacyTask in $legacyTasks) {
    if (Get-ScheduledTask -TaskName $legacyTask -ErrorAction SilentlyContinue) {
        Disable-ScheduledTask -TaskName $legacyTask | Out-Null
    }
}

try {
    if ((Get-Command docker -ErrorAction SilentlyContinue) -and
        (docker ps -a --filter "name=^/caiyan-redis$" --format "{{.Names}}" 2>$null) -eq "caiyan-redis") {
        docker update --restart unless-stopped caiyan-redis | Out-Null
    }
} catch {
    Write-Warning "Could not update the Redis restart policy: $($_.Exception.Message)"
}

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Output "TASK=$TaskName"
Write-Output "SCRIPT=$runtimeScript"
Write-Output "USER=$UserId"
Write-Output "LEGACY_TASKS_DISABLED=$($legacyTasks -join ',')"
