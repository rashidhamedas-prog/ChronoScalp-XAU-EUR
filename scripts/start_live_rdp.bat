@echo off
chcp 65001 >nul
REM Start ChronoScalp live from an interactive RDP session.
REM Closes hung terminal64 first so Python can spawn a fresh MT5 pipe.

cd /d "%~dp0.."
set "ROOT=%CD%"
set "PYTHONPATH=%ROOT%\src"
set "CHRONOSCALP_CONFIRM_LIVE=yes"
set "PYTHONUNBUFFERED=1"

if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo.
echo [1/3] Closing hung MetaTrader terminals...
taskkill /F /IM terminal64.exe >nul 2>&1
timeout /t 5 /nobreak >nul

echo [2/3] Starting live bot (MT5 may take up to ~3 minutes to connect)...
echo      Keep this window open. Minimize is OK; closing stops the bot.
echo.
"%PY%" "%ROOT%\scripts\run_live.py" --mode live
echo.
echo Bot exited. Press any key to close.
pause >nul
