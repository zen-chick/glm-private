package com.glm.remote;

import android.app.Activity;
import android.app.AlertDialog;
import android.hardware.biometrics.BiometricPrompt;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.security.GeneralSecurityException;
import java.util.concurrent.Executor;

public final class MainActivity extends Activity {
    private static final int INK = 0xFF16241F;
    private static final int FOREST = 0xFF0C3328;
    private static final int GREEN = 0xFF006C4C;
    private static final int PAPER = 0xFFF7F8F3;
    private static final int MIST = 0xFFE3EBE6;
    private static final int DANGER = 0xFFB42336;

    private SecureStore secureStore;
    private GlmApi api;
    private LinearLayout transcript;
    private ScrollView transcriptScroll;
    private EditText prompt;
    private TextView connectionLabel;
    private TextView metricsLabel;
    private ProgressBar progress;
    private Button sendButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(FOREST);
        getWindow().setNavigationBarColor(PAPER);
        secureStore = new SecureStore(this);
        api = new GlmApi();
        showApp();
        if (secureStore.hasConfiguration()) {
            authenticate("GLM Remoteのロックを解除", this::refreshStatus, this::finish);
        } else {
            showSettings();
        }
    }

    private void showApp() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(PAPER);

        LinearLayout header = horizontal(16, 12);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setBackgroundColor(FOREST);
        TextView brand = text("GLM Remote", 22, 0xFFFFFFFF);
        brand.setTypeface(null, android.graphics.Typeface.BOLD);
        header.addView(brand, new LinearLayout.LayoutParams(0, dp(52), 1));
        Button settings = button("設定", MIST, INK);
        settings.setContentDescription("接続設定");
        settings.setOnClickListener(view -> authenticate("設定を開く", this::showSettings, null));
        header.addView(settings, new LinearLayout.LayoutParams(dp(72), dp(42)));
        root.addView(header);

        LinearLayout status = new LinearLayout(this);
        status.setOrientation(LinearLayout.VERTICAL);
        status.setPadding(dp(18), dp(14), dp(18), dp(14));
        status.setBackgroundColor(MIST);
        connectionLabel = text("未接続", 15, INK);
        connectionLabel.setTypeface(null, android.graphics.Typeface.BOLD);
        metricsLabel = text("接続設定を確認してください", 13, 0xFF4B5F57);
        status.addView(connectionLabel);
        status.addView(metricsLabel);
        root.addView(status);

        transcriptScroll = new ScrollView(this);
        transcript = new LinearLayout(this);
        transcript.setOrientation(LinearLayout.VERTICAL);
        transcript.setPadding(dp(14), dp(18), dp(14), dp(18));
        transcript.addView(message("GLM Coreへ安全に接続して会話を開始します。", false));
        transcriptScroll.addView(transcript);
        root.addView(transcriptScroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        progress.setVisibility(View.GONE);
        root.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)));

        LinearLayout composer = horizontal(12, 10);
        composer.setGravity(Gravity.BOTTOM);
        prompt = new EditText(this);
        prompt.setHint("GLMへメッセージ");
        prompt.setTextColor(INK);
        prompt.setHintTextColor(0xFF66756F);
        prompt.setMinLines(1);
        prompt.setMaxLines(5);
        prompt.setImeOptions(EditorInfo.IME_ACTION_SEND);
        prompt.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        prompt.setBackground(shape(0xFFFFFFFF, 0xFFC7D2CC, 1, 6));
        prompt.setPadding(dp(12), dp(9), dp(12), dp(9));
        prompt.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendMessage();
                return true;
            }
            return false;
        });
        composer.addView(prompt, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        sendButton = button("送信", GREEN, 0xFFFFFFFF);
        sendButton.setOnClickListener(view -> sendMessage());
        LinearLayout.LayoutParams sendParams = new LinearLayout.LayoutParams(dp(76), dp(48));
        sendParams.leftMargin = dp(8);
        composer.addView(sendButton, sendParams);
        root.addView(composer);

        LinearLayout footer = horizontal(12, 8);
        Button refresh = button("状態を更新", 0xFFFFFFFF, GREEN);
        refresh.setOnClickListener(view -> refreshStatus());
        footer.addView(refresh, new LinearLayout.LayoutParams(0, dp(44), 1));
        Button kill = button("緊急停止", DANGER, 0xFFFFFFFF);
        kill.setOnClickListener(view -> confirmKill());
        LinearLayout.LayoutParams killParams = new LinearLayout.LayoutParams(0, dp(44), 1);
        killParams.leftMargin = dp(8);
        footer.addView(kill, killParams);
        root.addView(footer);

        setContentView(root);
    }

    private void showSettings() {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), dp(8), dp(20), 0);
        EditText endpoint = new EditText(this);
        endpoint.setHint("https://PC名.tailnet.ts.net");
        endpoint.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        endpoint.setText(secureStore.getBaseUrl());
        form.addView(label("接続先URL"));
        form.addView(endpoint);
        EditText token = new EditText(this);
        token.setHint("Bearerトークン");
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(secureStore.getToken());
        form.addView(label("認証トークン"));
        form.addView(token);
        TextView note = text("HTTPはUSBテスト用localhostまたはTailscale IPだけ許可されます。外出時はTailscale HTTPSを推奨します。", 12, 0xFF5B6B64);
        note.setPadding(0, dp(12), 0, 0);
        form.addView(note);

        AlertDialog dialog = new AlertDialog.Builder(this)
            .setTitle("安全な接続設定")
            .setView(form)
            .setNeutralButton("USBでペアリング", null)
            .setNegativeButton("キャンセル", null)
            .setPositiveButton("保存", null)
            .create();
        dialog.setOnShowListener(ignored -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
                try {
                    String normalized = GlmApi.normalizeBaseUrl(endpoint.getText().toString());
                    String enteredToken = token.getText().toString().trim();
                    if (enteredToken.length() < 32) throw new IllegalArgumentException("認証トークンが短すぎます");
                    secureStore.save(normalized, enteredToken);
                    dialog.dismiss();
                    refreshStatus();
                } catch (IllegalArgumentException | GeneralSecurityException error) {
                    Toast.makeText(this, error.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(view -> {
                String localUrl = "http://127.0.0.1:8765";
                endpoint.setText(localUrl);
                api.pairLocal(localUrl, new GlmApi.Callback<String>() {
                    @Override public void success(String pairedToken) {
                        runOnUiThread(() -> {
                            try {
                                secureStore.save(localUrl, pairedToken);
                                token.setText(pairedToken);
                                dialog.dismiss();
                                Toast.makeText(MainActivity.this, "USBペアリングが完了しました", Toast.LENGTH_SHORT).show();
                                refreshStatus();
                            } catch (GeneralSecurityException error) {
                                Toast.makeText(MainActivity.this, error.getMessage(), Toast.LENGTH_LONG).show();
                            }
                        });
                    }
                    @Override public void failure(String message) {
                        runOnUiThread(() -> Toast.makeText(MainActivity.this, "USBペアリング失敗: " + message, Toast.LENGTH_LONG).show());
                    }
                });
            });
        });
        dialog.show();
    }

    private void refreshStatus() {
        if (!secureStore.hasConfiguration()) return;
        setBusy(true);
        api.getStatus(secureStore.getBaseUrl(), secureStore.getToken(), new GlmApi.Callback<JSONObject>() {
            @Override public void success(JSONObject json) {
                runOnUiThread(() -> {
                    setBusy(false);
                    connectionLabel.setText("接続中  |  GLM Core");
                    connectionLabel.setTextColor(GREEN);
                    String temperature = json.isNull("gpu_temp") ? "--" : json.optString("gpu_temp") + " C";
                    metricsLabel.setText("GPU " + json.optString("gpu_util", "--") + "%  |  " + temperature
                        + "  |  VRAM " + json.optString("vram_used_gb", "--") + " GB");
                });
            }
            @Override public void failure(String message) {
                runOnUiThread(() -> {
                    setBusy(false);
                    connectionLabel.setText("接続できません");
                    connectionLabel.setTextColor(DANGER);
                    metricsLabel.setText(message);
                });
            }
        });
    }

    private void sendMessage() {
        String content = prompt.getText().toString().trim();
        if (content.isEmpty() || !secureStore.hasConfiguration()) {
            if (!secureStore.hasConfiguration()) showSettings();
            return;
        }
        prompt.setText("");
        transcript.addView(message(content, true));
        setBusy(true);
        api.chat(secureStore.getBaseUrl(), secureStore.getToken(), content, new GlmApi.Callback<String>() {
            @Override public void success(String answer) {
                runOnUiThread(() -> {
                    setBusy(false);
                    transcript.addView(message(answer, false));
                    scrollToBottom();
                });
            }
            @Override public void failure(String message) {
                runOnUiThread(() -> {
                    setBusy(false);
                    transcript.addView(message("エラー: " + message, false));
                    scrollToBottom();
                });
            }
        });
        scrollToBottom();
    }

    private void confirmKill() {
        new AlertDialog.Builder(this)
            .setTitle("GLMを緊急停止しますか？")
            .setMessage("実行中のAI処理とバックエンドを停止します。この操作は取り消せません。")
            .setNegativeButton("キャンセル", null)
            .setPositiveButton("生体認証して停止", (dialog, which) -> authenticate("緊急停止を承認", this::executeKill, null))
            .show();
    }

    private void executeKill() {
        setBusy(true);
        api.kill(secureStore.getBaseUrl(), secureStore.getToken(), new GlmApi.Callback<String>() {
            @Override public void success(String value) {
                runOnUiThread(() -> {
                    setBusy(false);
                    connectionLabel.setText("緊急停止を送信しました");
                    connectionLabel.setTextColor(DANGER);
                });
            }
            @Override public void failure(String message) {
                runOnUiThread(() -> {
                    setBusy(false);
                    Toast.makeText(MainActivity.this, message, Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void authenticate(String title, Runnable success, Runnable cancelled) {
        Executor executor = getMainExecutor();
        BiometricPrompt biometricPrompt = new BiometricPrompt.Builder(this)
            .setTitle(title)
            .setSubtitle("端末の本人確認を使用します")
            .setNegativeButton("キャンセル", executor, (dialog, which) -> {
                if (cancelled != null) cancelled.run();
            })
            .build();
        biometricPrompt.authenticate(new CancellationSignal(), executor, new BiometricPrompt.AuthenticationCallback() {
            @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                success.run();
            }
            @Override public void onAuthenticationError(int errorCode, CharSequence errorMessage) {
                if (cancelled != null) cancelled.run();
            }
        });
    }

    private void setBusy(boolean busy) {
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
        sendButton.setEnabled(!busy);
    }

    private View message(String content, boolean user) {
        FrameLayout row = new FrameLayout(this);
        row.setPadding(user ? dp(52) : 0, dp(5), user ? 0 : dp(52), dp(5));
        TextView bubble = text(content, 15, user ? 0xFFFFFFFF : INK);
        bubble.setTextIsSelectable(true);
        bubble.setPadding(dp(14), dp(11), dp(14), dp(11));
        bubble.setBackground(shape(user ? GREEN : 0xFFFFFFFF, user ? GREEN : 0xFFD6DEDA, 1, 8));
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.gravity = user ? Gravity.END : Gravity.START;
        row.addView(bubble, params);
        return row;
    }

    private void scrollToBottom() {
        transcriptScroll.post(() -> transcriptScroll.fullScroll(View.FOCUS_DOWN));
    }

    private LinearLayout horizontal(int horizontalPadding, int verticalPadding) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setPadding(dp(horizontalPadding), dp(verticalPadding), dp(horizontalPadding), dp(verticalPadding));
        return layout;
    }

    private TextView label(String value) {
        TextView label = text(value, 13, INK);
        label.setPadding(0, dp(12), 0, 0);
        return label;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.12f);
        return view;
    }

    private Button button(String value, int background, int foreground) {
        Button button = new Button(this);
        button.setText(value);
        button.setTextColor(foreground);
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setBackground(shape(background, background, 0, 6));
        return button;
    }

    private android.graphics.drawable.GradientDrawable shape(int fill, int stroke, int strokeWidth, int radius) {
        android.graphics.drawable.GradientDrawable drawable = new android.graphics.drawable.GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radius));
        if (strokeWidth > 0) drawable.setStroke(dp(strokeWidth), stroke);
        return drawable;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}