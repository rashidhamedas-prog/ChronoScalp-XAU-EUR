Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
Write-Output '--- user_config ---'
if (Test-Path .\data\user\user_config.json) {
  Get-Content .\data\user\user_config.json -Raw
}
Write-Output '--- trading_state ---'
if (Test-Path .\data\state\trading_state_live.json) {
  Get-Content .\data\state\trading_state_live.json -Raw
}
