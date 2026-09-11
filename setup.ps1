# GLM セットアップスクリプト
# 実行: PowerShell 5.1以上、管理者権限不要（ファイアウォール設定のみ管理者が必要）
# 文字コード: UTF-8 BOM付き（PowerShell 5.1互換）

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$GLM_DIR   = "$env:USERPROFILE\.glm"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  GLM セットアップ v0.1" -ForegroundColor Cyan
Write-Host "  $('=' * 46)" -ForegroundColor Cyan

# ── 1. ディレクトリ作成 ─────────────────────────────────────────────────────
Write-Host "`n  [1/5] ディレクトリ作成"
foreach ($d in @(
    "$GLM_DIR\sessions",
    "$GLM_DIR\logs",
    "$GLM_DIR\secrets",
    "$GLM_DIR\audit"
)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d | Out-Null
        Write-Host "  ✓ 作成: $d"
    } else {
        Write-Host "  ○ 既存: $d"
    }
}

# ── 2. IDEオプション依存 ───────────────────────────────────────────────────
Write-Host "`n  [2/6] IDEオプション依存 (Jupyter / DAP)"
$pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}
if ($pythonCommand -and (Test-Path "$SCRIPT_DIR\requirements-optional.txt")) {
    & $pythonCommand.Source -m pip install -r "$SCRIPT_DIR\requirements-optional.txt"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Jupyter / DAP依存を導入しました。" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ オプション依存の導入に失敗しました。IDE本体は続行します。" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ⚠ Pythonまたはrequirements-optional.txtが見つかりません。" -ForegroundColor Yellow
}

# ── 3. Ollama確認 ──────────────────────────────────────────────────────────
Write-Host "`n  [3/6] Ollama確認"
$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaPath = $null
if ($ollamaCommand) {
    $ollamaPath = $ollamaCommand.Source
}
if ($ollamaPath) {
    Write-Host "  ✓ Ollama検出: $ollamaPath"
} else {
    Write-Host "  ✗ Ollamaが見つかりません。" -ForegroundColor Red
    Write-Host "    → https://ollama.com/download からインストールしてください。" -ForegroundColor Yellow
    exit 1
}

# ── 4. モデルプル ──────────────────────────────────────────────────────────
Write-Host "`n  [4/6] モデルプル（初回のみ、時間がかかります）"

# Ollamaサービス起動確認
$apiUp = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 3 -ErrorAction Stop
    $apiUp = $true
} catch {}

if (-not $apiUp) {
    Write-Host "  Ollamaを起動します..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# 既存モデルのリスト取得
$existingModels = @()
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -ErrorAction Stop
    $data = $resp.Content | ConvertFrom-Json
    $existingModels = $data.models | ForEach-Object { $_.name }
} catch {
    Write-Host "  ⚠ モデルリスト取得失敗（Ollamaが起動していない可能性あり）" -ForegroundColor Yellow
}

foreach ($m in @("qwen3:0.5b", "qwen2.5-coder:7b")) {
    if ($existingModels -contains $m) {
        Write-Host "  ○ 既存: $m"
    } else {
        Write-Host "  ↓ プル中: $m ..."
        ollama pull $m
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ 完了: $m"
        } else {
            Write-Host "  ✗ 失敗: $m" -ForegroundColor Red
        }
    }
}

# qwen3.5:1.7bは手動判断を推奨（モデルが正式リリースされていない場合がある）
Write-Host "  ○ nano-light (qwen3.5:1.7b) は手動でプルしてください:"
Write-Host "    ollama pull qwen3.5:1.7b" -ForegroundColor Yellow

# ── 5. Modelfile登録 ──────────────────────────────────────────────────────
Write-Host "`n  [5/6] Modelfile登録"
$modelsDir = "$SCRIPT_DIR\models"

foreach ($item in @(
    @{ File = "nano-gate.Modelfile";  Name = "GLM-nano-gate" },
    @{ File = "nano-light.Modelfile"; Name = "GLM-nano-light" }
)) {
    $mf = "$modelsDir\$($item.File)"
    if (Test-Path $mf) {
        Write-Host "  登録: $($item.Name) ..."
        ollama create $($item.Name) -f $mf
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ $($item.Name)"
        } else {
            Write-Host "  ✗ 失敗: $($item.Name)" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ Modelfileなし: $mf" -ForegroundColor Yellow
    }
}

# ── 6. ファイアウォール（オプション、管理者実行時のみ） ─────────────────────
Write-Host "`n  [6/6] ファイアウォール設定（スキップ可）"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) {
    $ruleName = "GLM-Router-8765"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort 8765 `
            -RemoteAddress LocalSubnet `
            -Action Allow | Out-Null
        Write-Host "  ✓ ファイアウォール規則追加: $ruleName (LAN内のみ)"
    } else {
        Write-Host "  ○ ファイアウォール規則既存: $ruleName"
    }
} else {
    Write-Host "  ○ 管理者でないためスキップ（LAN接続が必要な場合のみ手動設定）"
}

# ── 完了メッセージ ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  $('=' * 46)" -ForegroundColor Cyan
Write-Host "  セットアップ完了！" -ForegroundColor Green
Write-Host ""
Write-Host "  起動コマンド:" -ForegroundColor White
Write-Host "    python $SCRIPT_DIR\router.py" -ForegroundColor Cyan
Write-Host "    python $SCRIPT_DIR\router.py --doctor    # 診断" -ForegroundColor Cyan
Write-Host "    python $SCRIPT_DIR\router.py --status    # ハード状態確認" -ForegroundColor Cyan
Write-Host "    python $SCRIPT_DIR\router.py --sessions  # セッション一覧" -ForegroundColor Cyan
Write-Host ""
