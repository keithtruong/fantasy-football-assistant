@echo off
REM One-time setup for the real-time Rotoworld watcher -- see
REM register_news_watch_task.ps1 for what it registers and why it's PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_news_watch_task.ps1"
pause
