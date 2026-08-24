@echo off
rem Shared portable runtime paths for every TimedLauncher entry point.
rem This file must be called from another batch file.

set "TIMEDLAUNCHER_PROJECT_DIR=%~dp0"
set "TIMEDLAUNCHER_RUNTIME_DIR=%~dp0runtime\python"
set "TIMEDLAUNCHER_PYTHON_EXE=%~dp0runtime\python\python.exe"
set "TIMEDLAUNCHER_PYTHONW_EXE=%~dp0runtime\python\pythonw.exe"
set "TIMEDLAUNCHER_REQUIREMENTS=%~dp0requirements.txt"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

exit /b 0
