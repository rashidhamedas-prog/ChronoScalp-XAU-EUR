# Strip UTF-8 BOM from trading_state_live.json if present (PowerShell Set-Content artifact).
$path = 'C:\ChronoScalp\ChronoScalp-XAU-EUR\data\state\trading_state_live.json'
if (-not (Test-Path $path)) {
  Write-Output 'NO_STATE_FILE'
  exit 0
}
$bytes = [System.IO.File]::ReadAllBytes($path)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  $utf8 = New-Object System.Text.UTF8Encoding $false
  $text = $utf8.GetString($bytes, 3, $bytes.Length - 3)
  [System.IO.File]::WriteAllText($path, $text, $utf8)
  Write-Output 'BOM_STRIPPED'
} else {
  Write-Output 'NO_BOM'
}
