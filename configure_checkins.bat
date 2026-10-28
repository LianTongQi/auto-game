@echo off
setlocal
cd /d "%~dp0"
call "%~dp0launcher_environment.bat"
if errorlevel 1 exit /b 1
"%TIMEDLAUNCHER_PYTHON_EXE%" -B "%~dp0checkin_setup.py" %*
if errorlevel 1 pause
endlocal
