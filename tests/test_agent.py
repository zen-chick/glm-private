import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_agent import AgentRunner, AgentTool, default_diagnostic_tools, fetch_webpage, todo_tool
from glm_security import AuditLogger


class TestAgentRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit = AuditLogger(Path(self.temp.name) / "audit.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_tool_call_round_trip(self):
        responses = iter([
            {"choices": [{"message": {"role": "assistant", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "inspect", "arguments": "{}"
                },
            }]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "完了しました"}}]},
        ])
        calls = []
        runner = AgentRunner(
            lambda messages, tools: (calls.append((list(messages), list(tools))) or next(responses)),
            [AgentTool("inspect", "read only", {"type": "object", "properties": {}}, lambda _: {"ok": True, "value": 42})],
            self.audit,
        )
        result = runner.run([{"role": "user", "content": "確認して"}], "session-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"]["content"], "完了しました")
        self.assertEqual(len(result["trace"]), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0][-1]["role"], "tool")

    def test_step_limit_stops_loop(self):
        response = {"choices": [{"message": {"role": "assistant", "tool_calls": [{
            "id": "loop", "function": {"name": "inspect", "arguments": "{}"}
        }]}}]}
        runner = AgentRunner(
            lambda messages, tools: response,
            [AgentTool("inspect", "read only", {"type": "object", "properties": {}}, lambda _: {"ok": True})],
            self.audit,
            max_steps=2,
        )
        result = runner.run([{"role": "user", "content": "繰り返して"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "agent_step_limit_exceeded")

    def test_unknown_tool_is_denied(self):
        response = {"choices": [{"message": {"role": "assistant", "tool_calls": [{
            "id": "unknown", "function": {"name": "shell", "arguments": "{}"}
        }]}}]}
        runner = AgentRunner(
            lambda messages, tools: response,
            [AgentTool("inspect", "read only", {"type": "object", "properties": {}}, lambda _: {"ok": True})],
            self.audit,
            max_steps=1,
        )
        result = runner.run([{"role": "user", "content": "実行して"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["trace"][0]["result"]["error"], "tool is not allowed")

    def test_web_tool_rejects_non_http_urls(self):
        self.assertFalse(fetch_webpage({"url": "file:///secret.txt"})["ok"])

    def test_todo_tool_stays_inside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            result = todo_tool(Path(directory), {"action": "add", "title": "Run tests"})
            self.assertTrue(result["ok"])
            self.assertTrue((Path(directory) / ".glm" / "todos.json").exists())
            self.assertEqual(len(default_diagnostic_tools(Path(directory))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
