@echo off
REM Launches Double Scribe. No console window.
cd /d "%~dp0"
".venv\Scripts\pythonw.exe" app\app.py
