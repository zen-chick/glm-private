import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_sandbox import SandboxRunner, SandboxTool, decode_process_output, load_sandbox_config


class TestSandboxRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.script = self.workspace / "check.py"
        self.script.write_text("print('ok')", encoding="utf-8")
        self.disabled_config = Path(self.temp.name) / "sandbox.json"
        self.disabled_config.write_text('{"enabled": false, "runtime": "none"}', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_refuses_host_execution_without_runtime(self):
        result = SandboxRunner(self.workspace, config_file=self.disabled_config).run_python_file(self.script)
        self.assertFalse(result["ok"])
        self.assertIn("host execution is disabled", result["error"])

    def test_rejects_file_outside_workspace(self):
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("print('no')", encoding="utf-8")
        with self.assertRaises(PermissionError):
            SandboxRunner(self.workspace).run_python_file(outside)

    def test_rejects_non_python_file(self):
        target = self.workspace / "check.txt"
        target.write_text("not python", encoding="utf-8")
        result = SandboxRunner(self.workspace, ["echo", "ignored"]).run_python_file(target)
        self.assertFalse(result["ok"])
        self.assertIn("Only Python", result["error"])

    def test_rejects_string_command_configuration(self):
        config = Path(self.temp.name) / "sandbox.json"
        config.write_text('{"enabled": true, "runtime": "test", "command": "python {script}"}', encoding="utf-8")
        self.assertEqual(load_sandbox_config(config)["command"], [])

    def test_decodes_common_process_output_encodings(self):
        self.assertEqual(decode_process_output("日本語".encode("utf-8")), "日本語")
        self.assertEqual(decode_process_output("WSL error".encode("utf-16-le")), "WSL error")
        self.assertEqual(decode_process_output("日本語".encode("utf-16")), "日本語")
        self.assertEqual(decode_process_output("日本語".encode("cp932")), "日本語")

    def test_tool_preserves_host_execution_refusal(self):
        result = SandboxTool(self.workspace, config_file=self.disabled_config).execute({"path": "check.py"})
        self.assertIn("host execution is disabled", result)

    def test_runs_in_configured_wsl2(self):
        config = Path(self.temp.name) / "wsl-sandbox.json"
        config.write_text('{"enabled": true, "runtime": "wsl2"}', encoding="utf-8")
        result = SandboxRunner(self.workspace, config_file=config).run_python_file(self.script)
        self.assertTrue(result["ok"])
        self.assertIn("ok", result["output"])


if __name__ == "__main__":
    unittest.main(verbosity=2)