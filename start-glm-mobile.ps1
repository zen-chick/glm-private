param(
    [int]$Port = 8765,
    [string]$Workspace = $PSScriptRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $tailscale) {
    $installed = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $installed) { $tailscale = Get-Item $installed }
}
if (-not $tailscale) {
    throw "Tailscaleが見つかりません。PCとXperiaの両方へTailscaleを導入してください。"
}

$tailscaleIp = (& $tailscale.Source ip -4 | Select-Object -First 1).Trim()
if ($tailscaleIp -notmatch '^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.') {
    throw "有効なTailscale IPv4アドレスを取得できません。tailscale upを完了してください。"
}

Write-Host "GLM Mobile endpoint: http://${tailscaleIp}:$Port" -ForegroundColor Cyan
Write-Host "インターネットへ直接公開せず、Tailnet ACLでXperiaだけを許可してください。" -ForegroundColor Yellow
& "C:\Windows\py.exe" "$PSScriptRoot\glm_ide_core.py" --workspace $Workspace --port $Port --bind-host $tailscaleIp