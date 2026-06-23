@echo off
setlocal enabledelayedexpansion

title CaiYan Local Services Stopper
cd /d "%~dp0"
call :load_env_prod
set "LOG_DIR_WIN=%LOG_DIR:/=\%"

echo Stopping production Celery worker by pidfile/name/queue...
if exist "%LOG_DIR_WIN%\celery.pid" (
    for /f "usebackq tokens=*" %%p in ("%LOG_DIR_WIN%\celery.pid") do (
        taskkill /F /T /PID %%p >nul 2>nul
    )
    del "%LOG_DIR_WIN%\celery.pid" >nul 2>nul
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$self = $PID;" ^
  "Get-CimInstance Win32_Process | Where-Object { $cmd = $_.CommandLine; $_.ProcessId -ne $self -and $cmd -and (($cmd -like '*uvicorn app.main:app*--port 8000*') -or ($cmd -like '*%CELERY_WORKER_NAME%@*') -or ($cmd -like '*-Q %CELERY_QUEUE%*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Stopping fallback listeners on ports 8000 and 5275...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING" /C:":5275 .*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>nul
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
