@echo off
setlocal
cd /d "%~dp0frontend"
if not exist "node_modules" (
    npm install
)
start "AI Tool Frontend" cmd /k "npm run dev"
pause
