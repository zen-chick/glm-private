import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_approval_broker import ApprovalBroker
from glm_covibe_adapter import CoVibeAdapter, GLMApprovalProvider, HeadlessTUI
from glm_security import AuditLogger


class TestCoVibeAdapter(unittest.TestCase):
    def test_source_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoVibeAdapter(
                directory,
                ApprovalBroker(token="test"),
                AuditLogger(Path(directory) / "audit.sqlite3"),
            )
            self.assertTrue(adapter.available())

    def test_co_vibe_runtime_loads_and_registers_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoVibeAdapter(
                directory,
                ApprovalBroker(token="test"),
                AuditLogger(Path(directory) / "audit.sqlite3"),
            )
            runtime = adapter._build_runtime()
            self.assertEqual(runtime["module"].__name__, "glm_embedded_covibe")
            self.assertGreaterEqual(len(runtime["registry"].names()), 20)

    def test_headless_tui_does_not_require_terminal(self):
        class Module:
            @staticmethod
            def _extract_tool_calls_from_text(content, known_tools):
                return [], content

        tui = HeadlessTUI(Module)
        content, calls = tui.show_sync_response({
            "choices": [{"message": {"content": "hello", "tool_calls": []}}]
        })
        self.assertEqual(content, "hello")
        self.assertEqual(calls, [])

    def test_approval_provider_publishes_b3_request(self):
        broker = ApprovalBroker(token="test")
        audit = AuditLogger(Path(tempfile.mkdtemp()) / "audit.sqlite3")
        provider = GLMApprovalProvider(broker, audit, timeout_seconds=1)
        result = provider.ask_permission("Bash", {"command": "echo test"})
        self.assertFalse(result)
        pending = broker.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["requested_by"], "co-vibe-agent")
        self.assertIn("reason", pending[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
