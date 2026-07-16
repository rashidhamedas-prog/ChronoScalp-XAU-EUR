@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ChronoScalp — start bot (paper) + dashboard
REM Usage: double-click or: scripts\start.bat [paper|live]

cd /d "%~dp0.."
set "ROOT=%CD%"
set "MODE=paper"
if not "%~1"=="" set "MODE=%~1"

if not exist "logs" mkdir "logs"
if not exist "data\state" mkdir "data\state"

if exist ".venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

set "PYTHONPATH=%ROOT%\src"

echo.
echo ========================================
echo   ChronoScalp - Start (%MODE%)
echo ========================================
echo   Root: %ROOT%
echo.

REM --- Bot ---
start "ChronoScalp Bot" cmd /k "cd /d %ROOT% && set PYTHONPATH=%ROOT%\src && %PY% scripts\run_live.py --mode %MODE%"

REM --- Dashboard ---
timeout /t 2 /nobreak >nul
start "ChronoScalp Dashboard" cmd /k "cd /d %ROOT% && set PYTHONPATH=%ROOT%\src && %PY% -m streamlit run scripts\dashboard.py --server.port 8501"

echo [OK] Bot started in window: ChronoScalp Bot
echo [OK] Dashboard: http://localhost:8501
echo.
echo To stop: run scripts\stop.bat
echo Kill switch (halt new trades): create data\state\STOP_TRADING
echo.
pause
