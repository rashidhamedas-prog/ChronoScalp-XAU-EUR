# Activate the entry kill switch on the VPS (halts NEW entries only; the bot
# keeps running and keeps managing any open position).
#
# NOTE: scripts/_vps_full_deploy.ps1 deletes this marker. Re-run this script
# after a deploy if entries must stay halted.
$ErrorActionPreference = "Stop"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
$marker = Join-Path $root "data\state\STOP_TRADING"

New-Item -ItemType Directory -Force -Path (Split-Path $marker -Parent) | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Set-Content -Path $marker -Value "activated: halt new entries pending stop-geometry fix ($stamp)" -Encoding utf8

Write-Output ("MARKER_EXISTS=" + (Test-Path $marker))
Write-Output ("MARKER_CONTENT=" + (Get-Content $marker -Raw).Trim())

# Report open positions so the operator knows what is still live.
Write-Output "=== OPEN POSITIONS ==="
$py = Join-Path $root ".venv\Scripts\python.exe"
$snippet = @'
import MetaTrader5 as mt5
if mt5.initialize():
    positions = mt5.positions_get()
    print("open_positions", 0 if positions is None else len(positions))
    for p in positions or []:
        print(
            f"POS ticket={p.ticket} {p.symbol} type={p.type} vol={p.volume} "
            f"open={p.price_open} sl={p.sl} tp={p.tp} profit={p.profit}"
        )
    mt5.shutdown()
else:
    print("MT5_INIT_FAILED", mt5.last_error())
'@
$tmp = Join-Path $env:TEMP "_cs_positions.py"
Set-Content -Path $tmp -Value $snippet -Encoding UTF8
& $py $tmp
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

Write-Output "HALT_DONE"
