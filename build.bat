@echo off
REM Build a standalone Windows .exe (no Python/venv needed to run the result).
REM Output: dist\Dustcover.exe
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo Creating virtual environment...
  %PY% -m venv "%~dp0.venv"
)

echo Installing dependencies (PySide6, winsdk, PyInstaller)...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt" pyinstaller
if errorlevel 1 (
  echo.
  echo Dependency install failed - see messages above.
  pause
  exit /b 1
)

echo Generating app icon...
"%VENV_PY%" "%~dp0make_icon.py"

echo.
echo Building Dustcover.exe (this can take a couple of minutes)...
"%VENV_PY%" -m PyInstaller --noconfirm --clean "%~dp0Dustcover.spec"
if errorlevel 1 (
  echo.
  echo Build failed - see messages above.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  Done.  Your standalone app is:
echo    %~dp0dist\Dustcover.exe
echo  Double-click it to run (TIDAL should be open and playing).
echo ============================================================
pause
