@echo off
setlocal enabledelayedexpansion

if /i "%~1"=="backend" goto :backend
if /i "%~1"=="worker" goto :worker
if /i "%~1"=="frontend" goto :frontend

title CaiYan Dev Services Launcher
cd /d "%~dp0"
call :load_env_dev
set "LOG_DIR_WIN=%LOG_DIR:/=\%"
if not exist "%LOG_DIR_WIN%" mkdir "%LOG_DIR_WIN%"

echo Checking Docker Desktop...
docker info >nul 2>nul
if errorlevel 1 (
    echo.
    echo Docker is not running.
    echo Please start Docker Desktop manually, wait until it is ready, then run start-dev.bat again.
    echo.
    pause
    exit /b 1
)

echo Checking Redis container caiyan-redis...
set "REDIS_EXISTS="
for /f "usebackq tokens=*" %%i in (`docker ps -a --filter "name=^/caiyan-redis$" --format "{{.Names}}"`) do set "REDIS_EXISTS=%%i"
if "%REDIS_EXISTS%"=="" (
    docker run --name caiyan-redis -p 6379:6379 -d redis:7
) else (
    set "REDIS_RUNNING="
    for /f "usebackq tokens=*" %%i in (`docker ps --filter "name=^/caiyan-redis$" --format "{{.Names}}"`) do set "REDIS_RUNNING=%%i"
    if "%REDIS_RUNNING%"=="" docker start caiyan-redis
)

echo Starting development backend, worker, and frontend...
set "BACKEND_RUNNING="
for /f "tokens=*" %%i in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING"') do set "BACKEND_RUNNING=1"
if defined BACKEND_RUNNING (
    echo Dev backend port 8001 is already listening. Skipping backend start.
) else (
    start "CaiYan Dev Backend - 8001" cmd /k ""%~f0" backend"
    timeout /t 2 /nobreak >nul
)

set "WORKER_RUNNING="
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "$self = $PID; Get-CimInstance Win32_Process | Where-Object { $cmd = $_.CommandLine; $_.ProcessId -ne $self -and $_.Name -like 'python*' -and $cmd -and ($cmd -like '*%CELERY_WORKER_NAME%@*' -or $cmd -like '*-Q %CELERY_QUEUE%*') } | Select-Object -First 1 -ExpandProperty ProcessId"`) do set "WORKER_RUNNING=1"
if defined WORKER_RUNNING (
    echo Dev Celery worker is already running. Skipping worker start.
) else (
    start "CaiYan Dev Celery Worker" cmd /k ""%~f0" worker"
)

set "FRONTEND_RUNNING="
for /f "tokens=*" %%i in ('netstat -ano ^| findstr /R /C:":5276 .*LISTENING"') do set "FRONTEND_RUNNING=1"
if defined FRONTEND_RUNNING (
    echo Dev frontend port 5276 is already listening. Skipping frontend start.
) else (
    start "CaiYan Dev Frontend - 5276" cmd /k ""%~f0" frontend"
)

echo.
echo Development URL: http://127.0.0.1:5276
echo Development API: http://127.0.0.1:8001
echo Database: product_knowledge_dev
echo.
pause
exit /b 0

:load_env_dev
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0backend\.env.dev") do (
    if not "%%a"=="" set "%%a=%%b"
)
exit /b 0

:backend
title CaiYan Dev Backend - 8001
cd /d "%~dp0backend"
call :load_env_dev
set "LOG_DIR_WIN=%LOG_DIR:/=\%"
if "%COMPUTERNAME%"=="" set "COMPUTERNAME=localhost"
if not exist "..\%LOG_DIR_WIN%" mkdir "..\%LOG_DIR_WIN%"
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
)
call "venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --workers 1 --timeout-keep-alive 120
exit /b %errorlevel%

:worker
title CaiYan Dev Celery Worker
cd /d "%~dp0backend"
call :load_env_dev
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
title CaiYan Dev Frontend - 5276
cd /d "%~dp0frontend"
if not exist "node_modules" (
    npm install
)
npm run dev:dev
exit /b %errorlevel%
