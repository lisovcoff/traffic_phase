@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0.web_runtime\tmp"
set "TMP=%TEMP%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%TEMP%" exit /b 1
set "WEB_PYTHON=python"
if exist "C:\Python314\python.exe" set "WEB_PYTHON=C:\Python314\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "WEB_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0.web_runtime\release_20261018\venv312\Scripts\python.exe" set "WEB_PYTHON=%~dp0.web_runtime\release_20261018\venv312\Scripts\python.exe"
if defined TRAFFIC_PHASE_PYTHON set "WEB_PYTHON=%TRAFFIC_PHASE_PYTHON%"
if "%~1"=="--check" (
  "%WEB_PYTHON%" -c "import tempfile; from app.main import app; print('Application import OK; temporary storage:', tempfile.gettempdir())"
  exit /b
)
echo Open http://127.0.0.1:8017/visualization
"%WEB_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8017
