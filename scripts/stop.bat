@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   ChronoScalp - Stop
echo ========================================
echo.

REM Close bot and dashboard windows by title
taskkill /FI "WINDOWTITLE eq ChronoScalp Bot*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChronoScalp Dashboard*" /T /F >nul 2>&1

REM Free port 8501 if Streamlit still listening
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)

echo [OK] ChronoScalp processes stopped.
echo.
echo Note: kill switch file data\state\STOP_TRADING is NOT removed.
echo       Delete it manually to allow new entries on next start.
echo.
pause
