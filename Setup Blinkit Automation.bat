@echo off
setlocal EnableExtensions
title Blinkit Report Automation - First Time Setup
cd /d "%~dp0"

echo.
echo ==========================================
echo   BLINKIT AUTOMATION - FIRST TIME SETUP
echo ==========================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
  where python >nul 2>&1 && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo Python is not installed.
  echo Install Python 3.12+ and run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo Failed to create environment.
    pause
    exit /b 1
  )
)

echo Installing required packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package installation failed.
  pause
  exit /b 1
)

echo Installing Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo Browser installation failed.
  pause
  exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

if not exist "Blinkit_Reports" mkdir "Blinkit_Reports"

echo.
echo ==========================================
echo Setup completed.
echo.
echo For normal use, double-click:
echo Start Blinkit Automation.bat
echo ==========================================
echo.
pause
