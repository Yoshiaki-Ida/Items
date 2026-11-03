@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT=%PROJECT_ROOT%\src\ticket_tools\ticket_creation\redmine_meeting_importer.py"
set "MODULE=ticket_tools.ticket_creation.redmine_meeting_importer"
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
set "DEFAULT_INPUT=%PROJECT_ROOT%\samples\meeting-open-items.json"
set "DEFAULT_CONFIG=%PROJECT_ROOT%\config\config.json"
set "DEFAULT_PROJECT=your_project_identifier"
set "DEFAULT_PARENT_TRACKER=6"
set "DEFAULT_CHILD_TRACKER=20"
set "DEBUG=0"

if /I "%~2"=="--debug" set "DEBUG=1"
if /I "%~3"=="--debug" set "DEBUG=1"
if /I "%~4"=="--debug" set "DEBUG=1"
if /I "%~5"=="--debug" set "DEBUG=1"
if /I "%~6"=="--debug" set "DEBUG=1"
if /I "%~7"=="--debug" set "DEBUG=1"
if /I "%~8"=="--debug" set "DEBUG=1"
if /I "%~9"=="--debug" set "DEBUG=1"

if "%RUN_IMPORTER_DEBUG%"=="1" set "DEBUG=1"

set "MODE=%~1"
if "%MODE%"=="" goto :usage
if /I "%MODE%"=="dry-run" goto :args_ok
if /I "%MODE%"=="apply" goto :args_ok
goto :usage

:args_ok
set "INPUT_JSON=%~2"
if /I "%INPUT_JSON%"=="--debug" set "INPUT_JSON="
if "%INPUT_JSON%"=="" set "INPUT_JSON=%DEFAULT_INPUT%"

set "CONFIG_JSON=%~3"
if /I "%CONFIG_JSON%"=="--debug" set "CONFIG_JSON="
if "%CONFIG_JSON%"=="" set "CONFIG_JSON=%DEFAULT_CONFIG%"

set "PROJECT_ID=%~4"
if /I "%PROJECT_ID%"=="--debug" set "PROJECT_ID="
if "%PROJECT_ID%"=="" set "PROJECT_ID=%DEFAULT_PROJECT%"

set "PARENT_TRACKER_ID=%~5"
if /I "%PARENT_TRACKER_ID%"=="--debug" set "PARENT_TRACKER_ID="
if "%PARENT_TRACKER_ID%"=="" set "PARENT_TRACKER_ID=%DEFAULT_PARENT_TRACKER%"

set "CHILD_TRACKER_ID=%~6"
if /I "%CHILD_TRACKER_ID%"=="--debug" set "CHILD_TRACKER_ID="
if "%CHILD_TRACKER_ID%"=="" set "CHILD_TRACKER_ID=%DEFAULT_CHILD_TRACKER%"

set "OUTPUT_JSON=%~7"
if /I "%OUTPUT_JSON%"=="--debug" set "OUTPUT_JSON="
if "%OUTPUT_JSON%"=="" (
  if /I "%MODE%"=="apply" (
    set "OUTPUT_JSON=%PROJECT_ROOT%\output\redmine-ticket-creation\%PROJECT_ID%\redmine-import-result.apply.json"
  ) else (
    set "OUTPUT_JSON=%PROJECT_ROOT%\output\redmine-ticket-creation\%PROJECT_ID%\redmine-import-result.json"
  )
)

set "BASE_URL_OVERRIDE=%~8"
if /I "%BASE_URL_OVERRIDE%"=="--debug" set "BASE_URL_OVERRIDE="
set "OPTIONS_ARG="
if not "%~9"=="" if /I not "%~9"=="--debug" set OPTIONS_ARG=--registration-options "%~9"

if "%DEBUG%"=="1" call :print_effective_args

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
  set "EC=1"
  goto :on_error
)

if not exist "%SCRIPT%" (
  echo [ERROR] Importer script not found: "%SCRIPT%"
  set "EC=1"
  goto :on_error
)

if not exist "%INPUT_JSON%" if exist "%PROJECT_ROOT%\%INPUT_JSON%" set "INPUT_JSON=%PROJECT_ROOT%\%INPUT_JSON%"
if not exist "%CONFIG_JSON%" if exist "%PROJECT_ROOT%\%CONFIG_JSON%" set "CONFIG_JSON=%PROJECT_ROOT%\%CONFIG_JSON%"

if not exist "%INPUT_JSON%" (
  echo [ERROR] Input JSON not found: "%INPUT_JSON%"
  echo [HINT] Do not use "...\" shorthand. Use a real path like ".\..\meeting-open-items-8.json".
  set "EC=1"
  goto :on_error
)

if not exist "%CONFIG_JSON%" (
  echo [ERROR] Config JSON not found: "%CONFIG_JSON%"
  echo [HINT] Copy "%PROJECT_ROOT%\config\config.example.json" to "%PROJECT_ROOT%\config\config.json" and edit it.
  set "EC=1"
  goto :on_error
)

if /I "%MODE%"=="apply" (
  echo Running apply mode...
  if "%BASE_URL_OVERRIDE%"=="" (
    "%PYTHON_EXE%" -m "%MODULE%" "%INPUT_JSON%" --config "%CONFIG_JSON%" --project-id "%PROJECT_ID%" --parent-tracker-id "%PARENT_TRACKER_ID%" --child-tracker-id "%CHILD_TRACKER_ID%" --output "%OUTPUT_JSON%" --apply --confirm-create-parent %OPTIONS_ARG%
  ) else (
    "%PYTHON_EXE%" -m "%MODULE%" "%INPUT_JSON%" --config "%CONFIG_JSON%" --base-url "%BASE_URL_OVERRIDE%" --project-id "%PROJECT_ID%" --parent-tracker-id "%PARENT_TRACKER_ID%" --child-tracker-id "%CHILD_TRACKER_ID%" --output "%OUTPUT_JSON%" --apply --confirm-create-parent %OPTIONS_ARG%
  )
  if errorlevel 1 (
    set "EC=!errorlevel!"
    goto :on_error
  )
  echo [OK] Apply completed. Output: "%OUTPUT_JSON%"
  exit /b 0
)

echo Running dry-run mode...
if "%BASE_URL_OVERRIDE%"=="" (
  "%PYTHON_EXE%" -m "%MODULE%" "%INPUT_JSON%" --config "%CONFIG_JSON%" --project-id "%PROJECT_ID%" --parent-tracker-id "%PARENT_TRACKER_ID%" --child-tracker-id "%CHILD_TRACKER_ID%" --output "%OUTPUT_JSON%" %OPTIONS_ARG%
) else (
  "%PYTHON_EXE%" -m "%MODULE%" "%INPUT_JSON%" --config "%CONFIG_JSON%" --base-url "%BASE_URL_OVERRIDE%" --project-id "%PROJECT_ID%" --parent-tracker-id "%PARENT_TRACKER_ID%" --child-tracker-id "%CHILD_TRACKER_ID%" --output "%OUTPUT_JSON%" %OPTIONS_ARG%
)
if errorlevel 1 (
  set "EC=!errorlevel!"
  goto :on_error
)
echo [OK] Dry-run completed. Output: "%OUTPUT_JSON%"
exit /b 0

:print_effective_args
echo [DEBUG] MODE=%MODE%
echo [DEBUG] INPUT_JSON=%INPUT_JSON%
echo [DEBUG] CONFIG_JSON=%CONFIG_JSON%
echo [DEBUG] PROJECT_ID=%PROJECT_ID%
echo [DEBUG] PARENT_TRACKER_ID=%PARENT_TRACKER_ID%
echo [DEBUG] CHILD_TRACKER_ID=%CHILD_TRACKER_ID%
echo [DEBUG] OUTPUT_JSON=%OUTPUT_JSON%
echo [DEBUG] BASE_URL_OVERRIDE=%BASE_URL_OVERRIDE%
goto :eof

:on_error
if "%EC%"=="" set "EC=1"
echo [FAILED] Exit code: %EC%
if "%RUN_IMPORTER_PAUSE_ON_ERROR%"=="1" pause
exit /b %EC%

:usage
echo Usage:
echo   run_meeting_importer.bat dry-run [input_json] [config_json] [project_id] [parent_tracker_id] [child_tracker_id] [output_json] [base_url]
echo   run_meeting_importer.bat apply   [input_json] [config_json] [project_id] [parent_tracker_id] [child_tracker_id] [output_json] [base_url]
echo   run_meeting_importer.bat apply   [input_json] [config_json] [project_id] [parent_tracker_id] [child_tracker_id] [output_json] [base_url] --debug
echo.
echo Example:
echo   run_meeting_importer.bat dry-run

echo   run_meeting_importer.bat apply "%PROJECT_ROOT%\samples\meeting-open-items.json" "%PROJECT_ROOT%\config\config.json" your_project_identifier 6 1 "%PROJECT_ROOT%\output\result.json" "https://redmine.example.com/redmine"
echo.
echo Optional env vars:
echo   Optional ninth argument: registration-options JSON for destination names.
echo   RUN_IMPORTER_DEBUG=1          ^(always print effective args^)
echo   RUN_IMPORTER_PAUSE_ON_ERROR=1 ^(pause on error, useful when double-clicking .bat^)
exit /b 2
