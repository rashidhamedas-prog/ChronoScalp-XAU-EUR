# عیب‌یابی VPS ویندوز (ChronoScalp)

راهنمای عملیاتی وقتی پنل/ربات بعد از ری‌استارت یا قطع MT5 از کار می‌افتد.
رمزها و توکن‌ها فقط در `.env` روی سرور هستند — هرگز در گیت commit نشوند.

ورود: RDP به هاست VPS → PowerShell را **Run as administrator** باز کنید.
مسیر پیش‌فرض پروژه روی VPS: `C:\ChronoScalp\ChronoScalp-XAU-EUR`

---

## ۱) MT5 بسته شده یا از حساب خارج شده

**علامت:** پنل/ربات خطای اتصال MT5 می‌دهد؛ تست بروکر fail می‌شود.

```powershell
$mt5 = Get-ChildItem "C:\Program Files*","C:\Program Files (x86)" -Filter terminal64.exe -Recurse -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
Write-Host "MT5 path: $mt5"
Start-Process $mt5
```

در پنجره MT5 دوباره لاگین کنید و ترمینال را **باز نگه دارید**.

---

## ۲) ویندوز ری‌استارت شده — پنل (۸۵۰۱) بالا نیست

**علامت:** `http://<VPS-IP>:8501` باز نمی‌شود.

```powershell
cd C:\ChronoScalp\ChronoScalp-XAU-EUR
$env:PYTHONPATH="C:\ChronoScalp\ChronoScalp-XAU-EUR\src"

Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "streamlit" } | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Process "C:\ChronoScalp\ChronoScalp-XAU-EUR\.venv\Scripts\python.exe" `
  -ArgumentList "-m streamlit run scripts\app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false" `
  -WorkingDirectory "C:\ChronoScalp\ChronoScalp-XAU-EUR" `
  -WindowStyle Hidden

Start-Sleep 3
Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
```

اگر باز نشد، فایروال:

```powershell
New-NetFirewallRule -DisplayName "ChronoScalp Panel 8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow -ErrorAction SilentlyContinue
```

---

## ۳) ربات Paper/Live بعد از ری‌استارت بالا نیست

از پنل: **کنترل ربات → استارت**، یا:

```powershell
cd C:\ChronoScalp\ChronoScalp-XAU-EUR
$env:PYTHONPATH="C:\ChronoScalp\ChronoScalp-XAU-EUR\src"
# اول MT5 را باز و لاگین کنید، بعد:
.\.venv\Scripts\python.exe scripts\run_live.py --mode paper
```

---

## ۴) Kill Switch گیر کرده

```powershell
Remove-Item "C:\ChronoScalp\ChronoScalp-XAU-EUR\data\state\STOP_TRADING" -ErrorAction SilentlyContinue
# در .env نباید CHRONOSCALP_STOP_TRADING=yes باشد
notepad C:\ChronoScalp\ChronoScalp-XAU-EUR\.env
```

---

## ۵) دیسک پر / وضعیت سریع

```powershell
Get-PSDrive C
Get-Service sshd -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 8501,8510,22,3389 -State Listen -ErrorAction SilentlyContinue | Format-Table LocalPort, State
Test-Path C:\ChronoScalp\ChronoScalp-XAU-EUR\.venv
Test-Path C:\ChronoScalp\ChronoScalp-XAU-EUR\.env
```

وضعیت API بدون هاردکد کردن توکن:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\_vps_api_status.ps1
```

---

## ۶) آپدیت کد از GitHub

```powershell
cd C:\ChronoScalp\ChronoScalp-XAU-EUR
git fetch origin
git checkout main
git reset --hard origin/main
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# سپس پنل/ربات را طبق بخش‌های بالا دوباره استارت کنید
```

---

## چک‌لیست روزانه

1. MT5 باز و لاگین
2. پنل روی پورت ۸۵۰۱ پاسخ می‌دهد
3. Kill Switch = off
4. ربات Paper (یا Live با `CHRONOSCALP_CONFIRM_LIVE=yes`) استارت است

مرتبط: [DEPLOY_NL_VPS.md](DEPLOY_NL_VPS.md)، [SSH_VPS.md](SSH_VPS.md)، [RAHNAMA_FA.md](RAHNAMA_FA.md).
