@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
set "ENVIRONMENT_FILE=%PROJECT_DIR%launcher_environment.bat"

if not exist "%ENVIRONMENT_FILE%" goto environment_file_missing
call "%ENVIRONMENT_FILE%"
if errorlevel 1 goto environment_file_failed

set "VENV_DIR=%TIMEDLAUNCHER_VENV_DIR%"
set "PYTHON_EXE=%TIMEDLAUNCHER_PYTHON_EXE%"
set "REQUIREMENTS=%TIMEDLAUNCHER_REQUIREMENTS%"

if /i "%~1"=="--check" goto check_environment
if not exist "%REQUIREMENTS%" goto requirements_missing

if not exist "%PYTHON_EXE%" (
    call :create_environment
    if errorlevel 1 goto environment_create_failed
)

echo.
echo Installing TimedLauncher dependencies into:
echo %VENV_DIR%
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r "%REQUIREMENTS%"
if errorlevel 1 goto install_failed

call :verify_environment
if errorlevel 1 goto verify_failed

echo.
echo Environment is ready.
"%PYTHON_EXE%" -B -c "import sys; from importlib.metadata import version; print('Python:', sys.version.split()[0]); print('psutil:', version('psutil')); print('PyAutoGUI:', version('PyAutoGUI')); print('PyGetWindow:', version('PyGetWindow')); print('Location:', sys.executable)"
if /i not "%~1"=="--from-launcher" pause
exit /b 0

:check_environment
if not exist "%PYTHON_EXE%" exit /b 1
if not exist "%REQUIREMENTS%" exit /b 1
call :verify_environment
exit /b %errorlevel%

:create_environment
call :find_python_311
if errorlevel 1 exit /b 1

echo.
echo Creating an isolated Python 3.11 environment:
echo %VENV_DIR%
if /i "%BASE_PYTHON_KIND%"=="launcher" (
    py.exe -3.11 -m venv "%VENV_DIR%"
) else (
    "%BASE_PYTHON_EXE%" -m venv "%VENV_DIR%"
)
if errorlevel 1 exit /b 1
if not exist "%PYTHON_EXE%" exit /b 1

"%PYTHON_EXE%" -m ensurepip --upgrade
if errorlevel 1 exit /b 1
exit /b 0

:find_python_311
set "BASE_PYTHON_KIND="
set "BASE_PYTHON_EXE="

if defined TIMEDLAUNCHER_BOOTSTRAP_PYTHON (
    if exist "%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%" (
        "%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%" -B -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "BASE_PYTHON_KIND=executable"
            set "BASE_PYTHON_EXE=%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%"
            exit /b 0
        )
    )
)

where py.exe >nul 2>nul
if not errorlevel 1 (
    py.exe -3.11 -B -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "BASE_PYTHON_KIND=launcher"
        exit /b 0
    )
)

for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    "%%P" -B -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "BASE_PYTHON_KIND=executable"
        set "BASE_PYTHON_EXE=%%P"
        exit /b 0
    )
)

echo.
echo Python 3.11 64-bit was not found.
echo Install it from https://www.python.org/downloads/release/python-3119/
echo During setup, enable "Add python.exe to PATH", then run this file again.
exit /b 1

:verify_environment
"%PYTHON_EXE%" -B -c "import sys, psutil, pyautogui, pygetwindow; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
exit /b %errorlevel%

:environment_file_missing
echo Environment path file not found:
echo %ENVIRONMENT_FILE%
goto failed

:environment_file_failed
echo Unable to load environment paths:
echo %ENVIRONMENT_FILE%
goto failed

:requirements_missing
echo Requirements file not found:
echo %REQUIREMENTS%
goto failed

:environment_create_failed
echo.
echo Unable to create the project environment.
echo Check that Python 3.11 64-bit is installed and this folder is writable.
goto failed

:install_failed
echo.
echo Dependency installation failed. Check the network and pip output above.
goto failed

:verify_failed
echo.
echo Dependencies were installed, but the environment verification failed.
echo Run this installer again or recreate the .venv folder.
goto failed

:failed
if /i not "%~1"=="--from-launcher" pause
exit /b 1
