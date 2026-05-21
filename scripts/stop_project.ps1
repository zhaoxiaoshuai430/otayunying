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
    PidFile    = Join-Path $backendDir '.flask.pid'
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

function Stop-BackendProcess([int]$ProcessId) {
  try {
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    Write-Host "Stopped PID: $ProcessId"
    return $true
  }
  catch {
    return $false
  }
}

$paths = Get-BackendPaths
$stoppedIds = @()
$candidateIds = @()

$pidFilePid = Get-PidFileProcessId -PidFile $paths.PidFile
if ($null -ne $pidFilePid) {
  $candidateIds += $pidFilePid
}

if ($candidateIds.Count -eq 0 -or $candidateIds -notcontains (Get-PortProcessId -Port 8000)) {
  $portPid = Get-PortProcessId -Port 8000
  if ($null -ne $portPid -and $candidateIds -notcontains $portPid) {
    $candidateIds += $portPid
  }
}

foreach ($processId in $candidateIds) {
  if (Stop-BackendProcess -ProcessId $processId) {
    $stoppedIds += $processId
  }
}

Start-Sleep -Milliseconds 500
$remainingPortPid = Get-PortProcessId -Port 8000
if ($null -ne $remainingPortPid -and $candidateIds -notcontains $remainingPortPid) {
  if (Stop-BackendProcess -ProcessId $remainingPortPid) {
    $stoppedIds += $remainingPortPid
  }
}

Remove-Item -LiteralPath $paths.PidFile -Force -ErrorAction SilentlyContinue

if ($null -eq (Get-PortProcessId -Port 8000) -and $stoppedIds.Count -gt 0) {
  Write-Host ("Backend stopped. PID(s): {0}" -f (($stoppedIds | Select-Object -Unique) -join ', '))
}
else {
  Write-Host 'Backend is not running on port 8000.'
}



