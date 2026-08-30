# Read-only: how are ChronoScalp processes supposed to survive a reboot / SSH exit?
# Looks for scheduled tasks, services, and startup-folder shortcuts.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"

Write-Output "===== SCHEDULED TASKS ====="
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -match 'chrono|scalp|bot|panel|telegram' -or $_.Actions.Execute -match 'ChronoScalp' }
if ($tasks) {
    foreach ($t in $tasks) {
        $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
        Write-Output ("TASK name=" + $t.TaskName + " path=" + $t.TaskPath + " state=" + $t.State)
        foreach ($a in $t.Actions) {
            Write-Output ("   exec=" + $a.Execute + " args=" + $a.Arguments)
        }
        if ($info) {
            Write-Output ("   last=" + $info.LastRunTime + " result=" + $info.LastTaskResult + " next=" + $info.NextRunTime)
        }
    }
} else {
    Write-Output "NO_MATCHING_TASKS"
}

Write-Output "===== SERVICES ====="
$svcs = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'chrono|scalp|nssm' }
if ($svcs) {
    foreach ($s in $svcs) { Write-Output ("SVC " + $s.Name + " status=" + $s.Status + " start=" + $s.StartType) }
} else {
    Write-Output "NO_MATCHING_SERVICES"
}

Write-Output "===== STARTUP FOLDER ====="
$startup = [Environment]::GetFolderPath("Startup")
Write-Output ("STARTUP_DIR=" + $startup)
Get-ChildItem $startup -ErrorAction SilentlyContinue | ForEach-Object { Write-Output ("  " + $_.Name) }
$allUsers = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"
Get-ChildItem $allUsers -ErrorAction SilentlyContinue | ForEach-Object { Write-Output ("  ALLUSERS " + $_.Name) }

Write-Output "===== WATCHDOG SCRIPT ====="
Write-Output ("HAS_watch_bot=" + (Test-Path (Join-Path $root "scripts\watch_bot.ps1")))
Write-Output "PROBE_AUTOSTART_DONE"
