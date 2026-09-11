# Code-OSS / GLM Compliance Baseline

最終更新: 2026-09-08
用途: 個人利用のGLM Workbench構築前のライセンス・解析範囲の整理

## 結論

GLMの完全なVS Code相当ワークベンチは、Microsoft版VS Codeのバイナリを解析して作るのではなく、公開されているCode-OSSソースを基盤に構築する。

Code-OSS本体はMIT License。MITの著作権表示・ライセンス表示を保持する。Microsoft版Visual Studio CodeはCode-OSSにMicrosoft固有のカスタマイズを加えた別配布物であり、製品ライセンス・商標・Marketplace・一部の非公開機能をそのまま利用しない。

この文書は法的助言ではない。公開配布・商用配布の前に専門家による最終確認を行う。

## 利用してよい範囲

- Code-OSSの公開ソースコード、公開ドキュメント、公開APIの利用・改変
- VS Code Extension APIの公開仕様に従う拡張機能の開発
- 自作GLMコードの解析・改変
- 動作確認のためのブラックボックステスト
- 依存ライブラリの公開ライセンス・API・互換性調査
- Code-OSSの製品名・ロゴを使わない独自ブランドへの変更

## 利用しない範囲

- Microsoft版VS Codeのバイナリ逆コンパイル・逆アセンブルによる複製
- Copilot、Marketplace、VS Code Serverなどの非公開通信・認証・内部APIの解析
- ライセンスチェック、署名、課金・アクセス制限の回避
- Microsoftの商標、ロゴ、製品固有アセットの無断流用
- Marketplace利用規約に反する拡張機能取得・再配布
- ライセンス表示を除去した依存コードの取り込み

## 台帳

| コンポーネント | 利用方法 | ライセンス確認 | 方針 |
|---|---|---|---|
| Code-OSS | Workbench基盤 | MIT | 著作権・ライセンス表示を保持 |
| Monaco Editor | 現行Standaloneで利用 | 依存パッケージのLICENSEを確認 | NOTICEへ記録 |
| Tauri | ネイティブシェル | 依存パッケージのLICENSEを確認 | Cargo.lockから台帳化 |
| co-vibe-core | GLM Agent統合 | MIT（同梱LICENSE） | NOTICEへ著作権表示を保持 |
| GLM独自コード | Router、Security、Agent連携 | プロジェクト方針に従う | 独自実装として管理 |
| Microsoft VS Code | 直接利用しない | Microsoft product license | バイナリ・商標・固有資産を取り込まない |
| VS Marketplace | 直接利用しない | Marketplace Terms of Use | 個人用の許可された取得方法を別途確認 |

## 実装上の分離

- Code-OSS側: Workbench、拡張ホスト、設定、タスク、デバッグ、ターミナル、ファイルサービス
- GLM側: Router、ローカルモデル、Agent、承認、監査、予算、熱管理
- 境界: 公開APIまたはlocalhostの認証付きGLMサービス
- 配布物: `GLM Standalone IDE`の名称・アイコン・product.jsonを使用
- telemetry: 既定無効。GLM側の監査ログと外部送信を分離

## 参照した公式情報

- https://github.com/microsoft/vscode/blob/main/LICENSE.txt
- https://github.com/microsoft/vscode/blob/main/README.md
- https://github.com/microsoft/vscode/wiki/Differences-between-the-repository-and-Visual-Studio-Code
