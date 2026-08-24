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
call :find_compatible_python
if errorlevel 1 exit /b 1

echo.
echo Creating an isolated TimedLauncher environment:
echo %VENV_DIR%
if /i "%BASE_PYTHON_KIND%"=="launcher" (
    echo Using Python launcher selector %BASE_PYTHON_SELECTOR%
    py.exe %BASE_PYTHON_SELECTOR% -m venv "%VENV_DIR%"
) else (
    echo Using %BASE_PYTHON_EXE%
    "%BASE_PYTHON_EXE%" -m venv "%VENV_DIR%"
)
if errorlevel 1 exit /b 1
if not exist "%PYTHON_EXE%" exit /b 1

"%PYTHON_EXE%" -m ensurepip --upgrade
if errorlevel 1 exit /b 1
exit /b 0

:find_compatible_python
set "BASE_PYTHON_KIND="
set "BASE_PYTHON_EXE="
set "BASE_PYTHON_SELECTOR="

if defined TIMEDLAUNCHER_BOOTSTRAP_PYTHON (
    if exist "%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%" (
        "%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%" -B -c "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "BASE_PYTHON_KIND=executable"
            set "BASE_PYTHON_EXE=%TIMEDLAUNCHER_BOOTSTRAP_PYTHON%"
            exit /b 0
        )
    )
)

where py.exe >nul 2>nul
if not errorlevel 1 (
    for %%V in (3.14 3.13 3.12 3.11 3.10) do (
        py.exe -%%V -B -c "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "BASE_PYTHON_KIND=launcher"
            set "BASE_PYTHON_SELECTOR=-%%V"
            exit /b 0
        )
    )

    rem Future Python versions may also work when all pinned dependencies support them.
    py.exe -3 -B -c "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "BASE_PYTHON_KIND=launcher"
        set "BASE_PYTHON_SELECTOR=-3"
        exit /b 0
    )
)

for /f "delims=" %%P in ('where python.exe 2^>nul') do (
    "%%P" -B -c "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "BASE_PYTHON_KIND=executable"
        set "BASE_PYTHON_EXE=%%P"
        exit /b 0
    )
)

echo.
echo No compatible 64-bit Python was found.
echo Current pinned dependencies require Python 3.10 or newer.
echo Install a supported version from https://www.python.org/downloads/windows/
echo During setup, enable "Add python.exe to PATH", then run this file again.
exit /b 1

:verify_environment
"%PYTHON_EXE%" -B -c "import sys, psutil, pyautogui, pygetwindow; from importlib.metadata import version; expected={'MouseInfo':'0.1.3','Pillow':'12.3.0','psutil':'7.2.2','PyAutoGUI':'0.9.54','PyGetWindow':'0.0.9','PyMsgBox':'2.0.1','pyperclip':'1.11.0','PyRect':'0.2.0','PyScreeze':'1.0.1','pytweening':'1.2.0'}; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 and all(version(name) == wanted for name, wanted in expected.items()) else 1)" >nul 2>nul
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
echo Check that a compatible 64-bit Python is installed and this folder is writable.
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
