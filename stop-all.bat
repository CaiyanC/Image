@echo off
setlocal enabledelayedexpansion

title CaiYan Local Services Stopper
cd /d "%~dp0"
call :load_env_prod
set "LOG_DIR_WIN=%LOG_DIR:/=\%"

echo Stopping validated production backend, frontend, and worker processes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\service_control_windows.ps1" -Action StopAll -RepoRoot "%~dp0" -LogPath "%~dp0logs\watchdog.log"
if errorlevel 1 (
    echo Failed to stop one or more production services. Check logs\watchdog.log.
    exit /b 1
)

echo.
set /p "STOP_REDIS=Stop Redis container caiyan-redis too? [y/N]: "
if /i "%STOP_REDIS%"=="y" (
    docker stop caiyan-redis
) else (
    echo Redis container left running.
)

echo.
echo Done.
pause

exit /b 0

:load_env_prod
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0backend\.env") do (
    if not "%%a"=="" set "%%a=%%b"
)
exit /b 0
