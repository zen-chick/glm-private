#!/usr/bin/env python3
"""GLM Router の安全基盤。Python標準ライブラリのみを使用する。"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets as secrets_module
import socketserver
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
from typing import Any, Optional

DEFAULT_MAX_CONCURRENT_REQUESTS = 16


GLM_DIR = Path.home() / ".glm"
AUDIT_DIR = GLM_DIR / "audit"
AUDIT_DB = AUDIT_DIR / "events.sqlite3"
SECRETS_DIR = GLM_DIR / "secrets"
AUTH_FILE = GLM_DIR / "auth_token"
HEARTBEAT_FILE = GLM_DIR / "router.heartbeat.json"
STOP_FILE = GLM_DIR / "STOP"
LOCK_FILE = GLM_DIR / "EMERGENCY_LOCK"
PROTECTED_PATHS = {STOP_FILE.resolve(), LOCK_FILE.resolve(), AUTH_FILE.resolve(), AUDIT_DB.resolve()}

# リクエスト本文・応答出力の既定上限（DoS/暴走防止）
MAX_REQUEST_BODY_BYTES = 2_000_000
MAX_RESPONSE_CHARS = 200_000
MAX_STREAM_SECONDS = 300
DEFAULT_MAX_CONCURRENT_SANDBOX = 2

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{16,})"),
    re.compile(r"(gh[po]_[A-Za-z0-9]{20,})"),
    re.compile(r"(xox[baprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9._-]{10,})", re.IGNORECASE),
    re.compile(r'((?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*)([^\s,"\']{4,})', re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """監査ログ・表示用テキストからAPIキー等の機密文字列をマスキングする。"""
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 2:
            redacted = pattern.sub(lambda m: m.group(1) + "***REDACTED***", redacted)
        else:
            redacted = pattern.sub("***REDACTED***", redacted)
    return redacted


def redact_structure(value: Any) -> Any:
    """dict/list/strを再帰的に走査し、機密情報をマスキングする。"""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: redact_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    return value


def ensure_auth_token(auth_file: Path = AUTH_FILE) -> str:
    """認証トークンを読み込む。存在しなければ安全に生成する（フェイルクローズ設計）。"""
    auth_file = Path(auth_file)
    try:
        if auth_file.exists() and not auth_file.is_symlink():
            token = auth_file.read_text(encoding="utf-8-sig").strip()
            if token:
                return token
        token = secrets_module.token_urlsafe(32)
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(auth_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(token)
        return token
    except OSError as error:
        raise RuntimeError(f"Failed to establish an authentication token: {error}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BoundedThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """並列リクエストを受け付けつつ、同時実行数に上限を設けて無限スレッド生成を防ぐ。"""

    daemon_threads = True

    def __init__(self, *args, max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS, **kwargs):
        super().__init__(*args, **kwargs)
        self._concurrency_semaphore = threading.Semaphore(max_concurrent_requests)

    def process_request_thread(self, request, client_address):
        with self._concurrency_semaphore:
            super().process_request_thread(request, client_address)


class SecretStore:
    """名前を検証してプロジェクト外の秘密情報を読み取る。"""

    def __init__(self, directory: Path = SECRETS_DIR):
        self.directory = Path(directory)

    def get(self, name: str) -> Optional[str]:
        if not name or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in name):
            raise ValueError("Secret name must contain only letters, digits, underscores, and hyphens.")
        path = self.directory / name
        try:
            value = path.read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            return None
        return value or None

    def set(self, name: str, value: str) -> None:
        if not name or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in name):
            raise ValueError("Secret name must contain only letters, digits, underscores, and hyphens.")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / name
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)


# ══════════════════════════════════════════════════════════════════════════════
# TOTP（RFC 6238, Google Authenticator互換）— 管理者向け監査画面の二段階認証に使用
# ══════════════════════════════════════════════════════════════════════════════
ADMIN_TOTP_SECRET_NAME = "admin_totp_secret"


def generate_totp_secret() -> str:
    """Base32のTOTP共有シークレットを新規生成する（Google Authenticatorに登録可能）。"""
    return base64.b32encode(secrets_module.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_at(secret: str, counter: int, digits: int = 6) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded.upper())
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code_int).zfill(digits)


def totp_now(secret: str, step: int = 30, digits: int = 6) -> str:
    return _totp_at(secret, int(time.time()) // step, digits)


def verify_totp(secret: str, code: str, step: int = 30, digits: int = 6, valid_window: int = 1) -> bool:
    """入力されたTOTPコードを検証する。時計ずれを許容するため前後1ステップも確認する。"""
    if not secret or not code or not code.isdigit():
        return False
    counter = int(time.time()) // step
    return any(
        hmac.compare_digest(_totp_at(secret, counter + offset, digits), code)
        for offset in range(-valid_window, valid_window + 1)
    )


def provisioning_uri(secret: str, account_name: str = "glm-admin", issuer: str = "GLM") -> str:
    """Google Authenticator等でQRコード登録するためのotpauth URIを生成する。"""
    return f"otpauth://totp/{issuer}:{account_name}?secret={secret}&issuer={issuer}&digits=6&period=30"


class AuditLogger:
    """ルーターの判断をSQLiteへ記録する。"""

    def __init__(self, database: Path = AUDIT_DB):
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    session_id TEXT,
                    detail_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL DEFAULT '',
                    record_hash TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS audit_events_timestamp "
                "ON audit_events(timestamp_utc)"
            )
            # 既存DBの互換性維持: 列がなければ追加する（ハッシュチェーン導入前のDB対応）
            existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
            if "prev_hash" not in existing_columns:
                connection.execute("ALTER TABLE audit_events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''")
            if "record_hash" not in existing_columns:
                connection.execute("ALTER TABLE audit_events ADD COLUMN record_hash TEXT NOT NULL DEFAULT ''")
            connection.commit()
        finally:
            connection.close()

    def _last_hash(self, connection) -> str:
        row = connection.execute(
            "SELECT record_hash FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row and row[0] else "0" * 64

    @staticmethod
    def _compute_hash(prev_hash: str, timestamp_utc: str, event_type: str, decision: str,
                       session_id: Optional[str], detail_json: str) -> str:
        material = "|".join([prev_hash, timestamp_utc, event_type, decision, session_id or "", detail_json])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def record(
        self,
        event_type: str,
        decision: str,
        session_id: Optional[str] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = json.dumps(redact_structure(detail or {}), ensure_ascii=False, sort_keys=True)
        timestamp = utc_now()
        connection = sqlite3.connect(self.database)
        try:
            prev_hash = self._last_hash(connection)
            record_hash = self._compute_hash(prev_hash, timestamp, event_type, decision, session_id, payload)
            connection.execute(
                "INSERT INTO audit_events "
                "(timestamp_utc, event_type, decision, session_id, detail_json, prev_hash, record_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (timestamp, event_type, decision, session_id, payload, prev_hash, record_hash),
            )
            connection.commit()
        finally:
            connection.close()

    def verify_integrity(self) -> dict:
        """ハッシュチェーンを検証し、改ざんがないか確認する。

        ハッシュチェーン導入前に作成された既存レコード（record_hashが空）は検証対象外とし、
        チェーンが実際に開始された最初のレコードから先を検証する。
        """
        connection = sqlite3.connect(self.database)
        try:
            rows = connection.execute(
                "SELECT id, timestamp_utc, event_type, decision, session_id, detail_json, prev_hash, record_hash "
                "FROM audit_events ORDER BY id ASC"
            ).fetchall()
        finally:
            connection.close()
        legacy_unverifiable = 0
        expected_prev = "0" * 64
        for row in rows:
            record_id, timestamp_utc, event_type, decision, session_id, detail_json, prev_hash, record_hash = row
            if not record_hash:
                legacy_unverifiable += 1
                continue
            if prev_hash != expected_prev:
                return {"ok": False, "broken_at_id": record_id, "reason": "prev_hash_mismatch",
                        "legacy_unverifiable_records": legacy_unverifiable}
            expected_hash = self._compute_hash(prev_hash, timestamp_utc, event_type, decision, session_id, detail_json)
            if expected_hash != record_hash:
                return {"ok": False, "broken_at_id": record_id, "reason": "record_hash_mismatch",
                        "legacy_unverifiable_records": legacy_unverifiable}
            expected_prev = record_hash
        return {"ok": True, "broken_at_id": None, "reason": None,
                "records_checked": len(rows) - legacy_unverifiable,
                "legacy_unverifiable_records": legacy_unverifiable}

    def count_since(self, epoch_seconds: float, event_type: str = "request") -> int:
        timestamp = datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat()
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type = ? AND timestamp_utc >= ?",
                (event_type, timestamp),
            ).fetchone()
        finally:
            connection.close()
        return int(row[0])

    def purge_older_than(self, days: int) -> int:
        """指定日数より古い監査ログを削除し、削除件数を返す（プライバシー保持期限の実装）。"""
        cutoff = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()
        connection = sqlite3.connect(self.database)
        try:
            cursor = connection.execute("DELETE FROM audit_events WHERE timestamp_utc < ?", (cutoff,))
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def purge_all(self) -> int:
        """監査ログを全件削除する（ワンクリック削除）。"""
        connection = sqlite3.connect(self.database)
        try:
            cursor = connection.execute("DELETE FROM audit_events")
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()


class WorkspaceGuard:
    """エージェントが明示されたワークスペース外や安全保護パスへ到達するのを防ぐ。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def contains(self, target: str | Path) -> bool:
        try:
            resolved = Path(target).expanduser().resolve()
            if resolved in PROTECTED_PATHS:
                return False
            resolved.relative_to(self.workspace)
            return True
        except ValueError:
            return False

    def require_contained(self, target: str | Path) -> Path:
        original = Path(target).expanduser()
        if original.is_symlink():
            # シンボリックリンク差し替え攻撃対策: リンクそのものへの直接操作を拒否する
            raise PermissionError(f"シンボリックリンクへのアクセスは拒否されました: {original}")
        resolved = original.resolve()
        if resolved in PROTECTED_PATHS:
            raise PermissionError(f"安全保護システムファイルへのアクセスは拒否されました: {resolved}")
        if not self.contains(resolved):
            raise PermissionError(f"Workspace外へのアクセスは拒否されました: {resolved}")
        return resolved


def safe_extract_zip(zip_path: Path, destination: Path) -> list[str]:
    """Zip Slip対策: 展開先ディレクトリ外へ書き込むメンバーを含むzipは全体を拒否する。"""
    import zipfile
    destination = Path(destination).resolve()
    with zipfile.ZipFile(zip_path) as archive:
        extracted = []
        for member in archive.infolist():
            member_path = (destination / member.filename).resolve()
            try:
                member_path.relative_to(destination)
            except ValueError:
                raise PermissionError(f"Zip Slipの疑いがあるため展開を拒否しました: {member.filename}")
            extracted.append(member.filename)
        archive.extractall(destination)
    return extracted


def write_heartbeat(process_id: int, status: str = "running") -> None:
    GLM_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = HEARTBEAT_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(
            {"pid": process_id, "status": status, "timestamp_utc": utc_now()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temp_file.replace(HEARTBEAT_FILE)


def request_stop(reason: str) -> None:
    GLM_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text(
        json.dumps({"reason": reason, "timestamp_utc": utc_now()}, ensure_ascii=False),
        encoding="utf-8",
    )


def stop_process_tree(process_id: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"], check=False)
    else:
        os.kill(process_id, 9)


def process_is_running(process_id: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, process_id)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except (AttributeError, OSError):
            return False
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def process_start_time(process_id: int) -> Optional[float]:
    """PID再利用対策: プロセス開始時刻を取得し、同一プロセスかどうかの照合に使う。"""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(0x1000, False, process_id)
            if not handle:
                return None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time),
            )
            kernel32.CloseHandle(handle)
            if not ok:
                return None
            return (creation.dwHighDateTime << 32) + creation.dwLowDateTime
        except (AttributeError, OSError):
            return None
    try:
        return os.stat(f"/proc/{process_id}").st_ctime
    except OSError:
        return None


def emergency_kill(reason: str = "emergency_user_override") -> None:
    """全プロセスを強制シャットダウンし非常用ロックファイルを生成する。"""
    GLM_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(
        json.dumps({"reason": reason, "timestamp_utc": utc_now()}, ensure_ascii=False),
        encoding="utf-8",
    )
    request_stop(reason)
    stop_process_tree(os.getpid())


def evaluate_stop_reason(
    process_id: int,
    target_start_time: Optional[float],
    parent_process_id: Optional[int],
    max_watch_seconds: Optional[int],
    started_at: float,
    heartbeat_timeout: int,
    audit: "AuditLogger",
    max_requests_per_minute: int,
    max_heals_per_minute: int = 5,
    now: Optional[float] = None,
) -> Optional[str]:
    """1回分の障害検出判定をwatch()から分離した純粋関数。障害復旧テストで直接呼び出せる。"""
    now = time.monotonic() if now is None else now
    if not process_is_running(process_id):
        return "process_exited"
    current_start_time = process_start_time(process_id)
    if target_start_time is not None and current_start_time is not None and current_start_time != target_start_time:
        return "process_exited"
    if parent_process_id is not None and not process_is_running(parent_process_id):
        return "parent_process_exited"
    if max_watch_seconds is not None and now - started_at > max_watch_seconds:
        return "max_watch_duration_exceeded"
    if LOCK_FILE.exists():
        return "emergency_lock_active"
    if STOP_FILE.exists():
        return "explicit_stop"
    if not HEARTBEAT_FILE.exists():
        return "heartbeat_missing"
    age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    if age > heartbeat_timeout:
        return "heartbeat_timeout"
    if audit.count_since(time.time() - 60, "request") > max_requests_per_minute:
        return "request_rate_limit_exceeded"
    if audit.count_since(time.time() - 60, "healed_error") > max_heals_per_minute:
        return "self_healing_loop_detected"
    return None


def watch(
    process_id: int,
    heartbeat_timeout: int,
    max_requests_per_minute: int,
    database: Path = AUDIT_DB,
    max_watch_seconds: Optional[int] = None,
    parent_process_id: Optional[int] = None,
) -> int:
    """停止指示・心拍断・異常頻度・自己修復無限ループ・親プロセス消失を検出したら即時プロセス停止する。"""
    audit = AuditLogger(database)
    started_at = time.monotonic()
    target_start_time = process_start_time(process_id)

    while True:
        reason = evaluate_stop_reason(
            process_id, target_start_time, parent_process_id, max_watch_seconds,
            started_at, heartbeat_timeout, audit, max_requests_per_minute,
        )
        if reason == "process_exited":
            return 0
        if reason == "self_healing_loop_detected":
            LOCK_FILE.write_text(
                json.dumps({"reason": reason, "timestamp_utc": utc_now()}, ensure_ascii=False),
                encoding="utf-8",
            )
        if reason:
            audit.record("circuit_breaker", "stop", detail={"reason": reason, "pid": process_id})
            stop_process_tree(process_id)
            return 1
        time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="GLM security watchdog")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--heartbeat-timeout", type=int, default=45)
    parser.add_argument("--max-requests-per-minute", type=int, default=120)
    parser.add_argument("--max-watch-seconds", type=int, default=None)
    args = parser.parse_args()
    if not args.watch or not args.pid:
        parser.error("--watch と --pid が必要です")
    sys.exit(watch(args.pid, args.heartbeat_timeout, args.max_requests_per_minute,
                    max_watch_seconds=args.max_watch_seconds, parent_process_id=args.parent_pid))


if __name__ == "__main__":
    main()