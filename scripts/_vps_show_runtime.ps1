# Show VPS deploy path + active symbols/overrides.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Write-Host "ROOT_EXISTS=$(Test-Path $root)"
if (-not (Test-Path $root)) { Write-Host "MISSING_ROOT"; exit 1 }
Set-Location $root
Write-Host "HEAD=$((git rev-parse --short HEAD))"
Write-Host "BRANCH=$((git branch --show-current))"
Write-Host "---OVERRIDES---"
if (Test-Path "config\runtime_overrides.yaml") {
  Get-Content "config\runtime_overrides.yaml" -TotalCount 50
} else {
  Write-Host "NO_OVERRIDES"
}
Write-Host "---SETTINGS_SYMBOLS---"
Select-String -Path "config\settings.yaml" -Pattern "^\s*-\s*\"|allowed_symbols|enabled_strategies" |
  ForEach-Object { $_.Line.Trim() }
Write-Host "STATUS_DONE"
