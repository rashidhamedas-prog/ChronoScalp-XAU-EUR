# ChronoScalp Telegram control bot watchdog — run as SYSTEM via Scheduled Task.
$ErrorActionPreference = "Continue"
Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR

$py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONPATH = (Resolve-Path ".\src").Path

function Get-TelegramBotProcesses {
  @(Get-CimInstance Win32_Process |
    Where-Object {
      $_.Name -match 'python' -and
      $_.CommandLine -and
      ($_.CommandLine -match 'telegram_control_bot\.py')
    })
}

$procs = Get-TelegramBotProcesses
if ($procs.Count -gt 1) {
  $keep = $procs[0].ProcessId
  foreach ($p in $procs | Select-Object -Skip 1) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Write-Output "TG_DEDUPE_KEPT=$keep"
  exit 0
}
if ($procs.Count -eq 1) {
  Write-Output "TG_ALREADY_UP"
  exit 0
}

New-Item -ItemType Directory -Path "logs" -Force | Out-Null

# No stdout redirect (can fail under SYSTEM if log handle stuck). Logging goes to chronoscalp_*.log.
Start-Process -FilePath $py `
  -ArgumentList @("scripts\telegram_control_bot.py") `
  -WorkingDirectory (Get-Location) `
  -WindowStyle Hidden

Start-Sleep -Seconds 5
$after = Get-TelegramBotProcesses
if ($after.Count -ge 1) {
  Write-Output "TG_STARTED_OK"
} else {
  Write-Output "TG_START_FAIL"
}
