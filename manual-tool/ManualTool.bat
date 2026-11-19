@echo off
setlocal
set "APP_DIR=%~dp0"
set "APP_JAVA=%APP_DIR%_internal\runtime\plantuml\java"
if exist "%APP_JAVA%\bin\java.exe" set "JAVA_HOME=%APP_JAVA%"
start "ManualTool" "%APP_DIR%ManualTool.exe" web
start "" http://127.0.0.1:8765/
endlocal
