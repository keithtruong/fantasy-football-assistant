@echo off
REM Double-click this file to check whether data\ffassistant.db is healthy
REM and to clear a stuck rollback journal left over from a failed write
REM through the Claude Cowork device link. Read-only — safe to run any time.

cd /d "%~dp0.."
python -m scripts.check_db_health

echo.
echo Press any key to close this window...
pause >nul
