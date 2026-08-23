@echo off
setlocal

title CaiYan Production Services Launcher
cd /d "%~dp0"

echo Starting production environment:
echo - Backend: 8000
echo - Frontend: 5275 (dist static serve)
echo - Database: product_knowledge
echo - Redis: redis://localhost:6379/0
echo - Queue: celery_prod
echo - Worker: worker_prod
echo - Logs: logs\prod
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\scripts\service_control_windows.ps1" -Action All -RepoRoot "%~dp0" -LogPath "%~dp0logs\watchdog.log"
exit /b %errorlevel%
