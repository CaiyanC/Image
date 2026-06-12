@echo off
setlocal
cd /d "%~dp0backend"
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
)
call "venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-keep-alive 120
pause
