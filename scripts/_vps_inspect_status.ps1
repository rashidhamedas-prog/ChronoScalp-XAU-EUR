# Remote inspect — uploaded for one-shot SSH; safe to leave.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root
Write-Output ("HEAD=" + (git rev-parse --short HEAD))
Write-Output ("BRANCH=" + (git branch --show-current))
Write-Output ("LOG=" + (git log -1 --oneline))
Write-Output "---OVERRIDES_HEAD---"
if (Test-Path "config\runtime_overrides.yaml") {
    Get-Content "config\runtime_overrides.yaml" -TotalCount 50
} else {
    Write-Output "NO_OVERRIDES"
}
Write-Output "---PROCS---"
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "run_live\.py|telegram_control_bot\.py|streamlit|run_api\.py") } |
  ForEach-Object {
      $cl = $_.CommandLine
      if ($cl.Length -gt 140) { $cl = $cl.Substring(0, 140) }
      Write-Output ("PID=" + $_.ProcessId + " " + $cl)
  }
Write-Output "INSPECT_DONE"
