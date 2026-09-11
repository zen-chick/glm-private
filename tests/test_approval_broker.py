import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_approval_broker import ApprovalBroker, create_server, load_token


class TestApprovalBroker(unittest.TestCase):
    def setUp(self):
        self.broker = ApprovalBroker(token="test-token")
        self.request = {"type": "approval_request", "id": "request-1", "tool": "Write", "params": {"path": "a.txt"}}

    def test_publishes_and_lists_pending_request(self):
        self.broker.publish(self.request)
        self.assertEqual(self.broker.pending(), [self.request])

    def test_accepts_a_single_valid_response(self):
        self.broker.publish(self.request)
        self.assertTrue(self.broker.respond("request-1", True))
        self.assertTrue(self.broker.decision("request-1"))
        self.assertFalse(self.broker.respond("request-1", True))

    def test_rejects_unknown_or_invalid_response(self):
        self.assertFalse(self.broker.respond("missing", True))
        self.broker.publish(self.request)
        self.assertFalse(self.broker.respond("request-1", "always"))

    def test_returns_none_for_missing_decision(self):
        self.assertIsNone(self.broker.decision("missing"))

    def test_loads_existing_shared_token(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory) / "auth_token"
            path.write_text("token-value\n", encoding="utf-8")
            self.assertEqual(load_token(path), "token-value")


class TestApprovalRequestSchema(unittest.TestCase):
    """B-3: /request の必須フィールド（reasonは常時、高リスクはtarget/scope/expiresも必須）を検証する。"""

    def setUp(self):
        self.broker = ApprovalBroker(token="test-token")
        self.server = create_server(self.broker, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method="POST",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_low_risk_request_requires_only_reason(self):
        status, body = self._post("/request", {
            "id": "req-low", "tool": "Read", "params": {"path": "a.txt"}, "reason": "参照のため",
        })
        self.assertEqual(status, 202)
        self.assertTrue(body["accepted"])

    def test_missing_reason_is_rejected(self):
        status, body = self._post("/request", {"id": "req-noreason", "tool": "Read", "params": {}})
        self.assertEqual(status, 400)
        self.assertIn("reason", body["error"])

    def test_high_risk_without_full_schema_is_rejected(self):
        status, body = self._post("/request", {
            "id": "req-highrisk", "tool": "git_push", "params": {"remote": "origin"}, "reason": "反映のため",
        })
        self.assertEqual(status, 400)
        self.assertIn("git_push", body["error"])

    def test_high_risk_missing_requested_by_is_rejected(self):
        status, body = self._post("/request", {
            "id": "req-highrisk-norequester", "tool": "git_push", "params": {"remote": "origin"},
            "reason": "反映のため", "target": "origin/main", "scope": "リポジトリ全体", "expires_in_minutes": 15,
        })
        self.assertEqual(status, 400)
        self.assertIn("requested_by", body["error"])

    def test_high_risk_with_full_schema_is_accepted(self):
        status, body = self._post("/request", {
            "id": "req-highrisk-ok", "tool": "git_push", "params": {"remote": "origin"},
            "reason": "反映のため", "target": "origin/main", "scope": "リポジトリ全体", "expires_in_minutes": 15,
            "requested_by": "session-42",
        })
        self.assertEqual(status, 202)
        pending = self.broker.pending()
        self.assertEqual(pending[0]["risk_category"], "git_push")
        self.assertEqual(pending[0]["target"], "origin/main")
        self.assertEqual(pending[0]["requested_by"], "session-42")


if __name__ == "__main__":
    unittest.main(verbosity=2)