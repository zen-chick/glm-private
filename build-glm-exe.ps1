# Build the single-entry GLM Workbench launcher executable.
param(
    [string]$OutputName = "GLM Workbench Launcher",
    [switch]$CoreOnly
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$glmDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path $glmDir -Parent
$python = (Get-Command py.exe -ErrorAction Stop).Source

$entryPoint = if ($CoreOnly) { "glm_ide_core.py" } else { "glm_launcher.py" }
$name = if ($CoreOnly) { "GLM Core" } else { $OutputName }
$pyInstallerArgs = @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--name", $name, "--distpath", (Join-Path $glmDir "dist"),
    "--workpath", (Join-Path $glmDir ".build\pyinstaller"))
if ($CoreOnly) {
    $pyInstallerArgs += @("--add-data", ((Join-Path $glmDir "ide-web") + ";ide-web"),
        "--add-data", ((Join-Path $glmDir "registry.json") + ";."),
        "--add-data", ((Join-Path $glmDir "settings.json") + ";."),
        "--add-data", ((Join-Path $glmDir "integrations.json") + ";."),
        "--exclude-module", "pytest", "--exclude-module", "jupyter_client",
        "--exclude-module", "ipykernel", "--exclude-module", "debugpy",
        "--exclude-module", "paramiko", "--exclude-module", "zmq",
        "--exclude-module", "numpy", "--exclude-module", "matplotlib",
        "--exclude-module", "IPython")
}
$pyInstallerArgs += (Join-Path $glmDir $entryPoint)
& $python $pyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $glmDir "dist\$name.exe"
if (-not (Test-Path $exe)) { throw "Launcher executable was not generated: $exe" }
Write-Host "Generated: $exe" -ForegroundColor Green
Write-Host "Place this executable next to the AIIDE folder or keep the current project layout." -ForegroundColor Yellow
