@echo off
REM Double-click entry point for a normal work session: starts the Flask dev
REM server in its own window, opens the app in your browser, then drops you
REM into Claude Code in this window.

cd /d "%~dp0.."

start "FF Assistant Server" cmd /k python -m scripts.run_app
timeout /t 2 /nobreak >nul
start http://localhost:5050

claude
