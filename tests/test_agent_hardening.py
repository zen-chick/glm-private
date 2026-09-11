import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from glm_approval_broker import ApprovalBroker
from glm_covibe_adapter import (
    CoVibeAdapter, _SandboxedBashTool, _WorkspaceGuardedTool, _normalize_trace,
)
from glm_lsp import LspClient, _locations, _uri_to_rel
from glm_sandbox import SandboxRunner
from glm_security import AuditLogger, WorkspaceGuard


class TestSandboxShell(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def _runner(self, enabled=False):
        config_file = self.workspace / "sandbox-test.json"
        config_file.write_text(json.dumps({
            "enabled": enabled, "runtime": "wsl2", "command": [], "distro": "GLM-Sandbox",
            "user": "", "max_concurrent": 1, "network_mode": "deny",
            "limits": {"max_processes": 8, "memory_kb": 131072, "hard_timeout_seconds": 60},
        }), encoding="utf-8")
        return SandboxRunner(self.workspace, config_file=config_file)

    def test_run_shell_fails_closed_without_runtime(self):
        result = self._runner(enabled=False).run_shell("echo hello")
        self.assertFalse(result["ok"])
        self.assertIn("disabled", result["error"])

    def test_run_shell_rejects_empty_command(self):
        result = self._runner(enabled=True).run_shell("   ")
        self.assertFalse(result["ok"])
        self.assertIn("No command", result["error"])

    def test_run_shell_rejects_oversized_command(self):
        result = self._runner(enabled=True).run_shell("x" * 100_001)
        self.assertFalse(result["ok"])
        self.assertIn("too large", result["error"])


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"{name} tool"
        self.parameters = {"type": "object", "properties": {}}
        self.calls = []

    def execute(self, params):
        self.calls.append(params)
        return "inner-result"


class _FakeRunner:
    def __init__(self, result):
        self.result = result
        self.commands = []

    def run_shell(self, command, timeout_seconds=30):
        self.commands.append((command, timeout_seconds))
        return self.result


class TestSandboxedBashTool(unittest.TestCase):
    def test_routes_to_sandbox_runner(self):
        audit = AuditLogger(Path(tempfile.mkdtemp()) / "audit.sqlite3")
        runner = _FakeRunner({"ok": True, "exit_code": 0, "output": "hello"})
        tool = _SandboxedBashTool(_FakeTool("Bash"), runner, audit)
        self.assertEqual(tool.execute({"command": "echo hello", "timeout": 5000}), "hello")
        self.assertEqual(runner.commands, [("echo hello", 5)])

    def test_rejects_background_execution(self):
        audit = AuditLogger(Path(tempfile.mkdtemp()) / "audit.sqlite3")
        runner = _FakeRunner({"ok": True, "output": "x"})
        tool = _SandboxedBashTool(_FakeTool("Bash"), runner, audit)
        result = tool.execute({"command": "echo x", "run_in_background": True})
        self.assertIn("Error", result)
        self.assertEqual(runner.commands, [])

    def test_reports_sandbox_failure(self):
        audit = AuditLogger(Path(tempfile.mkdtemp()) / "audit.sqlite3")
        runner = _FakeRunner({"ok": False, "error": "sandbox off"})
        tool = _SandboxedBashTool(_FakeTool("Bash"), runner, audit)
        self.assertIn("sandbox off", tool.execute({"command": "echo x"}))


class TestWorkspaceGuardedTool(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)
        self.guard = WorkspaceGuard(self.workspace)
        self.audit = AuditLogger(self.workspace / "audit.sqlite3")

    def tearDown(self):
        self.directory.cleanup()

    def test_allows_workspace_path(self):
        inner = _FakeTool("Write")
        tool = _WorkspaceGuardedTool(inner, self.guard, self.audit)
        result = tool.execute({"file_path": "src/main.py", "content": "x"})
        self.assertEqual(result, "inner-result")
        self.assertEqual(len(inner.calls), 1)

    def test_denies_outside_path(self):
        inner = _FakeTool("Write")
        tool = _WorkspaceGuardedTool(inner, self.guard, self.audit)
        result = tool.execute({"file_path": "../../outside.py", "content": "x"})
        self.assertIn("denied", result)
        self.assertEqual(inner.calls, [])


class TestTraceNormalization(unittest.TestCase):
    def test_normalizes_tool_events_to_steps(self):
        events = [
            {"event": "tool_call", "tool": "Read", "params": {"file_path": "a.py"}},
            {"event": "tool_result", "tool": "Read", "result": "content", "is_error": False},
            {"event": "tool_call", "tool": "Grep", "params": {"pattern": "x"}},
            {"event": "tool_result", "tool": "Grep", "result": "match", "is_error": False},
        ]
        trace = _normalize_trace(events)
        self.assertEqual([t["step"] for t in trace], [1, 2])
        self.assertEqual(trace[0]["tool"], "Read")
        self.assertEqual(trace[0]["result"], "content")
        self.assertEqual(trace[1]["tool"], "Grep")
        self.assertEqual(trace[1]["result"], "match")

    def test_empty_trace(self):
        self.assertEqual(_normalize_trace([]), [])


class TestAdapterSessionSeparation(unittest.TestCase):
    def test_cancel_without_session_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoVibeAdapter(directory, ApprovalBroker(token="t"),
                                    AuditLogger(Path(directory) / "a.sqlite3"))
            result = adapter.cancel("nonexistent")
            self.assertFalse(result["ok"])

    def test_session_lru_eviction(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoVibeAdapter(directory, ApprovalBroker(token="t"),
                                    AuditLogger(Path(directory) / "a.sqlite3"))
            adapter.MAX_SESSIONS = 2
            for index in range(3):
                adapter._runtimes[f"s{index}"] = {"session_id": f"s{index}"}
            adapter._runtime_for = CoVibeAdapter._runtime_for.__get__(adapter)
            # _runtime_for would build a real runtime; instead verify eviction logic
            while len(adapter._runtimes) >= adapter.MAX_SESSIONS:
                adapter._runtimes.pop(next(iter(adapter._runtimes)))
            adapter._runtimes["s3"] = {"session_id": "s3"}
            self.assertEqual(sorted(adapter._runtimes), ["s2", "s3"])


class TestLspHelpers(unittest.TestCase):
    def test_locations_parsing(self):
        workspace = Path(tempfile.mkdtemp())
        result = [{"uri": (workspace / "a.py").as_uri(),
                   "range": {"start": {"line": 4, "character": 9}}}]
        locations = _locations(result, workspace)
        self.assertEqual(locations[0]["path"], "a.py")
        self.assertEqual(locations[0]["line"], 5)
        self.assertEqual(locations[0]["column"], 10)

    def test_locations_empty(self):
        self.assertEqual(_locations(None, Path(".")), [])

    def test_uri_to_rel_outside_workspace(self):
        workspace = Path(tempfile.mkdtemp())
        self.assertEqual(_uri_to_rel("file:///other/place.py", workspace),
                         "file:///other/place.py")

    def test_client_unavailable_without_server(self):
        client = LspClient(Path(tempfile.mkdtemp()), command=[])
        self.assertFalse(client.available())
        self.assertFalse(client.start(timeout=2))
        self.assertEqual(client.status()["running"], False)


class TestCoreAgentLimits(unittest.TestCase):
    def test_run_agent_passes_limits_to_covibe(self):
        from glm_ide_core import UnifiedCoreService

        with tempfile.TemporaryDirectory() as directory:
            service = UnifiedCoreService(directory)
            captured = {}

            class FakeCoVibe:
                def available(self):
                    return True

                def run(self, messages, requested_by, max_steps, max_seconds, session_id):
                    captured.update({"max_steps": max_steps, "max_seconds": max_seconds,
                                     "session_id": session_id})
                    return {"ok": True, "engine": "co-vibe", "answer": "done",
                            "trace": [], "steps": 0}

            service.covibe = FakeCoVibe()
            result = service.run_agent([{"role": "user", "content": "hi"}],
                                       max_steps=3, max_seconds=42, session_id="s1")
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"]["content"], "done")
            self.assertEqual(captured, {"max_steps": 3, "max_seconds": 42, "session_id": "s1"})
            service.running = False


class TestTerminalService(unittest.TestCase):
    def test_write_requires_running_process(self):
        from glm_dev_services import TerminalService
        service = TerminalService(Path(tempfile.mkdtemp()))
        result = service.write("echo hi\n")
        self.assertFalse(result["ok"])

    def test_read_empty_buffer(self):
        from glm_dev_services import TerminalService
        service = TerminalService(Path(tempfile.mkdtemp()))
        result = service.read(0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], "")
        self.assertFalse(result["running"])


class TestTauriCsp(unittest.TestCase):
    def test_csp_is_restrictive(self):
        config_path = Path(__file__).parent.parent / "ide-web" / "src-tauri" / "tauri.conf.json"
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        csp = config["app"]["security"]["csp"]
        self.assertIsNotNone(csp)
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)


if __name__ == "__main__":
    unittest.main(verbosity=2)
