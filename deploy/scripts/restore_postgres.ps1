param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase,
    [string]$EnvFile = "",
    [string]$PgBin = "C:\Program Files\PostgreSQL\18\bin"
)

$ErrorActionPreference = "Stop"

if (-not $EnvFile) {
    $EnvFile = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\backend\.env"))
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
    }
}

$envValues = Read-DotEnv -Path $EnvFile
if (-not $envValues.ContainsKey("DATABASE_URL")) {
    throw "DATABASE_URL not found in $EnvFile"
}

$db = Convert-DatabaseUrl -DatabaseUrl $envValues["DATABASE_URL"]
$pgRestore = Join-Path $PgBin "pg_restore.exe"
if (-not (Test-Path $pgRestore)) {
    throw "pg_restore.exe not found: $pgRestore"
}
if (-not (Test-Path $BackupFile)) {
    throw "Backup file not found: $BackupFile"
}

$env:PGPASSWORD = $db.Password
& $pgRestore `
    --host $db.Host `
    --port $db.Port `
    --username $db.User `
    --dbname $TargetDatabase `
    --no-owner `
    --no-privileges `
    $BackupFile

if ($LASTEXITCODE -ne 0) {
    throw "pg_restore failed with exit code $LASTEXITCODE"
}

Write-Output "Restored $BackupFile to database $TargetDatabase"
