$ErrorActionPreference = 'Stop'

function Get-BackendPaths {
  $scriptDir = Split-Path -Parent $MyInvocation.PSCommandPath
  $root = Split-Path -Parent $scriptDir
  $backendDir = Join-Path $root 'apps\backend'
  if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "backend directory not found: $backendDir"
  }

  return [PSCustomObject]@{
    BackendDir = $backendDir
    PythonExe  = Join-Path $backendDir '.venv\Scripts\python.exe'
    ScheduleDb = Join-Path $backendDir 'celerybeat-schedule'
  }
}

$paths = Get-BackendPaths
if (-not (Test-Path -LiteralPath $paths.PythonExe)) {
  throw "Python virtual environment not found: $($paths.PythonExe). Run scripts/start_project.ps1 first."
}

Write-Host "Starting Celery beat for competitor room price schedule"
Push-Location -LiteralPath $paths.BackendDir
try {
  & $paths.PythonExe -m celery -A app.celery_app:celery_app beat --loglevel=info --schedule $paths.ScheduleDb
}
finally {
  Pop-Location
}
