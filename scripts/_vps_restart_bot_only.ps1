Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
git fetch origin
git checkout main
git reset --hard origin/main
Write-Output ("HEAD=" + (git rev-parse --short HEAD))

$env:PYTHONPATH = (Resolve-Path '.\src').Path
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $py scripts\_vps_restart_live.py
Write-Output 'DONE'
