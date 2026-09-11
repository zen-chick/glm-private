# GLM exe / VS Code互換性比較

最終確認: 2026-09-10

## 結論

`ide-web/src-tauri/target/release/glm-standalone-ide.exe` は、TauriでHTML/CSS/JavaScriptのStandalone UIを表示するexeです。VS Code/Code-OSS Workbenchと同じIDEではありません。

VS Codeに近い作業環境として使用する正規入口は、次の統合ランチャーです。

`glm/dist/GLM Workbench Launcher.exe`

このランチャーは、GLM Coreを1つだけ起動・再利用し、Code-OSS WorkbenchとGLM Router拡張を起動します。

## 比較

| 項目 | Tauri Standalone exe | GLM Workbench Launcher exe | VS Code / Code-OSS |
|---|---|---|---|
| ウィンドウ | Tauri WebView | Electron Workbench | Electron Workbench |
| Explorer | 独自HTML実装 | Workbench標準 | Workbench標準 |
| 検索 | 独自API/UI | Workbench標準 | Workbench標準 |
| タブ・分割 | 独自実装 | Workbench標準 | Workbench標準 |
| Command Palette | 独自簡易版 | Workbench標準 | Workbench標準 |
| Git/SCM | 独自API/UI | Workbench標準 + GLM連携 | Workbench標準 |
| Terminal | GLM独自Terminal API | Workbench統合ターミナル | Workbench統合ターミナル |
| Debug/DAP | GLM API接続 | Workbench標準 + GLM連携 | Workbench標準 |
| Extension API | なし | あり | あり |
| GLM Router | Core API経由 | GLM Router拡張 | Copilot等の拡張 |
| Coordinator/MLOps | GLM Core API/UI | GLM拡張へ統合可能 | 標準機能ではない |
| メモリ | 小さい | Electron/Workbench相当 | Electron/Workbench相当 |
| 単体exe | 現在はCore外部依存 | ランタイム隣接が必要 | 配布版はランタイム同梱 |

## 反映済み

- Code-OSS Workbenchのビルド成果物
- GLM Workbenchブランド
- GLM Router拡張
- GLM Core localhost API
- Coordinator / 専門Agent / ApprovalBroker
- Airflow / MLflow / Model Registry API
- GLM Coreの安全なWorkspaceGuardと監査
- Electron統合ランチャー
- Web Workbench起動スクリプト

## 未完成・残る差分

### Tauri Standalone exe側

- Coreの同梱と自動管理
- Workbench標準Explorerとの互換
- VS Code Extension Host
- 標準Command Palette
- 標準SCM、Settings、Terminal、Debug UI
- Workbenchと同じキーボードショートカット

これらをTauri側へ再実装するより、Code-OSS Workbenchを主画面にする方が保守性と互換性に優れます。

### 統合ランチャー側

- Code-OSSランタイムを配布フォルダーへ固定的に同梱
- Python/Coreランタイムの同梱
- 配布用署名
- 更新・アンインストール
- 初回Workspace選択
- Core終了時の子プロセス整理

## 正規の利用方法

```powershell
D:\Users\新しいフォルダー\AIIDE\glm\dist\GLM Workbench Launcher.exe
```

または開発時:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Users\新しいフォルダー\AIIDE\glm\start-glm.ps1
```

`glm-standalone-ide.exe` は、軽量な補助UI・検証用として扱います。
