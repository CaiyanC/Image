@echo off
setlocal enabledelayedexpansion

set "BACKUP_DIR=%DB_BACKUP_DIR%"
if "%BACKUP_DIR%"=="" set "BACKUP_DIR=D:\db_backup"
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "TODAY=%%i"
set "BACKUP_FILE=%BACKUP_DIR%\backup_%TODAY%.sql"

if "%PGHOST%"=="" set "PGHOST=localhost"
if "%PGPORT%"=="" set "PGPORT=5432"

if "%PGDATABASE%"=="" (
    echo PGDATABASE is not set. Please set PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD before running backup.
    exit /b 1
)

pg_dump -h "%PGHOST%" -p "%PGPORT%" -U "%PGUSER%" -d "%PGDATABASE%" -F p -f "%BACKUP_FILE%"
if errorlevel 1 (
    echo Database backup failed.
    exit /b 1
)

powershell -NoProfile -Command "Get-ChildItem -Path '%BACKUP_DIR%' -Filter 'backup_*.sql' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force"
echo Backup created: %BACKUP_FILE%
