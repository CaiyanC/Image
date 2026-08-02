param(
    [int]$BackendPort = 8003,
    [int]$FrontendPort = 5277,
    [string]$PreviewDatabase = "product_knowledge_toolpreview"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$envFile = Join-Path $backend ".env.dev"

if (-not (Test-Path $envFile)) { throw "Missing preview source environment: $envFile" }
foreach ($line in Get-Content $envFile) {
    if ($line -match '^([^#=]+)=(.*)$') {
        Set-Item -Path ("Env:" + $matches[1]) -Value $matches[2]
    }
}

foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Preview port $port is already in use. Choose another isolated port."
    }
}

$devDatabase = "product_knowledge_dev"
if ($env:DATABASE_URL -notmatch "/$devDatabase(\?|$)") {
    throw "Preview must start from the development database URL ending in $devDatabase."
}

$env:APP_ENV = "preview"
$env:BACKEND_PORT = "$BackendPort"
$env:DATABASE_URL = $env:DATABASE_URL -replace "/$devDatabase(\?|$)", "/$PreviewDatabase`$1"
$env:REDIS_URL = $env:REDIS_URL -replace "/1(\?|$)", "/2`$1"
$env:CELERY_QUEUE = "celery_toolpreview"
$env:CELERY_WORKER_NAME = "worker_toolpreview"
$env:UPLOAD_DIR = "uploads_toolpreview"
$env:LOG_DIR = "logs_toolpreview"
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"

# Create the isolated database if needed. The URL is read only from the local
# environment and is never written to the command line or logs.
python -c "import os; from sqlalchemy import create_engine, text; from sqlalchemy.engine import make_url; u=make_url(os.environ['DATABASE_URL']); e=create_engine(u.set(database='postgres'), isolation_level='AUTOCOMMIT', hide_parameters=True); c=e.connect(); n=u.database; exists=c.execute(text('SELECT 1 FROM pg_database WHERE datname=:n'), {'n': n}).scalar() is not None; c.execute(text('CREATE DATABASE ' + n)) if not exists else None; c.close(); print('preview database ' + ('exists' if exists else 'created'))"

$backendProcess = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--workers", "1", "--timeout-keep-alive", "120" `
    -WorkingDirectory $backend -WindowStyle Hidden -PassThru
$frontendProcess = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort" `
    -WorkingDirectory $frontend -WindowStyle Hidden -PassThru

Write-Host "Preview backend PID: $($backendProcess.Id)"
Write-Host "Preview frontend PID: $($frontendProcess.Id)"
Write-Host "Open: http://127.0.0.1:$FrontendPort/admin/model-governance"
