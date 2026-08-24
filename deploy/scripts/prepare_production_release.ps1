param(
    [string]$SourceRepo = "",
    [string]$Commit = "",
    [string]$ReleasesRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $SourceRepo) {
    $SourceRepo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$SourceRepo = [System.IO.Path]::GetFullPath($SourceRepo)
if (-not $ReleasesRoot) {
    $ReleasesRoot = [System.IO.Path]::GetFullPath("${SourceRepo}-prod-releases")
}

$branch = (& git -C $SourceRepo rev-parse --abbrev-ref HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "master") {
    throw "Production releases must be prepared from the master branch; current branch is $branch"
}
& git -C $SourceRepo diff --quiet --
if ($LASTEXITCODE -ne 0) {
    throw "Tracked working-tree changes must be committed before preparing a production release"
}
& git -C $SourceRepo diff --cached --quiet --
if ($LASTEXITCODE -ne 0) {
    throw "Staged changes must be committed before preparing a production release"
}

if (-not $Commit) {
    $Commit = (& git -C $SourceRepo rev-parse HEAD).Trim()
}
$resolvedCommit = (& git -C $SourceRepo rev-parse "$Commit^{commit}").Trim()
if ($LASTEXITCODE -ne 0 -or -not $resolvedCommit) {
    throw "Cannot resolve production commit: $Commit"
}

New-Item -ItemType Directory -Force -Path $ReleasesRoot | Out-Null
$releaseRoot = Join-Path $ReleasesRoot $resolvedCommit
if (Test-Path $releaseRoot) {
    $releaseCommit = (& git -C $releaseRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $releaseCommit -ne $resolvedCommit) {
        throw "Existing release path does not match requested commit: $releaseRoot"
    }
} else {
    & git -C $SourceRepo worktree add --detach $releaseRoot $resolvedCommit
    if ($LASTEXITCODE -ne 0) {
        throw "git worktree add failed for $resolvedCommit"
    }
}

$npm = Get-Command "npm.cmd" -ErrorAction Stop
Push-Location (Join-Path $SourceRepo "frontend")
try {
    & $npm.Source ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "frontend production build failed" }
} finally {
    Pop-Location
}

$releaseDist = Join-Path $releaseRoot "frontend\dist"
New-Item -ItemType Directory -Force -Path $releaseDist | Out-Null
Copy-Item -Path (Join-Path $SourceRepo "frontend\dist\*") -Destination $releaseDist -Recurse -Force

$prodVenv = Join-Path $SourceRepo "backend\runtime\prod-venv"
$prodPython = Join-Path $prodVenv "Scripts\python.exe"
if (-not (Test-Path $prodPython)) {
    & python -m venv $prodVenv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create production virtual environment" }
}
& $prodPython -m pip install -r (Join-Path $releaseRoot "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Production dependency installation failed" }

$pointerDir = Join-Path $SourceRepo "backend\runtime"
New-Item -ItemType Directory -Force -Path $pointerDir | Out-Null
@{
    commit = $resolvedCommit
    release_root = $releaseRoot
    prepared_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json | Set-Content -Path (Join-Path $pointerDir "production-release.json") -Encoding utf8

Write-Output "RELEASE_ROOT=$releaseRoot"
Write-Output "RELEASE_COMMIT=$resolvedCommit"
