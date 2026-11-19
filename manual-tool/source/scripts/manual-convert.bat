@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0manual-convert.ps1" %*
exit /b %ERRORLEVEL%