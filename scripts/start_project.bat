@echo off
setlocal
cd /d "%~dp0"
set "NO_PAUSE="
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

powershell -ExecutionPolicy Bypass -File ".\start_project.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%NO_PAUSE%"=="1" (
  if not "%EXIT_CODE%"=="0" (
    echo.
    echo ????????????????
  ) else (
    echo.
    echo ??????????
  )
  pause
)

exit /b %EXIT_CODE%
