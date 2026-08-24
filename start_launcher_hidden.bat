@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
set "ENVIRONMENT_FILE=%PROJECT_DIR%launcher_environment.bat"
set "INSTALLER=%PROJECT_DIR%install_dependencies.bat"
set "LAUNCHER_SCRIPT=%PROJECT_DIR%scheduler_launcher.py"

if not exist "%ENVIRONMENT_FILE%" goto environment_file_missing
call "%ENVIRONMENT_FILE%"
if errorlevel 1 goto environment_file_failed

set "PYTHONW_EXE=%TIMEDLAUNCHER_PYTHONW_EXE%"

if not exist "%LAUNCHER_SCRIPT%" goto script_missing
if not exist "%INSTALLER%" goto installer_missing

if /i "%~1"=="--check" (
    echo HIDDEN_STARTER_CHECK_OK
    exit /b 0
)

call "%INSTALLER%" --check >nul 2>nul
if errorlevel 1 (
    echo TimedLauncher environment is missing or incomplete.
    echo Starting first-run environment setup in this window...
    call "%INSTALLER%" --from-launcher
    if errorlevel 1 goto environment_failed
)

cd /d "%PROJECT_DIR%"
"%PYTHONW_EXE%" "%LAUNCHER_SCRIPT%" %*

if errorlevel 1 goto launch_failed
exit /b 0

:environment_file_missing
echo Environment path file not found:
echo %ENVIRONMENT_FILE%
pause
exit /b 1

:environment_file_failed
echo Unable to load environment paths:
echo %ENVIRONMENT_FILE%
pause
exit /b 1

:installer_missing
echo Dependency installer not found:
echo %INSTALLER%
pause
exit /b 1

:environment_failed
echo.
echo TimedLauncher environment setup failed.
pause
exit /b 1

:script_missing
echo Launcher script not found:
echo %LAUNCHER_SCRIPT%
pause
exit /b 1

:launch_failed
echo.
echo TimedLauncher failed. Check logs\launcher.log.
pause
exit /b 1
