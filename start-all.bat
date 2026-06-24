@echo off
setlocal enabledelayedexpansion

if /i "%~1"=="backend" goto :backend
if /i "%~1"=="worker" goto :worker
if /i "%~1"=="frontend" goto :frontend

title CaiYan Local Services Launcher
cd /d "%~dp0"
call :load_env_prod
set "LOG_DIR_WIN=%LOG_DIR:/=\%"
if not exist "%LOG_DIR_WIN%" mkdir "%LOG_DIR_WIN%"

echo Checking Docker Desktop...
docker info >nul 2>nul
if errorlevel 1 (
    echo.
    echo Docker is not running.
    echo Please start Docker Desktop manually, wait until it is ready, then run start-all.bat again.
    echo.
    pause
    exit /b 1
)

echo Checking Redis container caiyan-redis...
set "REDIS_EXISTS="
for /f "usebackq tokens=*" %%i in (`docker ps -a --filter "name=^/caiyan-redis$" --format "{{.Names}}"`) do set "REDIS_EXISTS=%%i"

if "%REDIS_EXISTS%"=="" (
    echo Redis container does not exist. Creating caiyan-redis...
    docker run --name caiyan-redis -p 6379:6379 -d redis:7
    if errorlevel 1 (
        echo Failed to create Redis container.
        pause
        exit /b 1
    )
) else (
    set "REDIS_RUNNING="
    for /f "usebackq tokens=*" %%i in (`docker ps --filter "name=^/caiyan-redis$" --format "{{.Names}}"`) do set "REDIS_RUNNING=%%i"
    if "%REDIS_RUNNING%"=="" (
        echo Redis container exists but is stopped. Starting caiyan-redis...
        docker start caiyan-redis
        if errorlevel 1 (
            echo Failed to start Redis container.
            pause
            exit /b 1
        )
    ) else (
        echo Redis container is already running.
    )
)

echo.
echo Starting Backend, Celery worker, and Frontend in separate windows...
set "BACKEND_RUNNING="
for /f "tokens=*" %%i in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do set "BACKEND_RUNNING=1"
if defined BACKEND_RUNNING (
    echo Backend port 8000 is already listening. Skipping backend start.
) else (
    start "CaiYan Backend - 8000" cmd /k ""%~f0" backend"
    timeout /t 2 /nobreak >nul
)

set "WORKER_RUNNING="
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "$self = $PID; Get-CimInstance Win32_Process | Where-Object { $cmd = $_.CommandLine; $_.ProcessId -ne $self -and $_.Name -like 'python*' -and $cmd -and ($cmd -like '*%CELERY_WORKER_NAME%@*' -or $cmd -like '*-Q %CELERY_QUEUE%*') } | Select-Object -First 1 -ExpandProperty ProcessId"`) do set "WORKER_RUNNING=1"
if defined WORKER_RUNNING (
    echo Celery worker is already running. Skipping worker start.
) else (
    start "CaiYan Celery Worker" cmd /k ""%~f0" worker"
    timeout /t 2 /nobreak >nul
)

set "FRONTEND_RUNNING="
for /f "tokens=*" %%i in ('netstat -ano ^| findstr /R /C:":5275 .*LISTENING"') do set "FRONTEND_RUNNING=1"
if defined FRONTEND_RUNNING (
    echo Frontend port 5275 is already listening. Skipping frontend start.
) else (
    start "CaiYan Frontend - 5275" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "$Host.UI.RawUI.WindowTitle='CaiYan Frontend - 5275'; Set-Location -LiteralPath '%~dp0frontend'; if (-not (Test-Path 'node_modules')) { npm install }; npm run build; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; npm run serve:prod"
)

set "LAN_IP="
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /R /C:"IPv4.*192\.168\." /C:"IPv4.*10\."') do (
    if not defined LAN_IP (
        set "LAN_IP=%%i"
        set "LAN_IP=!LAN_IP: =!"
    )
)

echo.
echo ============================================================
if defined LAN_IP (
    echo Local LAN IP: !LAN_IP!
    echo Coworker URL: http://!LAN_IP!:5275
) else (
    echo Could not find a 192.168.* or 10.* IPv4 address.
    echo Run ipconfig manually and use: http://^<your-lan-ip^>:5275
)
echo.
echo Keep the Backend, Celery worker, and Frontend windows open.
echo Closing those windows will stop the corresponding services.
echo Use stop-all.bat to stop local services.
echo ============================================================
echo.
pause
exit /b 0

:load_env_prod
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0backend\.env") do (
    if not "%%a"=="" set "%%a=%%b"
)
exit /b 0

:backend
title CaiYan Backend - 8000
cd /d "%~dp0backend"
call :load_env_prod
set "LOG_DIR_WIN=%LOG_DIR:/=\%"
if "%COMPUTERNAME%"=="" set "COMPUTERNAME=localhost"
if not exist "..\%LOG_DIR_WIN%" mkdir "..\%LOG_DIR_WIN%"
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
)
call "venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --workers 4 --timeout-keep-alive 120
exit /b %errorlevel%

:worker
title CaiYan Celery Worker
cd /d "%~dp0backend"
call :load_env_prod
set "LOG_DIR_WIN=%LOG_DIR:/=\%"
if "%COMPUTERNAME%"=="" set "COMPUTERNAME=localhost"
if not exist "..\%LOG_DIR_WIN%" mkdir "..\%LOG_DIR_WIN%"
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
)
call "venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
python -m celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo -Q %CELERY_QUEUE% -n %CELERY_WORKER_NAME%@%COMPUTERNAME% --pidfile=..\%LOG_DIR_WIN%\celery.pid --logfile=..\%LOG_DIR_WIN%\celery.log
exit /b %errorlevel%

:frontend
title CaiYan Frontend - 5275
cd /d "%~dp0frontend"
if not exist "node_modules" (
    npm install
)
npm run build
if errorlevel 1 exit /b %errorlevel%
npm run serve:prod
exit /b %errorlevel%
