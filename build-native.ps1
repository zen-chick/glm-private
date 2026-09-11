# GLM Native GUI build gate
# Requires Rust/Cargo and a complete Tauri project.
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$webDir = Join-Path $scriptDir "ide-web"
$distDir = Join-Path $webDir "dist"
$cargo = Get-Command cargo.exe -ErrorAction SilentlyContinue
if (-not $cargo) {
    Write-Error "Rust/Cargo is required. Install the Rust toolchain, then rerun this script."
}
$linker = Get-Command link.exe -ErrorAction SilentlyContinue
 $buildToolsVcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if (Test-Path $buildToolsVcvars) {
    $envDump = & cmd.exe /c "call `"$buildToolsVcvars`" x64 & set"
    foreach ($line in $envDump) {
        if ($line -match '^([^=]+)=(.*)$') { Set-Item -Path ("Env:" + $matches[1]) -Value $matches[2] }
    }
    $linker = Get-Command link.exe -ErrorAction SilentlyContinue
}
if (-not $linker) {
    Write-Error "MSVC link.exe is required. Install Visual Studio C++ Build Tools."
}

if (-not $env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR = "C:\glm-target" }

$tauriConfig = Join-Path $webDir "src-tauri\tauri.conf.json"
$cargoManifest = Join-Path $webDir "src-tauri\Cargo.toml"
if (-not (Test-Path $tauriConfig) -or -not (Test-Path $cargoManifest)) {
    Write-Error "The Tauri Rust project is incomplete: src-tauri/Cargo.toml is missing."
}

if (Test-Path $distDir) {
    Remove-Item $distDir -Recurse -Force
}
New-Item -ItemType Directory -Path $distDir | Out-Null
& (Join-Path $scriptDir "build-glm-exe.ps1") -CoreOnly
if ($LASTEXITCODE -ne 0) { throw "GLM Core executable build failed" }
New-Item -ItemType Directory -Path (Join-Path $distDir "resources") | Out-Null
Copy-Item (Join-Path $scriptDir "dist\GLM Core.exe") (Join-Path $distDir "resources\GLM Core.exe") -Force
Copy-Item (Join-Path $webDir "index.html"), (Join-Path $webDir "app.js"), (Join-Path $webDir "style.css") $distDir
Copy-Item (Join-Path $webDir "vs") $distDir -Recurse

Push-Location $webDir
try {
    & npm.cmd run tauri -- build
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tauri build failed. Check the Rust/Tauri diagnostics above."
    }
} finally {
    Pop-Location
}
