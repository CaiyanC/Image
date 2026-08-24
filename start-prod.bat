@echo off
setlocal

title CaiYan Production Release Launcher
cd /d "%~dp0"

echo Starting production environment:
echo - Backend: 8000
echo - Frontend: 5275 (dist static serve)
echo - Database: product_knowledge
echo - Redis: redis://localhost:6379/0
echo - Queue: celery_prod
echo - Worker: worker_prod
echo - Logs: logs\prod
echo - Code: detached immutable master commit
echo.

set "RELEASE_ROOT="
set "RELEASE_COMMIT="
for /f "tokens=1,* delims==" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\prepare_production_release.ps1" -SourceRepo "%~dp0" ^| findstr /B "RELEASE_"') do set "%%a=%%b"
if not defined RELEASE_ROOT (
    echo Failed to prepare production release.
    exit /b 1
)
if not defined RELEASE_COMMIT (
    echo Failed to resolve production release commit.
    exit /b 1
)

echo Backing up production database before migration...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\backup_postgres.ps1" -EnvFile "%~dp0backend\.env" -BackupDir "%~dp0backups\postgres" -RetentionDays 14
if errorlevel 1 exit /b %errorlevel%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\rotate_runtime_secrets.ps1" -EnvFile "%~dp0backend\.env" -Action PrepareModelKey -AllowInsecureLocalProd
if errorlevel 1 exit /b %errorlevel%

set "CAIYAN_ENV_FILE=%~dp0backend\.env"
set "APP_COMMIT=%RELEASE_COMMIT%"
set "APP_BRANCH=master"
pushd "%RELEASE_ROOT%\backend"
"%~dp0backend\runtime\prod-venv\Scripts\python.exe" -m alembic upgrade head
set "MIGRATION_EXIT=%ERRORLEVEL%"
popd
if not "%MIGRATION_EXIT%"=="0" exit /b %MIGRATION_EXIT%

powershell -NoProfile -ExecutionPolicy Bypass -File "%RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action StopAll -RepoRoot "%RELEASE_ROOT%" -RuntimeRoot "%~dp0" -DependencyRoot "%~dp0" -EnvFile "%~dp0backend\.env" -LogPath "%~dp0logs\watchdog.log" -ExpectedCommit "%RELEASE_COMMIT%" -AllowLegacySharedProcess
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action All -RepoRoot "%RELEASE_ROOT%" -RuntimeRoot "%~dp0" -DependencyRoot "%~dp0" -EnvFile "%~dp0backend\.env" -LogPath "%~dp0logs\watchdog.log" -ExpectedCommit "%RELEASE_COMMIT%"
if errorlevel 1 exit /b %errorlevel%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\rotate_runtime_secrets.ps1" -EnvFile "%~dp0backend\.env" -Action MarkModelMigrationComplete
if errorlevel 1 exit /b %errorlevel%
set "SECRET_CHANGED=false"
for /f "tokens=1,* delims==" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\rotate_runtime_secrets.ps1" -EnvFile "%~dp0backend\.env" -Action RotateSecret ^| findstr /B "CHANGED="') do set "SECRET_CHANGED=%%b"
if /i not "%SECRET_CHANGED%"=="true" exit /b 0

echo Restarting production services once to activate the isolated signing secret...
powershell -NoProfile -ExecutionPolicy Bypass -File "%RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action StopAll -RepoRoot "%RELEASE_ROOT%" -RuntimeRoot "%~dp0" -DependencyRoot "%~dp0" -EnvFile "%~dp0backend\.env" -LogPath "%~dp0logs\watchdog.log" -ExpectedCommit "%RELEASE_COMMIT%"
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%RELEASE_ROOT%\deploy\scripts\service_control_windows.ps1" -Action All -RepoRoot "%RELEASE_ROOT%" -RuntimeRoot "%~dp0" -DependencyRoot "%~dp0" -EnvFile "%~dp0backend\.env" -LogPath "%~dp0logs\watchdog.log" -ExpectedCommit "%RELEASE_COMMIT%"
exit /b %errorlevel%
