@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :install

where py >nul 2>&1
if %errorlevel%==0 (
  echo Creating venv with py launcher...
  py -3 -m venv .venv
  goto :install
)

where python >nul 2>&1
if %errorlevel%==0 (
  echo Creating venv with python...
  python -m venv .venv
  goto :install
)

echo Python 3 not found.
pause
exit /b 1

:install
if not exist ".venv\Scripts\python.exe" (
  echo Failed to create .venv
  pause
  exit /b 1
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo pip install failed
  pause
  exit /b 1
)

echo Starting news-radar on 127.0.0.1:8770 ...
echo Local:  http://127.0.0.1:8770/
".venv\Scripts\python.exe" -m news_radar
pause
