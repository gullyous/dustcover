@echo off
REM Same as run.bat but keeps a console window open so you can see errors.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo Creating virtual environment...
  %PY% -m venv "%~dp0.venv"
)

"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"

echo.
echo === Quick backend check (prints current track) =========================
"%VENV_PY%" "%~dp0media_backend.py"
echo ========================================================================
echo.
echo Launching widget (console stays open; close it to quit the widget)...
"%VENV_PY%" "%~dp0main.py"
pause
