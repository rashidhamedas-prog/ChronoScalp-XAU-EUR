@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ChronoScalp — start Control Panel (SaaS UI) + optional bot
REM Usage: double-click or: scripts\start.bat

cd /d "%~dp0.."
set "ROOT=%CD%"

if not exist "logs" mkdir "logs"
if not exist "data\state" mkdir "data\state"
if not exist "data\user" mkdir "data\user"
if not exist "data\licenses" mkdir "data\licenses"

if exist ".venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

set "PYTHONPATH=%ROOT%\src"

echo.
echo ========================================
echo   ChronoScalp Control Panel
echo ========================================
echo   Open: http://localhost:8501
echo   Flow: License -^> Broker -^> Start bot
echo.

start "ChronoScalp Panel" cmd /k "cd /d %ROOT% && set PYTHONPATH=%ROOT%\src && %PY% -m streamlit run scripts\app.py --server.port 8501"

echo [OK] Panel started. Use the UI to connect broker and start the bot.
echo To stop panel/bot: run scripts\stop.bat
echo.
pause
