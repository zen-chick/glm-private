# GLM unified launcher
# Default: Code-OSS based GLM Workbench. Optional modes: Standalone or Web.
[CmdletBinding()]
param(
    [ValidateSet('Workbench', 'Standalone', 'Web')]
    [string]$Mode = 'Workbench',
    [string]$Workspace = '',
    [switch]$CleanDuplicateCore
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$glmDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$codeOssDir = Join-Path (Split-Path $glmDir -Parent) 'code-oss'
$workspacePath = if ($Workspace) { $Workspace } elseif ($env:GLM_WORKSPACE) { $env:GLM_WORKSPACE } else { Join-Path $env:USERPROFILE 'Desktop\新しいフォルダー' }
$coreScript = Join-Path $glmDir 'glm_ide_core.py'
$python = (Get-Command py.exe -ErrorAction Stop).Source

New-Item -ItemType Directory -Path $workspacePath -Force | Out-Null
$env:GLM_WORKSPACE = $workspacePath
$env:GLM_STANDALONE_WORKSPACE = $workspacePath
$env:GLM_ROUTER_PATH = Join-Path $glmDir 'router.py'

function Get-CoreProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'py.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*glm_ide_core.py*--port 8765*' })
}

$coreProcesses = @(Get-CoreProcesses)
if ($CleanDuplicateCore -and $coreProcesses.Count -gt 1) {
    foreach ($duplicate in $coreProcesses | Select-Object -Skip 1) {
        Stop-Process -Id $duplicate.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $coreProcesses = @(Get-CoreProcesses)
}

if ($coreProcesses.Count -eq 0) {
    Start-Process $python -ArgumentList "`"$coreScript`" --workspace `"$workspacePath`" --port 8765" -WindowStyle Hidden | Out-Null
}

$ready = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($health.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 400 }
}
if (-not $ready) { throw 'GLM Core did not become ready on port 8765.' }

switch ($Mode) {
    'Standalone' {
        Start-Process 'http://127.0.0.1:8765/' | Out-Null
        Write-Host 'GLM Standalone opened: http://127.0.0.1:8765/'
    }
    'Web' {
        $webScript = Join-Path $glmDir 'start-glm-web.ps1'
        & $webScript
    }
    default {
        $electron = Join-Path $codeOssDir '.build\electron\GLM Workbench.exe'
        $main = Join-Path $codeOssDir 'out\main.js'
        $extension = Join-Path $codeOssDir 'extensions\glm-router'
        if (-not (Test-Path $electron) -or -not (Test-Path $main)) {
            throw 'GLM Workbench artifacts are missing. Build Code-OSS before launching.'
        }
        if (-not (Test-Path (Join-Path $extension 'package.json'))) {
            throw 'GLM Router extension is missing.'
        }
        $userData = Join-Path $env:LOCALAPPDATA 'GLMWorkbench'
        New-Item -ItemType Directory -Path $userData -Force | Out-Null
        $env:ELECTRON_RUN_AS_NODE = $null
        $env:VSCODE_PID = $null
        & $electron $main --no-sandbox --disable-telemetry --disable-updates --skip-welcome `
            "--user-data-dir=$userData" "--extensionDevelopmentPath=$extension" $workspacePath
    }
}
