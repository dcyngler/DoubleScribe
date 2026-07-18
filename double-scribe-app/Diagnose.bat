@echo off
REM Checks which audio devices are captured and whether they have signal.
cd /d "%~dp0"
".venv\Scripts\python.exe" diagnose_audio.py
