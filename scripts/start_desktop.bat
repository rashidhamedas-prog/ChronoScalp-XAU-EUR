@echo off
REM ChronoScalp Desktop Manager — run from your Windows laptop
cd /d "%~dp0.."
set PYTHONPATH=src
python scripts\desktop_client.py
if errorlevel 1 pause
