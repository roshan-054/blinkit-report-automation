@echo off
setlocal EnableExtensions
title Blinkit Report Automation
cd /d "%~dp0"

echo.
echo ==========================================
echo       BLINKIT REPORT AUTOMATION
echo ==========================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1 && set "PYTHON_CMD=py"
if not defined PYTHON_CMD where python >nul 2>&1 && set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
  echo Python 3.12+ was not found.
  echo Install Python, then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating application environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :python_error
)

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"

echo Checking required packages...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :dependency_error

if not exist "%LOCALAPPDATA%\ms-playwright" (
  echo Installing browser engine...
  "%VENV_PYTHON%" -m playwright install chromium
  if errorlevel 1 goto :browser_error
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME_EXE (
  echo Google Chrome was not found.
  pause
  exit /b 1
)

set "BLINKIT_PROFILE=%LOCALAPPDATA%\BlinkitAutomationChrome"

echo Starting Blinkit Chrome...
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%BLINKIT_PROFILE%" "https://seller.blinkit.com/"

echo Starting automation server...
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 (
  start "Blinkit Automation Server" /min cmd /c ""%VENV_PYTHON%" run.py"
)

echo Waiting for the local application...
set /a ATTEMPTS=0

:wait_loop
set /a ATTEMPTS+=1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/health; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 goto :open_app

if %ATTEMPTS% GEQ 30 goto :server_error
timeout /t 1 /nobreak >nul
goto :wait_loop

:open_app
echo.
echo ==========================================
echo  Blinkit Automation is ready.
echo ==========================================
echo.
start "" "http://127.0.0.1:8000/"
exit /b 0

:server_error
echo.
echo The automation server did not start.
echo.
echo Check the server window for the error message.
echo.
echo You can also open http://127.0.0.1:8000 manually after fixing it.
pause
exit /b 1

:python_error
echo Could not create the Python environment.
pause
exit /b 1

:dependency_error
echo Could not install required packages.
pause
exit /b 1

:browser_error
echo Could not install the Playwright browser.
pause
exit /b 1
