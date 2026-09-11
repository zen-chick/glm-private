package com.glm.remote;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class GlmApi {
    interface Callback<T> {
        void success(T value);
        void failure(String message);
    }

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    void pairLocal(String baseUrl, Callback<String> callback) {
        executor.execute(() -> {
            try {
                String normalized = normalizeBaseUrl(baseUrl);
                URI uri = new URI(normalized);
                if (!isLoopback(uri.getHost())) throw new IllegalArgumentException("USBペアリングはlocalhost接続だけ使用できます");
                JSONObject result = new JSONObject(request(normalized, "/api/auth/local-token", "GET", "", null));
                String token = result.optString("token", "");
                if (token.length() < 32) throw new IOException("Coreから有効な認証情報を取得できませんでした");
                callback.success(token);
            } catch (Exception error) {
                callback.failure(safeMessage(error));
            }
        });
    }

    void getStatus(String baseUrl, String token, Callback<JSONObject> callback) {
        executor.execute(() -> {
            try {
                callback.success(new JSONObject(request(baseUrl, "/api/status", "GET", token, null)));
            } catch (Exception error) {
                callback.failure(safeMessage(error));
            }
        });
    }

    void chat(String baseUrl, String token, String content, Callback<String> callback) {
        executor.execute(() -> {
            try {
                JSONObject body = new JSONObject();
                JSONArray messages = new JSONArray();
                messages.put(new JSONObject().put("role", "user").put("content", content));
                body.put("messages", messages).put("stream", false);
                JSONObject result = new JSONObject(request(baseUrl, "/v1/chat/completions", "POST", token, body.toString()));
                String answer = result.getJSONArray("choices").getJSONObject(0)
                    .getJSONObject("message").optString("content", "");
                callback.success(answer.isEmpty() ? "応答が空でした。" : answer);
            } catch (Exception error) {
                callback.failure(safeMessage(error));
            }
        });
    }

    void kill(String baseUrl, String token, Callback<String> callback) {
        executor.execute(() -> {
            try {
                request(baseUrl, "/api/kill", "POST", token, "{}");
                callback.success("ok");
            } catch (Exception error) {
                callback.failure(safeMessage(error));
            }
        });
    }

    static String normalizeBaseUrl(String raw) {
        String value = raw == null ? "" : raw.trim();
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (scheme == null || host == null || uri.getUserInfo() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException("正しい接続先URLを入力してください");
            }
            if ("https".equalsIgnoreCase(scheme)) return value;
            if (!"http".equalsIgnoreCase(scheme)) throw new IllegalArgumentException("HTTPまたはHTTPSだけ使用できます");
            if (isLoopback(host) || isTailscaleIpv4(host)) return value;
            throw new IllegalArgumentException("暗号化されていないHTTPはlocalhostまたはTailscale IPだけ使用できます");
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("正しい接続先URLを入力してください");
        }
    }

    private static boolean isLoopback(String host) {
        return "127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host) || "::1".equals(host);
    }

    private static boolean isTailscaleIpv4(String host) {
        String[] parts = host.split("\\.");
        if (parts.length != 4) return false;
        try {
            int first = Integer.parseInt(parts[0]);
            int second = Integer.parseInt(parts[1]);
            return first == 100 && second >= 64 && second <= 127;
        } catch (NumberFormatException error) {
            return false;
        }
    }

    private String request(String baseUrl, String path, String method, String token, String body) throws IOException, JSONException {
        String normalized = normalizeBaseUrl(baseUrl);
        HttpURLConnection connection = (HttpURLConnection) new URL(normalized + path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(8_000);
        connection.setReadTimeout(130_000);
        connection.setRequestProperty("Accept", "application/json");
        if (token != null && !token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("User-Agent", "GLM-Remote-Android/1.0");
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
        }
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        String response = readLimited(stream, 1_000_000);
        connection.disconnect();
        if (code < 200 || code >= 300) {
            String detail = response;
            try { detail = new JSONObject(response).optString("error", response); } catch (JSONException ignored) {}
            throw new IOException("HTTP " + code + ": " + detail);
        }
        return response;
    }

    private static String readLimited(InputStream stream, int limit) throws IOException {
        if (stream == null) return "";
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            char[] buffer = new char[4096];
            int count;
            while ((count = reader.read(buffer)) >= 0) {
                if (result.length() + count > limit) throw new IOException("サーバー応答が大きすぎます");
                result.append(buffer, 0, count);
            }
        }
        return result.toString();
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.isEmpty() ? error.getClass().getSimpleName() : message;
    }
}