# GLM Workbench Migration Plan

最終更新: 2026-09-09

## 目的

GLM Standaloneを補助UIとして維持し、Code-OSS Workbenchを主画面とするWeb/Electron共通のIDEプラットフォームへ移行する。

最終形は、HTML/CSS/TypeScriptで構成されたCode-OSS WorkbenchをElectronまたはブラウザーで動かし、GLM Coreをlocalhostサービス、GLM RouterをWorkbench拡張として接続する。StandaloneのExplorer等をVS Code互換へ再実装するのではなく、Workbench標準機能を主操作面にする。

現行の独自Standalone UIは機能確認用として維持する。Cドライブの検証ワークスペースとDドライブの開発ソースは分離する。

## 完成条件

- Explorer、Search、SCM、Run and Debug、Extensions、SettingsをWorkbenchの標準操作で利用できる
- `settings.json`、`tasks.json`、`launch.json`、workspace fileを扱える
- VS Code Extension APIの通常拡張をインストール・起動・停止できる
- LSP、DAP、ターミナル、Git、ファイルwatcher、Quick Open、Command Paletteが動作する
- GLM Routerをモデルプロバイダーとして利用できる
- GLM AgentのWrite、Read、Search、実行、承認、監査がWorkbenchから利用できる
- system指示や内部ツール状態は通常表示から分離し、必要時だけ詳細表示できる
- Code-OSSのMIT表示、依存ライセンス、GLM独自NOTICEを配布物に含める
- Microsoft版VS Code固有の商標、Marketplace、Copilot、非公開APIを含めない

## フェーズ

### Phase 0: 基盤と台帳

- Code-OSSソースを専用ディレクトリへ取得
- Node.js、Python、Rust、ビルド要件を確認
- `product.json`、ブランド、telemetry、更新URLをGLM向けに定義
- 依存ライセンスをNOTICEへ集約

### Phase 1: Code-OSS単体ビルド

- GLM統合なしでCode-OSSをWindows上でビルド
- 起動、Workbench、標準拡張、設定、ターミナルを確認
- 公式VS Codeバイナリではなく、GLMブランドのCode-OSS配布物にする

### Phase 2: GLMサービス統合

- GLM Coreをlocalhostサービスとして起動
- 認証トークン、WorkspaceGuard、監査ログを維持
- Chat/Agent UIをCode-OSSのサイドバーまたはWebviewへ統合
- GLM Routerのモデル選択・モード・予算・熱状態を表示
- Electron主画面は `start-glm-workbench.ps1` から生成済みWorkbenchを起動する
- Web主画面は `start-glm-web.ps1` からCode-OSS Webを起動する

### Phase 3: 開発機能統合

- GLM LSP、DAP、タスク、ターミナル、Git操作をWorkbenchサービスへ接続
- ファイル操作はWorkspaceGuardと承認ブローカーを必ず経由
- system指示、Agent内部トレース、承認要求を通常チャットから分離

### Phase 4: 互換性検証

- 標準拡張のインストール・起動・停止
- Python、JSON、TypeScript、Markdownの編集・診断
- 定義ジャンプ、参照検索、リネーム、補完
- tasks.json実行、launch.jsonデバッグ、統合ターミナル
- マルチルート、再起動後の設定保持、クラッシュ復旧
- C側検証ワークスペースでGLM Standalone経由の受入テスト

## 現行資産の扱い

- `router.py`, `glm_ide_core.py`, `glm_security.py`: GLMバックエンドとして再利用
- `glm_agent.py`, `glm_covibe_adapter.py`: Agent実行層として再利用
- `vscode-extension/`: VS Code側の既存統合として維持
- `ide-web/`: 移行期間の軽量検証UIとして維持
- `start-glm-workbench.ps1`: Electron版Workbenchの正規起動経路
- `start-glm-web.ps1`: ブラウザー版Workbenchの開発起動経路
- `start-glm.ps1`: 推奨する唯一の統合起動入口。既定はWorkbench
- `dist/GLM Workbench Launcher.exe`: Windows向け単一起動exe。隣接する`AIIDE/code-oss`を使ってCoreとWorkbenchを起動する
- `C:\Users\pcgam\Desktop\新しいフォルダー`: GLM Standaloneの機能確認用workspace
- `D:\Users\新しいフォルダー\AIIDE\glm`: 開発ソース・ビルド用workspace

## 2026-09-08 実施済み

- Code-OSS shallow cloneを `D:\Users\新しいフォルダー\AIIDE\code-oss` に取得
- `product.json` をGLM Workbenchブランドへ変更
- Copilot既定設定、Copilot自動更新、Microsoft音声サービスURLを除外
- `build-fast.ts` をGLM配布時にCopilot工程をスキップするよう変更
- GLM Router拡張を `extensions/glm-router` に統合
- GLM Core接続設定をproduct.jsonへ追加
- Client output、Extension Host output、標準拡張の型チェックを確認
- GLM Workbenchスモークテストを追加し、Core healthを確認
- Electronランタイムを `.build/electron/GLM Workbench.exe` に取得

## 2026-09-09 実施済み

- Workbenchを主画面、Standaloneを補助UIとする方針を明文化
- Electron起動スクリプトを生成タスクと実行タスクに分離
- Code-OSS Web起動スクリプトを追加
- GLM CoreのCoordinator、Airflow、MLflow、Model Registry APIをWorkbench統合対象として維持

残作業:

- 開発用NLS生成の正式タスク化
- Electronのnative optional addon（policy-watcher等）の配布/ビルド整理
- GLM Router拡張のWorkbench UI受入テスト
- 完全配布用の依存ライセンスNOTICE生成

## 解析方針

公開Code-OSSソースと公開APIを読む。Microsoft版バイナリ、Copilot、Marketplace、非公開サービスの通信・認証・署名を解析しない。
