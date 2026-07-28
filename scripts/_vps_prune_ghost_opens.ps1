Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $py scripts\_vps_prune_ghost_opens.py
