param(
    [string]$EnvFile = "",
    [string]$BackupDir = "",
    [int]$RetentionDays = 14,
    [string]$PgBin = "C:\Program Files\PostgreSQL\18\bin"
)

$ErrorActionPreference = "Stop"

if (-not $EnvFile) {
    $EnvFile = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backend\.env"))
}
if (-not $BackupDir) {
    $BackupDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backups\postgres"))
}

function Read-DotEnv {
    param([string]$Path)

    $result = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $key, $value = $line -split "=", 2
        $result[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $result
}

function Convert-DatabaseUrl {
    param([string]$DatabaseUrl)

    $uriText = $DatabaseUrl -replace "^postgresql\+psycopg2://", "postgresql://"
    $uri = [Uri]$uriText
    $userParts = $uri.UserInfo -split ":", 2

    return @{
        Host = $uri.Host
        Port = $uri.Port
        User = [Uri]::UnescapeDataString($userParts[0])
        Password = [Uri]::UnescapeDataString($userParts[1])
        Database = $uri.AbsolutePath.TrimStart("/")
    }
}

$envValues = Read-DotEnv -Path $EnvFile
if (-not $envValues.ContainsKey("DATABASE_URL")) {
    throw "DATABASE_URL not found in $EnvFile"
}

$db = Convert-DatabaseUrl -DatabaseUrl $envValues["DATABASE_URL"]
$pgDump = Join-Path $PgBin "pg_dump.exe"
if (-not (Test-Path $pgDump)) {
    throw "pg_dump.exe not found: $pgDump"
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir "$($db.Database)_$timestamp.dump"

$env:PGPASSWORD = $db.Password
& $pgDump `
    --host $db.Host `
    --port $db.Port `
    --username $db.User `
    --format custom `
    --file $target `
    $db.Database

if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE"
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem $BackupDir -Filter "$($db.Database)_*.dump" |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    Remove-Item -Force

$item = Get-Item $target
Write-Output "Backup created: $($item.FullName)"
Write-Output "Size bytes: $($item.Length)"
