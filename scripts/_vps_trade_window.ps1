# Read-only: dump every log line mentioning the tickets/symbols of the most
# recent live trades, plus the surrounding context, so the close cause is visible.
$ErrorActionPreference = "Continue"
$root = "C:\ChronoScalp\ChronoScalp-XAU-EUR"
Set-Location $root

$logs = Get-ChildItem "logs\chronoscalp_2026-08-2*.log" | Sort-Object Name
$lines = @()
foreach ($l in $logs) { $lines += Get-Content $l.FullName }
Write-Output ("LINES=" + $lines.Count)

Write-Output "=== ALL place_order / close / modify / reconcile / heat LINES ==="
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'place_order|Order placed|modify_sl_tp|close_position|Closed position|record_close|record_external|external close|three_strikes|breakeven|trailing|partial|reconcile|Position gone|disappeared|mistake_memory|lesson') {
        Write-Output ("HIT[" + $i + "] " + $lines[$i])
    }
}

Write-Output "=== CONTEXT AROUND EACH place_order (-3 / +40) ==="
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'Order placed') {
        Write-Output ("---- context for line " + $i + " ----")
        $from = [Math]::Max(0, $i - 3)
        $to = [Math]::Min($lines.Count - 1, $i + 40)
        for ($j = $from; $j -le $to; $j++) {
            if ($lines[$j] -notmatch 'entry rejected|Empty BTCUSD|symbol unavailable') {
                Write-Output ("  " + $lines[$j])
            }
        }
    }
}

Write-Output "=== BROKER SYMBOL SPECS (stops_level / spread) ==="
$py = Join-Path $root ".venv\Scripts\python.exe"
$snippet = @'
import MetaTrader5 as mt5
ok = mt5.initialize()
print("init", ok, mt5.last_error())
if ok:
    for s in ("XAUUSD", "EURUSD"):
        info = mt5.symbol_info(s)
        if info is None:
            print(s, "NO_INFO")
            continue
        tick = mt5.symbol_info_tick(s)
        spread_pts = (tick.ask - tick.bid) / info.point if tick and info.point else float("nan")
        print(
            f"{s} digits={info.digits} point={info.point} trade_stops_level={info.trade_stops_level} "
            f"freeze={info.trade_freeze_level} spread_cur={info.spread} spread_float={info.spread_float} "
            f"tick_value={info.trade_tick_value} contract={info.trade_contract_size} "
            f"vol_min={info.volume_min} vol_max={info.volume_max} vol_step={info.volume_step} "
            f"live_spread_points={spread_pts:.1f} filling={info.filling_mode}"
        )
    mt5.shutdown()
'@
$tmp = Join-Path $env:TEMP "_cs_specs.py"
Set-Content -Path $tmp -Value $snippet -Encoding UTF8
& $py $tmp
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

Write-Output "WINDOW_DONE"
