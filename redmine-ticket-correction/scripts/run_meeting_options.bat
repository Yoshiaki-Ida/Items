@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto :run
where python >nul 2>nul
if errorlevel 1 exit /b 1
set "PYTHON_EXE=python"
:run
"%PYTHON_EXE%" -m ticket_tools.ticket_creation.meeting_registration %*
exit /b %errorlevel%
