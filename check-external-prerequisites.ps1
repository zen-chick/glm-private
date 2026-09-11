# GLM external prerequisite check
# Does not print API keys or modify Windows features.
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Continue"

function Show-Check($name, $ok, $detail) {
    $mark = if ($ok) { "OK" } else { "MISSING" }
    $color = if ($ok) { "Green" } else { "Yellow" }
    Write-Host ("[{0}] {1}: {2}" -f $mark, $name, $detail) -ForegroundColor $color
}

$cargo = Get-Command cargo.exe -ErrorAction SilentlyContinue
Show-Check "Cargo" ($null -ne $cargo) $(if ($cargo) { $cargo.Source } else { "Install Rust toolchain" })

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
$wslReady = $false
$wslDetail = "wsl.exe not found"
if ($wsl) {
    $wslOutput = & $wsl.Source --list --quiet 2>&1 | Out-String
    $wslReady = $LASTEXITCODE -eq 0 -and $wslOutput.Trim().Length -gt 0
    $wslDetail = if ($wslReady) { $wslOutput.Trim() } else { "Install/register a WSL distribution" }
}
Show-Check "WSL2 distribution" $wslReady $wslDetail

$sandbox = Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -ErrorAction SilentlyContinue
$sandboxReady = $sandbox -and $sandbox.State -eq "Enabled"
Show-Check "Windows Sandbox" $sandboxReady $(if ($sandbox) { [string]$sandbox.State } else { "Requires administrator access to query" })

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
Show-Check "signtool" ($null -ne $signtool) $(if ($signtool) { $signtool.Source } else { "Install Windows SDK signing tools" })

$sshd = Get-Command sshd.exe -ErrorAction SilentlyContinue
$sshdService = Get-Service sshd -ErrorAction SilentlyContinue
Show-Check "OpenSSH Server" ($null -ne $sshd -and $null -ne $sshdService) $(if ($sshdService) { $sshdService.Status } else { "Install OpenSSH Server optional feature" })

foreach ($name in @("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY")) {
    $configured = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))
    Show-Check $name $configured $(if ($configured) { "configured (value hidden)" } else { "not configured" })
}

Write-Host ""
Write-Host "No installation or privilege escalation was performed." -ForegroundColor Cyan
