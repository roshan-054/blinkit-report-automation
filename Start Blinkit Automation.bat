@echo off
setlocal EnableExtensions

title Blinkit Report Automation

cd /d "%~dp0"

echo.
echo ==========================================
echo       BLINKIT REPORT AUTOMATION
echo ==========================================
echo.

REM Find Python
set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py"
if not defined PYTHON_CMD (
  where python >nul 2>&1 && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo Python is not installed.
  echo Please install Python 3.12+ and run this launcher again.
  echo.
  pause
  exit /b 1
)

REM Create a local virtual environment on first run.
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: creating application environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :python_error
)

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

REM Install/update required packages.
echo Checking application packages...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :dependency_error

REM Install Playwright Chromium if needed.
if not exist "%LOCALAPPDATA%\ms-playwright" (
  echo First-time setup: installing browser engine...
  "%VENV_PYTHON%" -m playwright install chromium
  if errorlevel 1 goto :browser_error
)

REM Create .env from the supplied template when needed.
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo Created .env from .env.example
)

REM Find Chrome.
set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_EXE (
  echo Google Chrome was not found.
  echo Please install Google Chrome and run this launcher again.
  pause
  exit /b 1
)

REM Use an isolated Chrome profile so the automation does not interfere
REM with the user's normal Chrome profile.
set "BLINKIT_PROFILE=%LOCALAPPDATA%\BlinkitAutomationChrome"

echo Starting Blinkit Chrome session...
start "Blinkit Chrome" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%BLINKIT_PROFILE%" "https://seller.blinkit.com/"

REM Start API only if port 8000 is not already in use.
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 (
  echo Starting automation server...
  start "Blinkit Automation Server" cmd /k ""%VENV_PYTHON%" run.py"
) else (
  echo Automation server is already running.
)

timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000/"

echo.
echo ==========================================
echo  Blinkit Automation is ready.
echo.
echo  1. Login to Blinkit if required.
echo  2. Use the dashboard buttons.
echo ==========================================
echo.
exit /b 0

:python_error
echo.
echo Could not create the Python environment.
pause
exit /b 1

:dependency_error
echo.
echo Could not install required packages.
pause
exit /b 1

:browser_error
echo.
echo Could not install the Playwright browser.
pause
exit /b 1
