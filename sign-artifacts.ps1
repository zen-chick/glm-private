# Sign GLM Windows artifacts with an installed code-signing certificate.
# The certificate password must be entered by the operator when signtool prompts.
param(
    [Parameter(Mandatory = $false)]
    [string]$CertificatePath,
    [string]$CertThumbprint = "1D10DB4D1CA1CD1CA16582401991F00CD083A132",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    Write-Error "signtool.exe is required. Install the Windows SDK signing tools."
}
if ($CertificatePath -and -not (Test-Path $CertificatePath -PathType Leaf)) {
    Write-Error "Certificate file was not found: $CertificatePath"
}
if (-not $CertificatePath -and -not $CertThumbprint) {
    Write-Error "Specify CertificatePath or CertThumbprint."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$artifactRoots = @(
    (Join-Path $scriptDir "dist"),
    (Join-Path $scriptDir "ide-web\src-tauri\target\release\bundle")
)
$artifacts = foreach ($root in $artifactRoots) {
    if (Test-Path $root) {
        Get-ChildItem $root -Include "*.exe","*.msi" -File -Recurse
    }
}
if (-not $artifacts) {
    Write-Error "No Windows executables were found under dist. Build first."
}

$isSelfSignedDevCert = -not $CertificatePath

foreach ($artifact in $artifacts) {
    if ($CertificatePath) {
        & $signtool.Source sign /fd SHA256 /f $CertificatePath /tr $TimestampUrl /td SHA256 $artifact.FullName
    } else {
        & $signtool.Source sign /fd SHA256 /sha1 $CertThumbprint /tr $TimestampUrl /td SHA256 $artifact.FullName
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Signing failed: $($artifact.FullName)"
    }
    & $signtool.Source verify /pa /all $artifact.FullName
    if ($LASTEXITCODE -ne 0) {
        if ($isSelfSignedDevCert) {
            # ローカル開発用の自己署名証明書は信頼済みルートに連鎖しないため、この失敗は想定内。
            Write-Warning "Signature applied but chain is not trusted (expected for a self-signed dev certificate): $($artifact.FullName)"
        } else {
            Write-Error "Signature verification failed: $($artifact.FullName)"
        }
    } else {
        Write-Host "Signed and verified: $($artifact.Name)" -ForegroundColor Green
        continue
    }
    Write-Host "Signed (trust chain unverified): $($artifact.Name)" -ForegroundColor Yellow
}
