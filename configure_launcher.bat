@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
set "ENVIRONMENT_FILE=%PROJECT_DIR%launcher_environment.bat"
set "SETUP_SCRIPT=%PROJECT_DIR%setup_wizard.py"
set "RUNTIME_CHECK=%PROJECT_DIR%verify_runtime.py"

if not exist "%ENVIRONMENT_FILE%" goto environment_file_missing
call "%ENVIRONMENT_FILE%"
if errorlevel 1 goto environment_file_failed

set "PYTHON_EXE=%TIMEDLAUNCHER_PYTHON_EXE%"

if not exist "%SETUP_SCRIPT%" goto script_missing
if not exist "%RUNTIME_CHECK%" goto runtime_check_missing
if not exist "%PYTHON_EXE%" goto runtime_missing

"%PYTHON_EXE%" -B "%RUNTIME_CHECK%" --quiet
if errorlevel 1 goto runtime_invalid

if /i "%~1"=="--check" (
    echo SETUP_STARTER_CHECK_OK
    exit /b 0
)

cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" -B "%SETUP_SCRIPT%"

if errorlevel 1 goto setup_cancelled
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

:runtime_check_missing
echo Runtime verifier not found:
echo %RUNTIME_CHECK%
pause
exit /b 1

:runtime_missing
echo.
echo Bundled Python runtime was not found.
echo Download and extract the complete Windows Release package.
pause
exit /b 1

:runtime_invalid
echo.
echo Bundled Python runtime is incomplete or damaged.
echo Download and extract the complete Windows Release package again.
pause
exit /b 1

:script_missing
echo Setup wizard not found:
echo %SETUP_SCRIPT%
pause
exit /b 1

:setup_cancelled
echo.
echo Setup was cancelled or not saved.
pause
exit /b 1
