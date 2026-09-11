#requires -RunAsAdministrator
# Enable optional Windows isolation features. Review before running.
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

Write-Host "Enabling WSL and Windows Sandbox features..." -ForegroundColor Cyan
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart
Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -NoRestart
$sshCapability = Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
if ($sshCapability.RestartNeeded) {
	Write-Host "OpenSSH Serverの有効化にはWindowsの再起動が必要です。再起動後にこのスクリプトを再実行してください。" -ForegroundColor Yellow
} elseif (Get-Service -Name sshd -ErrorAction SilentlyContinue) {
	Set-Service -Name sshd -StartupType Manual
	Write-Host "OpenSSH Serverを有効化しました。必要時は Start-Service sshd で起動できます。" -ForegroundColor Green
} else {
	Write-Error "OpenSSH Serverの有効化後もsshdサービスが見つかりません。管理者権限で再実行してください。"
}
Write-Host "WSL/Sandboxの有効化後は再起動し、WSLディストリビューションを登録してください: wsl --install -d Ubuntu" -ForegroundColor Green
