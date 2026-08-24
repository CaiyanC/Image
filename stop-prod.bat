@echo off
setlocal

title CaiYan Production Services Stopper
cd /d "%~dp0"

echo Stopping production environment:
echo - Backend: 8000
echo - Frontend: 5275
echo - Database: product_knowledge
echo - Redis: redis://localhost:6379/0
echo - Queue: celery_prod
echo - Worker: worker_prod
echo - Logs: logs\prod
echo.

set "ACTIVE_RELEASE_ROOT=%~dp0"
set "ACTIVE_RELEASE_COMMIT="
if exist "%~dp0backend\runtime\production-release.json" (
    for /f "tokens=1,* delims==" %%a in ('powershell -NoProfile -Command "$p = Get-Content -Raw -LiteralPath ''%~dp0backend\runtime\production-release.json'' | ConvertFrom-Json; Write-Output (''ACTIVE_RELEASE_ROOT='' + $p.release_root); Write-Output (''ACTIVE_RELEASE_COMMIT='' + $p.commit)"') do set "%%a=%%b"
)
if not exist "%ACTIVE_RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" (
    echo Active production release is invalid: %ACTIVE_RELEASE_ROOT%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%ACTIVE_RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action StopAll -RepoRoot "%ACTIVE_RELEASE_ROOT%" -RuntimeRoot "%~dp0" -DependencyRoot "%~dp0" -EnvFile "%~dp0backend\.env" -LogPath "%~dp0logs\watchdog.log" -ExpectedCommit "%ACTIVE_RELEASE_COMMIT%" -AllowLegacySharedProcess
exit /b %errorlevel%
