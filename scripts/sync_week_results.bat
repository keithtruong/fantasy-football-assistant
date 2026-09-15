@echo off
REM Scheduled-task entry point (see the Task Scheduler entry registered
REM alongside this script): syncs the most recently completed week's box
REM scores + free-agent scores for TAMS (league_id 3) so the weekly recap's
REM Matchup Stories/Waiver Wire Watch sections have real data. Safe to run
REM unattended and repeatedly — see sync_week_results.py's own docstring for
REM why no --week argument is needed here.

cd /d "%~dp0.."
python -m scripts.sync_week_results --league-id 3
