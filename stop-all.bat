@echo off
setlocal enabledelayedexpansion

title CaiYan Local Services Stopper
cd /d "%~dp0"
echo Stopping validated production backend, frontend, and worker processes...
call "%~dp0stop-prod.bat"
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
