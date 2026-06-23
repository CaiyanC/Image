param(
    [string]$UploadsPath = "",
    [string]$DriveLetter = "D",
    [decimal]$MinFreeGB = 20,
    [decimal]$MaxUploadsGB = 100,
    [string]$LogPath = "",
    [string]$StatePath = "",
    [int]$NotifyCooldownHours = 24,
    [switch]$NoNotify
)

$ErrorActionPreference = "Stop"

if (-not $UploadsPath) {
    $UploadsPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backend\uploads"))
}
if (-not $LogPath) {
    $LogPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\logs\storage_monitor.log"))
}
if (-not $StatePath) {
    $StatePath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backend\runtime\storage_monitor_state.json"))
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogPath -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $StatePath -Parent) | Out-Null
if (-not (Test-Path $UploadsPath)) {
    New-Item -ItemType Directory -Force -Path $UploadsPath | Out-Null
}

function Write-StorageLog {
    param([string]$Level, [string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "$timestamp [$Level] $Message" -Encoding utf8
}

function Read-State {
    if (-not (Test-Path $StatePath)) {
        return [pscustomobject]@{
            status = "unknown"
            last_notify_at = $null
            last_reason = $null
        }
    }
    try {
        return Get-Content $StatePath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            status = "unknown"
            last_notify_at = $null
            last_reason = "state file unreadable: $($_.Exception.Message)"
        }
    }
}

function Save-State {
    param([object]$State)
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $StatePath -Encoding utf8
}

function Send-StorageNotification {
    param([string]$Title, [string]$Message)
    if ($NoNotify) {
        Write-StorageLog "INFO" "notification suppressed by NoNotify: $Title"
        return
    }
    $text = "$Title`n$Message"
    $msg = Get-Command msg.exe -ErrorAction SilentlyContinue
    if ($msg) {
        & msg.exe $env:USERNAME /TIME:60 $text
        if ($LASTEXITCODE -eq 0) {
            Write-StorageLog "INFO" "notification sent via msg.exe: $Title"
            return
        }
        Write-StorageLog "WARN" "msg.exe notification failed with exit code $LASTEXITCODE"
    } else {
        Write-StorageLog "WARN" "msg.exe not found; notification not sent"
    }
}

function Get-DirectorySizeBytes {
    param([string]$Path)
    $sum = 0L
    if (Test-Path $Path) {
        Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
            ForEach-Object { $sum += $_.Length }
    }
    return $sum
}

$now = Get-Date
$uploadsBytes = Get-DirectorySizeBytes -Path $UploadsPath
$uploadsGB = [math]::Round($uploadsBytes / 1GB, 2)
$driveName = $DriveLetter.TrimEnd(":")
$drive = Get-PSDrive -Name $driveName -ErrorAction Stop
$freeGB = [math]::Round($drive.Free / 1GB, 2)
$usedGB = [math]::Round($drive.Used / 1GB, 2)
$totalGB = [math]::Round(($drive.Free + $drive.Used) / 1GB, 2)

$issues = @()
if ($freeGB -lt $MinFreeGB) {
    $issues += "drive ${driveName}: free ${freeGB}GB below threshold ${MinFreeGB}GB"
}
if ($uploadsGB -gt $MaxUploadsGB) {
    $issues += "uploads ${uploadsGB}GB above threshold ${MaxUploadsGB}GB"
}

$state = Read-State
$status = if ($issues.Count -gt 0) { "warning" } else { "ok" }
$summary = "uploads=${uploadsGB}GB drive=${driveName}: free=${freeGB}GB used=${usedGB}GB total=${totalGB}GB thresholds: minFree=${MinFreeGB}GB maxUploads=${MaxUploadsGB}GB"

if ($status -eq "ok") {
    if ($state.status -eq "warning") {
        $message = "CaiYan storage recovered. $summary"
        Write-StorageLog "INFO" $message
        Send-StorageNotification "CaiYan storage recovered" $message
    } else {
        Write-StorageLog "INFO" "storage ok: $summary"
    }
    Save-State ([pscustomobject]@{
        status = "ok"
        last_notify_at = $state.last_notify_at
        last_reason = $null
        checked_at = $now.ToString("o")
        uploads_gb = $uploadsGB
        drive_free_gb = $freeGB
    })
    Write-Output "OK $summary"
    exit 0
}

$reason = $issues -join "; "
Write-StorageLog "WARN" "storage threshold reached: $reason; $summary"

$lastNotifyAt = $null
if ($state.last_notify_at) {
    try { $lastNotifyAt = [datetime]::Parse($state.last_notify_at) } catch { $lastNotifyAt = $null }
}
$shouldNotify = $state.status -ne "warning" -or -not $lastNotifyAt -or (($now - $lastNotifyAt).TotalHours -ge $NotifyCooldownHours)
if ($shouldNotify) {
    Send-StorageNotification "CaiYan storage warning" "$reason. $summary"
    $lastNotifyAtValue = $now.ToString("o")
} else {
    Write-StorageLog "INFO" "notification suppressed by cooldown: $reason"
    $lastNotifyAtValue = $state.last_notify_at
}

Save-State ([pscustomobject]@{
    status = "warning"
    last_notify_at = $lastNotifyAtValue
    last_reason = $reason
    checked_at = $now.ToString("o")
    uploads_gb = $uploadsGB
    drive_free_gb = $freeGB
})

Write-Output "WARNING $reason; $summary"
exit 1
