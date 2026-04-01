@echo off
cd /d "%~dp0"
start "" http://localhost:7860
python -m app.main serve
pause
