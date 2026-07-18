@echo off
REM Debug launcher for the new UI: shows a console with any Python errors.
cd /d "%~dp0"
echo Starting Double Scribe in debug mode...
echo (Leave this window open while using the app.)
echo.
".venv\Scripts\python.exe" app\app.py
echo.
echo --- The app has closed. Any error is shown above. ---
pause
