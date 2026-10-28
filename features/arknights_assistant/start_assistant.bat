@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_assistant.ps1"
if errorlevel 1 pause
endlocal
