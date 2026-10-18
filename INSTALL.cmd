@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-tested-py312.txt
if errorlevel 1 exit /b 1
call START_WEB.cmd --check
if errorlevel 1 exit /b 1
echo Installation checked. Run START_WEB.cmd and open http://127.0.0.1:8017/visualization
