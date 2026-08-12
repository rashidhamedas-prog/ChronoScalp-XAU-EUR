Set-Location "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe scripts\list_mt5_symbols.py
