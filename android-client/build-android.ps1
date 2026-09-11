param(
    [switch]$Install
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$javaHome = "C:\Program Files\Android\Android Studio\jbr"
$sdkDir = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$signingDir = Join-Path $env:USERPROFILE ".glm\signing"
$keyStore = Join-Path $signingDir "glm-remote.jks"
$passwordFile = Join-Path $signingDir "glm-remote-password.dpapi"
$outputDir = Join-Path (Split-Path -Parent $projectDir) "dist"
$outputApk = Join-Path $outputDir "GLM-Remote-v1.0.0.apk"

if (-not (Test-Path "$javaHome\bin\keytool.exe")) { throw "Android Studio JBRが見つかりません。" }
if (-not (Test-Path $sdkDir)) { throw "Android SDKが見つかりません。" }
New-Item -ItemType Directory -Path $signingDir -Force | Out-Null
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

if (-not (Test-Path $keyStore) -or -not (Test-Path $passwordFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes)
    ConvertTo-SecureString $password -AsPlainText -Force | ConvertFrom-SecureString | Set-Content $passwordFile -Encoding ASCII
    & "$javaHome\bin\keytool.exe" -genkeypair -keystore $keyStore -storepass $password -keypass $password -alias glm-remote -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=GLM Remote, OU=Private, O=GLM, C=JP"
    if ($LASTEXITCODE -ne 0) { throw "署名鍵を生成できませんでした。" }
}

$securePassword = (Get-Content $passwordFile -Raw).Trim() | ConvertTo-SecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:JAVA_HOME = $javaHome
    $env:ANDROID_HOME = $sdkDir
    $env:GLM_ANDROID_STORE_FILE = $keyStore
    $env:GLM_ANDROID_STORE_PASSWORD = $password
    Push-Location $projectDir
    try {
        & ".\gradlew.bat" --no-daemon clean :app:assembleRelease
        if ($LASTEXITCODE -ne 0) { throw "Androidリリースビルドに失敗しました。" }
    } finally {
        Pop-Location
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Item Env:\GLM_ANDROID_STORE_PASSWORD -ErrorAction SilentlyContinue
    $password = $null
}

Copy-Item "$projectDir\app\build\outputs\apk\release\app-release.apk" $outputApk -Force
Write-Host "署名済みAPK: $outputApk" -ForegroundColor Green

if ($Install) {
    $adb = Join-Path $sdkDir "platform-tools\adb.exe"
    & $adb install -r $outputApk
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "署名が異なる旧Debug版がある場合は、端末からGLM Remoteを削除して再実行してください。"
        exit $LASTEXITCODE
    }
}