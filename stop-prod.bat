@echo off
setlocal

title CaiYan Production Services Stopper
cd /d "%~dp0"
set "RUNTIME_ROOT=%~dp0."

echo Stopping production environment:
echo - Backend: 8000
echo - Frontend: 5275
echo - Database: product_knowledge
echo - Redis: redis://localhost:6379/0
echo - Queue: celery_prod
echo - Worker: worker_prod
echo - Logs: logs\prod
echo.

set "ACTIVE_RELEASE_ROOT=%RUNTIME_ROOT%"
set "ACTIVE_RELEASE_COMMIT="
if exist "%RUNTIME_ROOT%\backend\runtime\production-release.json" (
    for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -Raw -LiteralPath '%RUNTIME_ROOT%\backend\runtime\production-release.json')).release_root"`) do set "ACTIVE_RELEASE_ROOT=%%a"
    for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -Raw -LiteralPath '%RUNTIME_ROOT%\backend\runtime\production-release.json')).commit"`) do set "ACTIVE_RELEASE_COMMIT=%%a"
)
if not exist "%ACTIVE_RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" (
    echo Active production release is invalid: %ACTIVE_RELEASE_ROOT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%ACTIVE_RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action StopAll -RepoRoot "%ACTIVE_RELEASE_ROOT%" -RuntimeRoot "%RUNTIME_ROOT%" -DependencyRoot "%RUNTIME_ROOT%" -EnvFile "%RUNTIME_ROOT%\backend\.env" -LogPath "%RUNTIME_ROOT%\logs\watchdog.log" -ExpectedCommit "%ACTIVE_RELEASE_COMMIT%" -AllowLegacySharedProcess
exit /b %errorlevel%
