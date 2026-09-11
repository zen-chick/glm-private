# GLM Remote for Android

Xperia 5 IVから自宅PCのGLM Coreを操作する専用Androidクライアントです。

## 実装済み

- Android KeystoreによるBearerトークン暗号化
- 起動時および緊急停止時の生体認証
- GLM Core状態、GPU温度、VRAM使用量の表示
- OpenAI互換API経由のチャット
- 確認付きKill Switch
- USB経由のローカル限定ペアリング
- HTTPS、localhost、Tailscale IPv4以外の接続拒否

## USB初回設定

1. PCでGLM Coreを起動します。
2. XperiaのUSBデバッグを許可します。
3. `adb reverse tcp:8765 tcp:8765`を実行します。
4. アプリの「USBでペアリング」を押します。

トークンは画面やコマンドへ表示されず、端末のAndroid Keystoreで暗号化されます。

## 外出先接続

PCとXperiaへTailscaleを導入し、PCで `start-glm-mobile.ps1` を実行します。アプリの接続先を表示された`http://100.x.x.x:8765`へ変更してください。ルーターのポート開放とTailscale Funnelは使用しません。

## ビルド

`build-android.ps1`はユーザー領域の`~/.glm/signing`に専用署名鍵とDPAPI暗号化パスワードを作成し、署名済みAPKをGLMの`dist`へ出力します。

```powershell
.\build-android.ps1
.\build-android.ps1 -Install
```

Android Studioではこの`android-client`フォルダーを開いてください。