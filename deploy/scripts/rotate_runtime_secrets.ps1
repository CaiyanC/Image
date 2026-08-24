param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [ValidateSet("PrepareModelKey", "MarkModelMigrationComplete", "RotateSecret")]
    [string]$Action,
    [switch]$AllowInsecureLocalProd
)

$ErrorActionPreference = "Stop"
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)
if (-not (Test-Path $EnvFile)) {
    throw "Environment file not found: $EnvFile"
}

$lines = [System.Collections.Generic.List[string]]::new()
Get-Content $EnvFile -Encoding utf8 | ForEach-Object { $lines.Add($_) }

function Get-EnvValue {
    param([string]$Key)
    foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1]
        }
    }
    return ""
}

function Set-EnvValue {
    param([string]$Key, [string]$Value)
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Key))=") {
            $lines[$index] = "$Key=$Value"
            return
        }
    }
    $lines.Add("$Key=$Value")
}

function New-RandomBase64 {
    param([int]$ByteCount)
    $bytes = New-Object byte[] $ByteCount
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

$changed = $false
$appEnv = (Get-EnvValue "APP_ENV").ToLowerInvariant()
switch ($Action) {
    "PrepareModelKey" {
        if (-not (Get-EnvValue "MODEL_CREDENTIAL_ENCRYPTION_KEY")) {
            Set-EnvValue "MODEL_CREDENTIAL_ENCRYPTION_KEY" (New-RandomBase64 32)
            $changed = $true
        }
        if ($appEnv -eq "prod") {
            if (Get-EnvValue "DEFAULT_ADMIN_PASSWORD") {
                Set-EnvValue "DEFAULT_ADMIN_PASSWORD" ""
                $changed = $true
            }
            Set-EnvValue "ALLOW_ADMIN_BOOTSTRAP" "false"
            if ($AllowInsecureLocalProd) {
                Set-EnvValue "AUTH_COOKIE_SECURE" "false"
                Set-EnvValue "ALLOW_INSECURE_LOCAL_PROD" "true"
            }
            $productionOrigins = [System.Collections.Generic.List[string]]::new()
            $productionOrigins.Add("http://localhost:5275")
            $productionOrigins.Add("http://127.0.0.1:5275")
            Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.IPAddress -match "^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)"
                } |
                ForEach-Object {
                    $origin = "http://$($_.IPAddress):5275"
                    if (-not $productionOrigins.Contains($origin)) {
                        $productionOrigins.Add($origin)
                    }
                }
            $corsValue = $productionOrigins -join ","
            if ((Get-EnvValue "CORS_ORIGINS") -ne $corsValue) {
                Set-EnvValue "CORS_ORIGINS" $corsValue
                $changed = $true
            }
        }
    }
    "MarkModelMigrationComplete" {
        if (-not (Get-EnvValue "MODEL_CREDENTIAL_ENCRYPTION_KEY")) {
            throw "Cannot mark migration complete without MODEL_CREDENTIAL_ENCRYPTION_KEY"
        }
        Set-EnvValue "MODEL_CREDENTIAL_KEY_MIGRATION_COMPLETE" "true"
        $changed = $true
    }
    "RotateSecret" {
        if ((Get-EnvValue "MODEL_CREDENTIAL_KEY_MIGRATION_COMPLETE").ToLowerInvariant() -ne "true") {
            throw "Model credential migration must complete before SECRET_KEY rotation"
        }
        if ((Get-EnvValue "SECRET_ROTATION_COMPLETE").ToLowerInvariant() -ne "true") {
            Set-EnvValue "SECRET_KEY" (New-RandomBase64 48)
            Set-EnvValue "SECRET_ROTATION_COMPLETE" "true"
            $changed = $true
        }
    }
}

if ($changed) {
    $temporary = "$EnvFile.$([guid]::NewGuid().ToString('N')).tmp"
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($temporary, [string[]]$lines, $utf8WithoutBom)
    Move-Item -LiteralPath $temporary -Destination $EnvFile -Force
}

Write-Output "CHANGED=$($changed.ToString().ToLowerInvariant())"
