@echo off
REM Runs Double Scribe as a local web server for testing in a browser
REM (http://127.0.0.1:8765) instead of the native window.
cd /d "%~dp0"
".venv\Scripts\python.exe" app\server.py
