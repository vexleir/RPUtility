@echo off
cd /d "%~dp0"

echo Checking requirements...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install requirements. Make sure Python is installed and on PATH.
    pause
    exit /b 1
)

start "" http://localhost:7860
python -m app.main serve
pause
