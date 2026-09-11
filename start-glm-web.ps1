# GLM Workbench Web development launcher
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$glmDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$codeOssDir = Join-Path (Split-Path $glmDir -Parent) "code-oss"
$workspace = if ($env:GLM_WORKSPACE) { $env:GLM_WORKSPACE } else { Join-Path $env:USERPROFILE "Desktop\新しいフォルダー" }
$core = Join-Path $glmDir "glm_ide_core.py"
$extension = Join-Path $codeOssDir "extensions\glm-router"
$python = (Get-Command py.exe -ErrorAction Stop).Source

if (-not (Test-Path $extension)) { throw "GLM Router extension is missing: $extension" }
$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'py.exe'" |
    Where-Object { $_.CommandLine -like "*glm_ide_core.py*--port 8765*" } |
    Select-Object -First 1
if (-not $existing) {
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
    $webWorkbench = Join-Path $codeOssDir "out\vs\code\browser\workbench\workbench.js"
    if (-not (Test-Path $webWorkbench)) {
        & npm.cmd run compile-web
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $webWorkbench)) {
            throw "Code-OSS Web output is unavailable after npm.cmd run compile-web"
        }
    }
    & node.exe scripts/code-web.js $workspace --host 127.0.0.1 --port 8080 --browserType none --extensionDevelopmentPath $extension
} finally {
    Pop-Location
}
