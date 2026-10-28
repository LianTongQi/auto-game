@echo off
setlocal
cd /d "%~dp0"
call "%~dp0launcher_environment.bat"
if not exist "%TIMEDLAUNCHER_PYTHON_EXE%" (
    echo Portable Python is missing. Please use the complete TimedLauncher release.
    pause
    exit /b 1
)
set "SKLAND_ACTION=%~1"
if not defined SKLAND_ACTION set "SKLAND_ACTION=setup"
"%TIMEDLAUNCHER_PYTHON_EXE%" -B "%~dp0skland_checkin.py" "%SKLAND_ACTION%"
set "SKLAND_EXIT=%ERRORLEVEL%"
pause
exit /b %SKLAND_EXIT%
