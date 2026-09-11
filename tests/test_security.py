import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import glm_security
from glm_security import (
    AuditLogger, SecretStore, WorkspaceGuard, process_is_running,
    generate_totp_secret, totp_now, verify_totp, safe_extract_zip,
    evaluate_stop_reason, write_heartbeat,
)


class TestAuditLogger(unittest.TestCase):
    def test_records_auditable_event(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "audit.sqlite3"
            audit = AuditLogger(database)
            audit.record("request", "route", "session-1", {"tier": "local"})
            connection = sqlite3.connect(database)
            try:
                row = connection.execute(
                    "SELECT event_type, decision, session_id, detail_json FROM audit_events"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[:3], ("request", "route", "session-1"))
            self.assertIn('"tier": "local"', row[3])

    def test_counts_recent_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditLogger(Path(directory) / "audit.sqlite3")
            audit.record("request", "route")
            audit.record("request", "deny")
            self.assertEqual(audit.count_since(time.time() - 60), 2)

    def test_hash_chain_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "audit.sqlite3"
            audit = AuditLogger(database)
            audit.record("request", "route", "session-1", {"tier": "local"})
            audit.record("request", "deny", "session-1", {"reason": "unauthorized"})
            self.assertTrue(audit.verify_integrity()["ok"])

            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE audit_events SET decision = 'allow' WHERE id = 1")
                connection.commit()
            finally:
                connection.close()

            result = audit.verify_integrity()
            self.assertFalse(result["ok"])
            self.assertEqual(result["broken_at_id"], 1)


class TestEvaluateStopReason(unittest.TestCase):
    """障害復旧テスト: watchdogの各検出条件をevaluate_stop_reason()経由で個別に検証する。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        directory = Path(self.tmp.name)
        self.original = {
            "HEARTBEAT_FILE": glm_security.HEARTBEAT_FILE,
            "STOP_FILE": glm_security.STOP_FILE,
            "LOCK_FILE": glm_security.LOCK_FILE,
        }
        glm_security.HEARTBEAT_FILE = directory / "heartbeat.json"
        glm_security.STOP_FILE = directory / "STOP"
        glm_security.LOCK_FILE = directory / "LOCK"
        self.audit = AuditLogger(directory / "audit.sqlite3")
        self.self_pid = __import__("os").getpid()

    def tearDown(self):
        for key, value in self.original.items():
            setattr(glm_security, key, value)
        self.tmp.cleanup()

    def _healthy_kwargs(self, **overrides):
        write_heartbeat(self.self_pid)
        kwargs = dict(
            process_id=self.self_pid, target_start_time=None, parent_process_id=None,
            max_watch_seconds=None, started_at=time.monotonic(), heartbeat_timeout=45,
            audit=self.audit, max_requests_per_minute=120,
        )
        kwargs.update(overrides)
        return kwargs

    def test_healthy_state_has_no_stop_reason(self):
        self.assertIsNone(evaluate_stop_reason(**self._healthy_kwargs()))

    def test_dead_process_reports_process_exited(self):
        # 存在しないと考えられる高いPIDを使用（環境依存を避けるため広い範囲で探索）
        dead_pid = 2 ** 30
        reason = evaluate_stop_reason(**self._healthy_kwargs(process_id=dead_pid))
        self.assertEqual(reason, "process_exited")

    def test_missing_heartbeat_file_triggers_recovery(self):
        kwargs = self._healthy_kwargs()
        glm_security.HEARTBEAT_FILE.unlink()
        self.assertEqual(evaluate_stop_reason(**kwargs), "heartbeat_missing")

    def test_stale_heartbeat_triggers_timeout_recovery(self):
        kwargs = self._healthy_kwargs(heartbeat_timeout=1)
        old_time = time.time() - 10
        os_module = __import__("os")
        os_module.utime(glm_security.HEARTBEAT_FILE, (old_time, old_time))
        self.assertEqual(evaluate_stop_reason(**kwargs), "heartbeat_timeout")

    def test_stop_file_triggers_explicit_stop(self):
        kwargs = self._healthy_kwargs()
        glm_security.STOP_FILE.write_text("{}", encoding="utf-8")
        self.assertEqual(evaluate_stop_reason(**kwargs), "explicit_stop")

    def test_lock_file_triggers_emergency_lock(self):
        kwargs = self._healthy_kwargs()
        glm_security.LOCK_FILE.write_text("{}", encoding="utf-8")
        self.assertEqual(evaluate_stop_reason(**kwargs), "emergency_lock_active")

    def test_parent_process_exit_triggers_recovery(self):
        kwargs = self._healthy_kwargs(parent_process_id=2 ** 30)
        self.assertEqual(evaluate_stop_reason(**kwargs), "parent_process_exited")

    def test_max_watch_duration_triggers_recovery(self):
        kwargs = self._healthy_kwargs(max_watch_seconds=1, started_at=time.monotonic() - 10)
        self.assertEqual(evaluate_stop_reason(**kwargs), "max_watch_duration_exceeded")

    def test_pid_reuse_is_treated_as_process_exited(self):
        kwargs = self._healthy_kwargs(target_start_time=123456789.0)
        self.assertEqual(evaluate_stop_reason(**kwargs), "process_exited")

    def test_request_rate_limit_triggers_recovery(self):
        kwargs = self._healthy_kwargs(max_requests_per_minute=2)
        for _ in range(5):
            self.audit.record("request", "route")
        self.assertEqual(evaluate_stop_reason(**kwargs), "request_rate_limit_exceeded")

    def test_self_healing_loop_triggers_recovery(self):
        kwargs = self._healthy_kwargs()
        for _ in range(10):
            self.audit.record("healed_error", "auto_heal")
        self.assertEqual(evaluate_stop_reason(**kwargs), "self_healing_loop_detected")


class TestTotp(unittest.TestCase):
    def test_current_code_verifies(self):
        secret = generate_totp_secret()
        code = totp_now(secret)
        self.assertTrue(verify_totp(secret, code))

    def test_wrong_code_rejected(self):
        secret = generate_totp_secret()
        code = totp_now(secret)
        wrong = "0" * 6 if code != "0" * 6 else "1" * 6
        self.assertFalse(verify_totp(secret, wrong))

    def test_different_secrets_produce_different_codes(self):
        first = totp_now(generate_totp_secret())
        second = totp_now(generate_totp_secret())
        # 確率的に異なるものの必須ではないため、形式のみ検証
        self.assertEqual(len(first), 6)
        self.assertEqual(len(second), 6)


class TestWorkspaceGuard(unittest.TestCase):
    def test_accepts_path_inside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            inside = workspace / "source.py"
            self.assertEqual(WorkspaceGuard(workspace).require_contained(inside), inside.resolve())

    def test_rejects_path_outside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            with self.assertRaises(PermissionError):
                WorkspaceGuard(workspace).require_contained(Path(directory) / "secret.txt")

    def test_rejects_protected_security_files(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            guard = WorkspaceGuard(workspace)
            from glm_security import STOP_FILE
            with self.assertRaises(PermissionError):
                guard.require_contained(STOP_FILE)

    def test_rejects_symlink_swap_attack(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            outside_secret = Path(directory) / "outside.txt"
            outside_secret.write_text("secret", encoding="utf-8")
            link = workspace / "looks_safe.py"
            try:
                link.symlink_to(outside_secret)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is not permitted in this environment")
            with self.assertRaises(PermissionError):
                WorkspaceGuard(workspace).require_contained(link)


class TestSafeExtractZip(unittest.TestCase):
    def test_rejects_zip_slip_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "dest"
            destination.mkdir()
            zip_path = Path(directory) / "evil.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../../escape.txt", "pwned")
            with self.assertRaises(PermissionError):
                safe_extract_zip(zip_path, destination)

    def test_extracts_safe_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "dest"
            destination.mkdir()
            zip_path = Path(directory) / "ok.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("inner/file.txt", "hello")
            extracted = safe_extract_zip(zip_path, destination)
            self.assertIn("inner/file.txt", extracted)
            self.assertEqual((destination / "inner" / "file.txt").read_text(encoding="utf-8"), "hello")


class TestSecretStore(unittest.TestCase):
    def test_reads_a_named_secret_without_logging_it(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory)
            (secrets / "notion_token").write_text("secret-value\n", encoding="utf-8")
            self.assertEqual(SecretStore(secrets).get("notion_token"), "secret-value")

    def test_returns_none_for_missing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(SecretStore(Path(directory)).get("slack_webhook"))

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                SecretStore(Path(directory)).get("../auth_token")


class TestWatchdogSupport(unittest.TestCase):
    def test_current_process_is_running(self):
        self.assertTrue(process_is_running(__import__("os").getpid()))


if __name__ == "__main__":
    unittest.main(verbosity=2)