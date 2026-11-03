@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT=%PROJECT_ROOT%\src\ticket_tools\ticket_creation\redmine_to_markdown.py"
set "MODULE=ticket_tools.ticket_creation.redmine_to_markdown"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"

set "BASE_URL=https://redmine.example.local"
set "PROJECT=your_project_identifier"
set "STATUS_ID=*"
set "OUTPUT=%PROJECT_ROOT%\output\redmine-ticket-creation\tickets.md"

if /I "%~1"=="/h" goto :usage
if /I "%~1"=="/help" goto :usage
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--help" goto :usage

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
set "BASE_URL=%~1"
set "PROJECT=%~2"
if not "%~3"=="" set "STATUS_ID=%~3"
if not "%~4"=="" set "OUTPUT=%~4"

if not exist "%PROJECT_ROOT%\output" mkdir "%PROJECT_ROOT%\output"

if not exist "%PYTHON_EXE%" (
  for /f "usebackq delims=" %%P in (`where python 2^>nul`) do (
    set "PYTHON_EXE=%%P"
    goto :python_ready
  )
)

:python_ready
if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python executable not found.
  echo         Create .venv under the project root, or activate a Python environment.
  exit /b 1
)

if not exist "%SCRIPT%" (
  echo Script not found: "%SCRIPT%"
  exit /b 1
)

echo Exporting tickets...
"%PYTHON_EXE%" -m "%MODULE%" ^
  --base-url "%BASE_URL%" ^
  --project "%PROJECT%" ^
  --status-id "%STATUS_ID%" ^
  --config "%PROJECT_ROOT%\config\config.json" ^
  --output "%OUTPUT%"

if errorlevel 1 (
  echo.
  echo Export failed.
  exit /b 1
)

echo.
echo Done. Output: "%OUTPUT%"
exit /b 0

:usage
echo Usage:
echo   export_tickets.bat ^<base_url^> ^<project^> [status_id] [output]
echo.
echo Example:
echo   export_tickets.bat "https://redmine.example.local" "my_project" "*" ".\output\tickets.md"
exit /b 0
