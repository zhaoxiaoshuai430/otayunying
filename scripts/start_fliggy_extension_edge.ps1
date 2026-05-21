$ErrorActionPreference = 'Stop'

function Get-ProjectPaths {
  $scriptDir = Split-Path -Parent $MyInvocation.PSCommandPath
  $root = Split-Path -Parent $scriptDir
  $workspaceParent = Split-Path -Parent $root
  return [PSCustomObject]@{
    Root                = $root
    StartProjectScript  = Join-Path $scriptDir 'start_project.ps1'
    SourceExtensionDir  = Join-Path $root 'apps\frontend\extension'
    RuntimeExtensionDir = Join-Path $workspaceParent 'fliggy-extension'
    ProfileDir          = Join-Path $workspaceParent 'fliggy-extension-profile'
    StartUrl            = 'https://www.fliggy.com/jiudian/?_er_static=true'
  }
}

function Get-EdgeExecutable {
  $candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft/Edge/Application/msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft/Edge/Application/msedge.exe'),
    'msedge.exe'
  ) | Where-Object { $_ }

  foreach ($candidate in $candidates) {
    if ($candidate -eq 'msedge.exe') {
      return $candidate
    }
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }

  throw 'Microsoft Edge was not found.'
}

function Ensure-Backend([pscustomobject]$Paths) {
  if (-not (Test-Path -LiteralPath $Paths.StartProjectScript)) {
    throw "start_project.ps1 not found: $($Paths.StartProjectScript)"
  }

  & $Paths.StartProjectScript
  if ($LASTEXITCODE -ne 0) {
    throw 'Failed to start backend service.'
  }
}

function Sync-Extension([pscustomobject]$Paths) {
  if (-not (Test-Path -LiteralPath $Paths.SourceExtensionDir)) {
    throw "extension directory not found: $($Paths.SourceExtensionDir)"
  }

  $runtimeDir = $Paths.RuntimeExtensionDir
  $runtimeParent = Split-Path -Parent $runtimeDir
  New-Item -ItemType Directory -Force -Path $runtimeParent | Out-Null

  if (Test-Path -LiteralPath $runtimeDir) {
    if ((Split-Path -Leaf $runtimeDir) -ne 'fliggy-extension') {
      throw "Refusing to delete unexpected directory: $runtimeDir"
    }
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
  }

  Copy-Item -LiteralPath $Paths.SourceExtensionDir -Destination $runtimeDir -Recurse -Force
}

function Clear-ExtensionCaches([pscustomobject]$Paths) {
  $targets = @(
    (Join-Path $Paths.ProfileDir 'Default/Extension Scripts'),
    (Join-Path $Paths.ProfileDir 'Default/Service Worker'),
    (Join-Path $Paths.ProfileDir 'Default/Local Extension Settings/kmbpdggpjflealmalokmjekiccocbmgh'),
    (Join-Path $Paths.ProfileDir 'Default/Sync Extension Settings/kmbpdggpjflealmalokmjekiccocbmgh')
  )

  foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target)) {
      continue
    }
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Stop-DedicatedEdge([pscustomobject]$Paths) {
  $profileBackslash = $Paths.ProfileDir
  $profileSlash = $Paths.ProfileDir -replace '\\', '/'
  $processes = Get-CimInstance Win32_Process -Filter "name = 'msedge.exe'" | Where-Object {
    ($_.CommandLine -like "*$profileBackslash*") -or ($_.CommandLine -like "*$profileSlash*")
  }

  foreach ($process in $processes) {
    try {
      Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    } catch {
      Write-Warning "Failed to stop Edge PID $($process.ProcessId): $($_.Exception.Message)"
    }
  }

  Start-Sleep -Seconds 1
}

function Focus-DedicatedEdge([pscustomobject]$Paths) {
  $profileBackslash = $Paths.ProfileDir
  $profileSlash = $Paths.ProfileDir -replace '\\', '/'
  $process = Get-CimInstance Win32_Process -Filter "name = 'msedge.exe'" | Where-Object {
    ($_.CommandLine -like "*$profileBackslash*") -or ($_.CommandLine -like "*$profileSlash*")
  } | Select-Object -First 1

  if ($null -eq $process) {
    return
  }

  $wshell = New-Object -ComObject WScript.Shell
  [void]$wshell.AppActivate([int]$process.ProcessId)
}

$paths = Get-ProjectPaths
$edgeExe = Get-EdgeExecutable

Ensure-Backend -Paths $paths
Sync-Extension -Paths $paths
New-Item -ItemType Directory -Force -Path $paths.ProfileDir | Out-Null
Stop-DedicatedEdge -Paths $paths
Clear-ExtensionCaches -Paths $paths

$arguments = @(
  '--new-window',
  '--remote-debugging-port=9222',
  "--user-data-dir=$($paths.ProfileDir)",
  "--disable-extensions-except=$($paths.RuntimeExtensionDir)",
  "--load-extension=$($paths.RuntimeExtensionDir)",
  $paths.StartUrl
)

Start-Process -FilePath $edgeExe -ArgumentList $arguments | Out-Null
Start-Sleep -Seconds 2
Focus-DedicatedEdge -Paths $paths

Write-Host 'Opened Edge with Fliggy extension.'
Write-Host "Extension: $($paths.RuntimeExtensionDir)"
Write-Host "Profile: $($paths.ProfileDir)"
Write-Host "URL: $($paths.StartUrl)"

