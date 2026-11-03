@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT=%PROJECT_ROOT%\src\ticket_tools\ticket_creation\create_children_from_markdown.py"
set "MODULE=ticket_tools.ticket_creation.create_children_from_markdown"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
set "BASE_URL=https://redmine.example.local"
set "PROJECT=your_project_identifier"

if /I "%~1"=="/h" goto :usage
if /I "%~1"=="/help" goto :usage
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--help" goto :usage

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage

set "PARENT_ID=%~1"
set "ARG3=%~3"

set "TRACKER="
set "INPUT_MD="
set "BASE_URL_ARG="
set "PROJECT_ARG="

if "%~3"=="" goto :mode_no_tracker
if /I "%ARG3:~0,4%"=="http" goto :mode_no_tracker_with_override
goto :mode_with_tracker

:mode_no_tracker
set "INPUT_MD=%~2"
goto :mode_done

:mode_no_tracker_with_override
set "INPUT_MD=%~2"
set "BASE_URL_ARG=%~3"
set "PROJECT_ARG=%~4"
goto :mode_done

:mode_with_tracker
set "TRACKER=%~2"
set "INPUT_MD=%~3"
set "BASE_URL_ARG=%~4"
set "PROJECT_ARG=%~5"

:mode_done

if not "%BASE_URL_ARG%"=="" set "BASE_URL=%BASE_URL_ARG%"
if not "%PROJECT_ARG%"=="" set "PROJECT=%PROJECT_ARG%"

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

if "%REDMINE_API_KEY%"=="" (
  echo [ERROR] Set the REDMINE_API_KEY user environment variable and restart VS Code.
  exit /b 2
)

if not exist "%SCRIPT%" (
  echo Script not found: "%SCRIPT%"
  exit /b 1
)

if not exist "%INPUT_MD%" if exist "%PROJECT_ROOT%\%INPUT_MD%" set "INPUT_MD=%PROJECT_ROOT%\%INPUT_MD%"

if not exist "%INPUT_MD%" (
  echo Input file not found: "%INPUT_MD%"
  exit /b 1
)

if not "%TRACKER%"=="" (
  "%PYTHON_EXE%" -m "%MODULE%" ^
    --base-url "%BASE_URL%" ^
    --project "%PROJECT%" ^
    --config "%PROJECT_ROOT%\config\config.json" ^
    --parent-id "%PARENT_ID%" ^
    --tracker "%TRACKER%" ^
    --input "%INPUT_MD%"
  if errorlevel 1 exit /b 1
  exit /b 0
)

"%PYTHON_EXE%" -m "%MODULE%" ^
  --base-url "%BASE_URL%" ^
  --project "%PROJECT%" ^
  --config "%PROJECT_ROOT%\config\config.json" ^
  --parent-id "%PARENT_ID%" ^
  --input "%INPUT_MD%"

exit /b %errorlevel%

:usage
echo Usage:
echo   create_children_from_markdown.bat ^<parent_id^> ^<input_md_or_yaml^>
echo   create_children_from_markdown.bat ^<parent_id^> ^<default_tracker^> ^<input_md_or_yaml^>
echo   create_children_from_markdown.bat ^<parent_id^> ^<input_md_or_yaml^> [base_url] [project]
echo   create_children_from_markdown.bat ^<parent_id^> ^<default_tracker^> ^<input_md_or_yaml^> [base_url] [project]
echo Example:
echo   create_children_from_markdown.bat 1 ".\samples\child_items.yaml"
echo   create_children_from_markdown.bat 1 "Task" ".\samples\child_items.yaml"
echo   create_children_from_markdown.bat 1 ".\samples\child_items.yaml" "https://redmine.example.com/redmine" "my_project"
exit /b 2
