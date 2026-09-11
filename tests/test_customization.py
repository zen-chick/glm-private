import json
import tempfile
import unittest
from pathlib import Path

from glm_customization import CustomizationRegistry


class TestCustomizationRegistry(unittest.TestCase):
    def test_loads_documents_mcp_and_hooks_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / ".github").mkdir()
            (workspace / ".glm").mkdir()
            (workspace / ".github" / "copilot-instructions.md").write_text("Use focused tests.", encoding="utf-8")
            (workspace / "review.instructions.md").write_text("---\napplyTo: '**/*.py'\n---\nReview Python changes.", encoding="utf-8")
            (workspace / ".glm" / "hooks.json").write_text(json.dumps({"hooks": {"before_agent": ["echo forbidden"]}}), encoding="utf-8")
            (workspace / "mcp-servers.json").write_text(json.dumps({"mcpServers": {"demo": {"command": "demo", "args": ["--stdio"], "enabled": False}}}), encoding="utf-8")
            registry = CustomizationRegistry(workspace, workspace / ".global")
            summary = registry.summary()
            self.assertEqual(len(summary["documents"]), 2)
            self.assertEqual(summary["mcp_servers"][0]["name"], "demo")
            self.assertEqual(summary["hooks"]["before_agent"], 1)
            self.assertFalse(registry.emit("before_agent")["executed"])

    def test_prepares_system_message(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "SKILL.md").write_text("Use pytest.", encoding="utf-8")
            registry = CustomizationRegistry(workspace, workspace / ".global")
            messages = registry.prepare_messages([{"role": "user", "content": "test"}])
            self.assertEqual(messages[0]["role"], "system")
            self.assertIn("Use pytest.", messages[0]["content"])
            self.assertEqual(messages[-1]["content"], "test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
