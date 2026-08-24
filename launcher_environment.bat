@echo off
rem Shared environment paths for every TimedLauncher entry point.
rem This file must be called from another batch file.

set "TIMEDLAUNCHER_PROJECT_DIR=%~dp0"
set "TIMEDLAUNCHER_VENV_DIR=%~dp0.venv"
set "TIMEDLAUNCHER_PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "TIMEDLAUNCHER_PYTHONW_EXE=%~dp0.venv\Scripts\pythonw.exe"
set "TIMEDLAUNCHER_REQUIREMENTS=%~dp0requirements.txt"

exit /b 0
