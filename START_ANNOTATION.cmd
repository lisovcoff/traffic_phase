@echo off
cd /d "%~dp0"
py -3 -m scripts.run_annotation
if errorlevel 1 pause
