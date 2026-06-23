@echo off
setlocal enabledelayedexpansion

title CaiYan Dev Services Stopper
cd /d "%~dp0"
call :load_env_dev
set "LOG_DIR_WIN=%LOG_DIR:/=\%"

echo Stopping development Celery worker by pidfile/name/queue...
if exist "%LOG_DIR_WIN%\celery.pid" (
    for /f "usebackq tokens=*" %%p in ("%LOG_DIR_WIN%\celery.pid") do (
        taskkill /F /T /PID %%p >nul 2>nul
    )
    del "%LOG_DIR_WIN%\celery.pid" >nul 2>nul
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$self = $PID;" ^
  "Get-CimInstance Win32_Process | Where-Object { $cmd = $_.CommandLine; $_.ProcessId -ne $self -and $cmd -and (($cmd -like '*%CELERY_WORKER_NAME%@*') -or ($cmd -like '*-Q %CELERY_QUEUE%*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo Stopping fallback development listeners on ports 8001 and 5276...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING" /C:":5276 .*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>nul
)

echo.
echo Done. Redis and production services were left running.
pause

exit /b 0

:load_env_dev
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0backend\.env.dev") do (
    if not "%%a"=="" set "%%a=%%b"
)
exit /b 0
