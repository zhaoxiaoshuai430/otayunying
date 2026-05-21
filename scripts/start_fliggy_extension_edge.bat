@echo off
setlocal
cd /d "%~dp0"
set "NO_PAUSE="
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

powershell -ExecutionPolicy Bypass -File ".\start_fliggy_extension_edge.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%NO_PAUSE%"=="1" (
  echo.
  if not "%EXIT_CODE%"=="0" (
    echo Failed to open Edge with the Fliggy extension.
  ) else (
    echo Edge launched with the Fliggy extension.
  )
  pause
)

exit /b %EXIT_CODE%