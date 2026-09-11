# GLM Standalone IDE 一括起動スクリプト (PowerShell 5.1+)
# 文字コード: UTF-8 (BOM付き)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$GLM_DIR = "$SCRIPT_DIR"
$defaultWorkspace = Join-Path $env:USERPROFILE "Desktop\新しいフォルダー"
$WORKSPACE_DIR = if ($env:GLM_STANDALONE_WORKSPACE) { $env:GLM_STANDALONE_WORKSPACE } else { $defaultWorkspace }
New-Item -ItemType Directory -Path $WORKSPACE_DIR -Force | Out-Null

Write-Host ""
Write-Host "  ⚡ GLM Standalone IDE 起動処理" -ForegroundColor Cyan
Write-Host "  $('=' * 50)" -ForegroundColor Cyan

# ── 1. Pythonの確認 ───────────────────────────────────────────────────────────
$pyCmd = $null
$pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pyCommand) {
    $pyCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}
if ($pyCommand) {
    $pyCmd = $pyCommand.Source
}
if (-not $pyCmd) {
    Write-Host "  ✗ Python (py.exe または python.exe) が見つかりません。" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Python: $pyCmd"

# ── 2. Ollamaの接続チェック ───────────────────────────────────────────────────
Write-Host "  [1/3] Ollama 接続確認..." -NoNewline
try:
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 2 -ErrorAction Stop
    Write-Host " [OK]" -ForegroundColor Green
} catch {
    Write-Host " [未起動]" -ForegroundColor Yellow
    Write-Host "  ⚠ Ollama が起動していません。Ollama を起動してください ('ollama serve')" -ForegroundColor Yellow
}

# ── 3. GLM Unified Core (8765) の起動 ────────────────────────────────────────
Write-Host "  [2/2] GLM Unified Core 起動 (Port 8765)..."
$coreScript = "$GLM_DIR\glm_ide_core.py"

# 既存プロセスの終了確認
$existingProcess = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'py.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*glm_ide_core.py*" }
if ($existingProcess) {
    Write-Host "  ○ 既存の Unified Core プロセスを検出しました。"
} else {
    Start-Process $pyCmd -ArgumentList "`"$coreScript`" --workspace `"$WORKSPACE_DIR`"" -WindowStyle Hidden
    $ready = $false
    for ($attempt = 1; $attempt -le 15; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -TimeoutSec 1 -ErrorAction Stop
            if ($health.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
    if (-not $ready) {
        Write-Host "  ✗ Unified Core の起動確認に失敗しました。" -ForegroundColor Red
        exit 1
    }
    Write-Host "  ✓ Unified Core 起動完了" -ForegroundColor Green
}

# Unified Core が静的フロントエンドも同一オリジンから配信するため、別サーバーは不要
$url = "http://127.0.0.1:8765"
Write-Host "  ✓ ブラウザで IDE 画面を開きます: $url" -ForegroundColor Green
Start-Process $url

Write-Host ""
Write-Host "  $('=' * 50)" -ForegroundColor Cyan
Write-Host "  GLM Standalone IDE が正常に起動しました。" -ForegroundColor Green
Write-Host "  画面が開かない場合は手動で $url にアクセスしてください。"
Write-Host ""
