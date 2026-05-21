$ErrorActionPreference = 'Stop'

function Get-BackendPaths {
  $scriptDir = Split-Path -Parent $MyInvocation.PSCommandPath
  $root = Split-Path -Parent $scriptDir
  $backendDir = Join-Path $root 'apps\backend'
  if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "backend directory not found: $backendDir"
  }

  return [PSCustomObject]@{
    Root       = $root
    BackendDir = $backendDir
    VenvDir    = Join-Path $backendDir '.venv'
    PythonExe  = Join-Path $backendDir '.venv\Scripts\python.exe'
    PidFile    = Join-Path $backendDir '.flask.pid'
    StdoutLog  = Join-Path $backendDir 'flask.stdout.log'
    StderrLog  = Join-Path $backendDir 'flask.stderr.log'
  }
}

function Get-PortProcessId([int]$Port) {
  $lines = netstat -ano | Select-String (":{0}" -f $Port)
  if ($null -eq $lines) {
    return $null
  }

  foreach ($line in $lines) {
    $parts = ($line.ToString() -split '\s+') | Where-Object { $_ }
    if ($parts.Count -lt 5) {
      continue
    }
    $state = $parts[-2]
    $resolvedPid = 0
    if ($state -ne 'LISTENING') {
      continue
    }
    if (-not [int]::TryParse($parts[-1], [ref]$resolvedPid)) {
      continue
    }
    if ($resolvedPid -le 0) {
      continue
    }
    return $resolvedPid
  }

  return $null
}

function Test-HttpOk([string]$Url) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3
    return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
  }
  catch {
    return $false
  }
}

function Ensure-Venv([pscustomobject]$Paths) {
  if (Test-Path -LiteralPath $Paths.PythonExe) {
    return
  }

  Write-Host "[1/4] Creating virtual environment with Python 3.11"
  py -3.11 -m venv $Paths.VenvDir
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to create virtual environment with Python 3.11"
  }

  Write-Host "[2/4] Installing dependencies"
  & $Paths.PythonExe -m pip install --upgrade pip | Out-Host
  & $Paths.PythonExe -m pip install -r (Join-Path $Paths.BackendDir 'requirements.txt') | Out-Host
}

function Ensure-Dependencies([pscustomobject]$Paths) {
  $hasFlask = $false
  try {
    & $Paths.PythonExe -c "import flask" | Out-Null
    $hasFlask = ($LASTEXITCODE -eq 0)
  }
  catch {
    $hasFlask = $false
  }

  if ($hasFlask) {
    return
  }

  Write-Host "[2/4] Installing dependencies"
  & $Paths.PythonExe -m pip install --upgrade pip | Out-Host
  & $Paths.PythonExe -m pip install -r (Join-Path $Paths.BackendDir 'requirements.txt') | Out-Host
}

$paths = Get-BackendPaths
$healthUrl = 'http://127.0.0.1:8000/health'
$serviceStatusUrl = 'http://127.0.0.1:8000/plugin/service-status'

$existingPid = Get-PortProcessId -Port 8000
if ($null -ne $existingPid) {
  if (Test-HttpOk -Url $healthUrl) {
    $existingPid.ToString() | Set-Content -LiteralPath $paths.PidFile -Encoding UTF8 -Force
    Write-Host "Backend already running on http://127.0.0.1:8000"
    Write-Host "PID: $existingPid"
    Write-Host "Plugin Status: $serviceStatusUrl"
    exit 0
  }

  throw "Port 8000 is already in use by PID $existingPid, but the health endpoint is not responding."
}

Ensure-Venv -Paths $paths
Ensure-Dependencies -Paths $paths

Write-Host "[3/4] Starting Flask API + schedule runner on http://127.0.0.1:8000"
$proc = Start-Process -FilePath $paths.PythonExe -WorkingDirectory $paths.BackendDir -ArgumentList @(
  'run_flask_server.py'
) -RedirectStandardOutput $paths.StdoutLog -RedirectStandardError $paths.StderrLog -PassThru

$proc.Id.ToString() | Set-Content -LiteralPath $paths.PidFile -Encoding UTF8 -Force

Write-Host "[4/4] Waiting for health endpoint"
for ($i = 0; $i -lt 15; $i++) {
  Start-Sleep -Seconds 1
  if (Test-HttpOk -Url $healthUrl) {
    $activePid = Get-PortProcessId -Port 8000
    if ($null -eq $activePid) {
      throw "Health endpoint is ready, but no LISTENING process was found on port 8000."
    }
    $activePid.ToString() | Set-Content -LiteralPath $paths.PidFile -Encoding UTF8 -Force
    Write-Host "Started successfully"
    Write-Host "PID: $activePid"
    Write-Host "Health: $healthUrl"
    Write-Host "Plugin Status: $serviceStatusUrl"
    exit 0
  }
}

throw "Backend process started (PID $($proc.Id)) but health endpoint did not become ready. Check $($paths.StderrLog)"



