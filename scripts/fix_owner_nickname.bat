@echo off
REM Double-click this file to fix team 120's display name in
REM data\ffassistant.db (from ESPN's raw "JFN" to the real nickname
REM "Johnny"), and to clear a stuck rollback journal if one is present
REM from an earlier failed write through the Claude Cowork device link.
REM Safe to run any time.

cd /d "%~dp0.."
python -m scripts.fix_owner_nickname

echo.
echo Press any key to close this window...
pause >nul
