@echo off
setlocal
cd /d "%~dp0"
echo start_backend.bat is deprecated.
echo Use start-prod.bat for production or start-dev.bat for development.
echo Redirecting to start-prod.bat...
call "%~dp0start-prod.bat"
exit /b %errorlevel%
