@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   ChronoScalp - Graceful Stop
echo ========================================
echo.

REM Prefer graceful shutdown: write STOP marker + SHUTDOWN signal for the bot
REM to persist state and exit. Force-kill only after a 30s timeout.

set "STATE_DIR=data\state"
set "USER_DIR=data\user"
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
if not exist "%USER_DIR%" mkdir "%USER_DIR%"

echo shutdown> "%STATE_DIR%\SHUTDOWN"
echo yes> "%STATE_DIR%\STOP_TRADING"
echo [..] Graceful stop signaled (SHUTDOWN + STOP_TRADING)

set /a WAITED=0
:wait_loop
if not exist "%USER_DIR%\bot.pid" goto after_wait
if %WAITED% GEQ 30 goto force_kill
timeout /t 1 /nobreak >nul
set /a WAITED+=1
goto wait_loop

:force_kill
echo [!] Graceful stop timed out after 30s — forcing process tree stop
if exist "%USER_DIR%\bot.pid" (
  for /f %%p in (%USER_DIR%\bot.pid) do taskkill /PID %%p /T /F >nul 2>&1
  del /f /q "%USER_DIR%\bot.pid" >nul 2>&1
)

:after_wait
REM Soft-stop titled console windows without recycling MT5 terminal.
taskkill /FI "WINDOWTITLE eq ChronoScalp Panel*" /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChronoScalp Bot*" /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq ChronoScalp Dashboard*" /T >nul 2>&1

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /PID %%p >nul 2>&1
)

if exist "%STATE_DIR%\SHUTDOWN" del /f /q "%STATE_DIR%\SHUTDOWN" >nul 2>&1

echo [OK] ChronoScalp stop sequence finished.
echo.
pause
