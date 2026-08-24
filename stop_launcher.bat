@echo off
chcp 65001 >nul
setlocal

set "PROJECT_DIR=%~dp0"
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "LOCK_FILE=%RUNTIME_DIR%\launcher.lock"
set "STOP_FILE=%RUNTIME_DIR%\stop.request"

if not exist "%LOCK_FILE%" (
    echo TimedLauncher 当前没有运行。
    pause
    exit /b 0
)

> "%STOP_FILE%" echo stop

echo 已发送安全停止请求，正在等待当前程序清理...

for /l %%I in (1,1,30) do (
    if not exist "%LOCK_FILE%" goto stopped
    timeout /t 1 /nobreak >nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"$text = Get-Content -Raw '%LOCK_FILE%' -ErrorAction SilentlyContinue; $launcherPid = 0; if ($text -and [int]::TryParse($text.Trim(), [ref]$launcherPid) -and (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue)) { exit 0 } else { exit 1 }"

if errorlevel 1 (
    del /q "%LOCK_FILE%" 2>nul
    del /q "%STOP_FILE%" 2>nul
    echo.
    echo 已清理失效的运行锁文件。
    pause
    exit /b 0
)

echo.
echo TimedLauncher 未在 30 秒内退出，请查看 logs\launcher.log。
pause
exit /b 1

:stopped
echo.
echo TimedLauncher 已安全停止。
pause
exit /b 0
