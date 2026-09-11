# GLM Workbench (Code-OSS based) development launcher
# Workspace: C:\Users\pcgam\Desktop\新しいフォルダー
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$glmDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$codeOssDir = Join-Path (Split-Path $glmDir -Parent) "code-oss"
$workspace = if ($env:GLM_WORKSPACE) { $env:GLM_WORKSPACE } else { Join-Path $env:USERPROFILE "Desktop\新しいフォルダー" }
$core = Join-Path $glmDir "glm_ide_core.py"
$python = (Get-Command py.exe -ErrorAction Stop).Source
$electron = Join-Path $codeOssDir ".build\electron\GLM Workbench.exe"
$main = Join-Path $codeOssDir "out\main.js"
$extension = Join-Path $codeOssDir "extensions\glm-router"
$userData = Join-Path $env:LOCALAPPDATA "GLMWorkbench"

New-Item -ItemType Directory -Path $workspace -Force | Out-Null
$env:GLM_STANDALONE_WORKSPACE = $workspace
$env:GLM_ROUTER_PATH = Join-Path $glmDir "router.py"

$coreProcess = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'py.exe'" |
    Where-Object { $_.CommandLine -like "*glm_ide_core.py*--port 8765*" } |
    Select-Object -First 1
if (-not $coreProcess) {
    Start-Process $python -ArgumentList "`"$core`" --workspace `"$workspace`" --port 8765" -WindowStyle Hidden
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -TimeoutSec 1 -ErrorAction Stop
            if ($health.StatusCode -eq 200) { break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
}

Push-Location $codeOssDir
try {
    if (-not (Test-Path $electron) -or -not (Test-Path $main)) {
        throw "GLM Workbench build artifacts are missing. Run: npm.cmd run electron and npm.cmd run build-fast"
    }
    if (-not (Test-Path (Join-Path $extension "package.json"))) {
        throw "GLM Router extension is missing: $extension"
    }
    $env:ELECTRON_RUN_AS_NODE = $null
    $env:VSCODE_PID = $null
    New-Item -ItemType Directory -Path $userData -Force | Out-Null
    & $electron $main --no-sandbox --disable-telemetry --disable-updates --skip-welcome `
        "--user-data-dir=$userData" "--extensionDevelopmentPath=$extension" $workspace
} finally {
    Pop-Location
}
