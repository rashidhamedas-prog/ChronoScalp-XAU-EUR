Set-Location C:\ChronoScalp\ChronoScalp-XAU-EUR
Write-Output '--- recent after reset ---'
Get-Content .\logs\bot_stdout.log -Tail 40 | Select-String -Pattern 'daily_loss|Ultra-scalp|started|Trade opened|skip heartbeat'
Write-Output '--- pid ---'
Get-Content .\data\user\bot.pid -ErrorAction SilentlyContinue
