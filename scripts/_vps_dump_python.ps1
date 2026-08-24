Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match "python" -or ($_.CommandLine -and $_.CommandLine -match "python") } |
  ForEach-Object {
    $cl = if ($_.CommandLine) { $_.CommandLine } else { "" }
    if ($cl.Length -gt 160) { $cl = $cl.Substring(0, 160) }
    Write-Output ("PID=$($_.ProcessId) NAME=$($_.Name) CL=$cl")
  }
Write-Output "PY_DUMP_DONE"
