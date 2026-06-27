@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"

if not exist "%VENV_PY%" (
  echo Creating virtual environment...
  %PY% -m venv "%~dp0.venv"
)

echo Installing dependencies (first run only, may take a minute)...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo Dependency install failed - see messages above.
  pause
  exit /b 1
)

echo Starting Tidal widget...
start "" "%VENV_PYW%" "%~dp0main.py"
exit /b 0
