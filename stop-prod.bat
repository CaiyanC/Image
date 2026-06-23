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

call "%~dp0stop-all.bat"
exit /b %errorlevel%
