$ErrorActionPreference = 'Stop'

function Get-BackendPaths {
  $scriptDir = Split-Path -Parent $MyInvocation.PSCommandPath
  $root = Split-Path -Parent $scriptDir
  $backendDir = Join-Path $root 'apps\backend'
  if (-not (Test-Path -LiteralPath $backendDir)) {
    throw "backend directory not found: $backendDir"
  }

  return [PSCustomObject]@{
    PidFile = Join-Path $backendDir '.flask.pid'
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

function Get-PidFileProcessId([string]$PidFile) {
  if (-not (Test-Path -LiteralPath $PidFile)) {
    return $null
  }

  $pidText = (Get-Content -Raw -Encoding UTF8 $PidFile).Trim()
  if ([string]::IsNullOrWhiteSpace($pidText)) {
    return $null
  }

  $resolvedPid = 0
  if (-not [int]::TryParse($pidText, [ref]$resolvedPid)) {
    return $null
  }
  if ($resolvedPid -le 0) {
    return $null
  }

  return $resolvedPid
}

function Test-HttpOk([string]$Url) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3
    return [PSCustomObject]@{
      Ok         = ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
      StatusCode = $response.StatusCode
    }
  }
  catch {
    return [PSCustomObject]@{
      Ok         = $false
      StatusCode = $null
    }
  }
}

$paths = Get-BackendPaths
$backendPid = Get-PortProcessId -Port 8000
$pidFilePid = Get-PidFileProcessId -PidFile $paths.PidFile
$health = Test-HttpOk -Url 'http://127.0.0.1:8000/health'
$pluginStatus = Test-HttpOk -Url 'http://127.0.0.1:8000/plugin/service-status'

if ($null -eq $backendPid) {
  Write-Host 'Status: stopped'
  if ($null -ne $pidFilePid) {
    Write-Host "PID file: $pidFilePid (stale or not listening on port 8000)"
  }
  exit 0
}

Write-Host 'Status: running'
Write-Host "PID: $backendPid"
if ($null -ne $pidFilePid -and $pidFilePid -ne $backendPid) {
  Write-Host "PID file: $pidFilePid (mismatch)"
}
Write-Host "Health: $($health.Ok) (status code: $($health.StatusCode))"
Write-Host "Plugin Status: $($pluginStatus.Ok) (status code: $($pluginStatus.StatusCode))"
Write-Host 'URL: http://127.0.0.1:8000/plugin/service-status'
