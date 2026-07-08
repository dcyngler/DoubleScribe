@echo off
REM Launches the new Transcriber UI. No console window.
cd /d "%~dp0"
".venv\Scripts\pythonw.exe" app\app.py
