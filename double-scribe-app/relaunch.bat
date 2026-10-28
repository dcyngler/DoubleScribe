@echo off
rem Used only by the silent in-app auto-updater's [Run] entry in DoubleScribe.iss.
rem A short pause before relaunching lets AV real-time scanning release its lock on the
rem freshly-written DLLs, avoiding the "DLL load failed ... used by another process" crash.
timeout /t 2 /nobreak >nul
start "" "%~dp0DoubleScribe.exe"
