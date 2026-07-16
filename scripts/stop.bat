@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   ChronoScalp - Stop
echo ========================================
echo.

REM Stop bot via PID file if present
if exist "data\user\bot.pid" (
  for /f %%p in (data\user\bot.pid) do taskkill /PID %%p /T /F >nul 2>&1
  del /f /q "data\user\bot.pid" >nul 2>&1
)

taskkill /FI "WINDOWTITLE eq ChronoScalp Panel*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChronoScalp Bot*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChronoScalp Dashboard*" /T /F >nul 2>&1

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)

echo [OK] ChronoScalp stopped.
echo.
pause
