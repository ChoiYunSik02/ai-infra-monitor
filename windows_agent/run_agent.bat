@echo off
chcp 65001 > nul

:: Request admin privileges
net session > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

title Windows Hardware Monitor Agent

echo ================================================
echo  Windows Hardware Monitor Agent
echo  Target: http://192.168.0.37:8000
echo  Admin: OK
echo ================================================
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python not found. Install Python 3.9+ first.
        pause
        exit /b 1
    )
)

echo [SETUP] Installing packages...
.venv\Scripts\pip install -q -r requirements.txt

if not exist "lib" mkdir lib

echo [START] Running agent...
echo.
.venv\Scripts\python windows_agent.py

pause
