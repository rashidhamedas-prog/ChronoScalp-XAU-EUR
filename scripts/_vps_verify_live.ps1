$ErrorActionPreference = "Continue"
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
if (Test-Path data\user\bot.pid) {
  Write-Output ("PIDFILE=" + (Get-Content data\user\bot.pid -Raw).Trim())
} else {
  Write-Output "NO_PIDFILE"
}
if (Test-Path data\state\STOP_TRADING) { Write-Output "KILL=ON" } else { Write-Output "KILL=OFF" }
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run_live\.py" } | ForEach-Object {
  Write-Output ("BOT_PROC=" + $_.ProcessId)
}
$log = Get-ChildItem logs\chronoscalp_*.log -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
  Write-Output ("LOG=" + $log.Name)
  Select-String -Path $log.FullName -Pattern "ChronoScalp started|mode live|Failed to connect|Trade opened|Kill switch" |
    Select-Object -Last 10 |
    ForEach-Object { $_.Line }
}
Write-Output "VERIFY_DONE"
