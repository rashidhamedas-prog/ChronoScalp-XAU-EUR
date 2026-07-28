Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
Write-Output '--- settings ultra_scalp ---'
Select-String -Path .\config\settings.yaml -Pattern 'require_confluence|rvol_min|trend_mode|impulse_body'
Write-Output '--- overrides ---'
Get-ChildItem .\data -Recurse -Filter '*override*' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
Get-ChildItem .\data\user -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
Write-Output '--- recent logs ---'
Get-ChildItem .\logs -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | ForEach-Object { $_.Name + ' ' + $_.LastWriteTime }
$latest = Get-ChildItem .\logs -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
  Write-Output ('TAIL ' + $latest.FullName)
  Get-Content $latest.FullName -Tail 25
}
