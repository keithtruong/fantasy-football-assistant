# One-time setup: registers the real-time Rotoworld watcher as a Windows
# scheduled task that fires every 5 minutes (the script itself decides whether
# each firing actually polls -- see scripts/watch_news.py). Re-running is safe.
#
# Registered via PowerShell rather than schtasks /TR on purpose: schtasks turns
# single quotes into double quotes inside /TR, which broke on the apostrophe in
# this repo's folder name. Here the task runs `pythonw -m scripts.watch_news`
# with the repo as its working directory, so no path needs quoting at all.

$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent

# Resolve the real interpreter behind `python` (not the WindowsApps Store
# alias, which doesn't launch reliably from Task Scheduler), then its pythonw.
$python = (& python -c "import sys; print(sys.executable)").Trim()
$pythonw = Join-Path (Split-Path $python -Parent) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

$action   = New-ScheduledTaskAction -Execute $pythonw -Argument '-m scripts.watch_news' -WorkingDirectory $repo
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable

Register-ScheduledTask -TaskName 'FF Assistant - News Watch' -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Registered 'FF Assistant - News Watch'"
Write-Host "  Runs:   $pythonw -m scripts.watch_news"
Write-Host "  In:     $repo"
