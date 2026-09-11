import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_ide_core import UnifiedCoreService, validate_bind_host
from glm_security import SecretStore

class TestUnifiedCoreService(unittest.TestCase):
    def test_remote_bind_is_limited_to_loopback_and_tailscale(self):
        self.assertEqual(validate_bind_host("localhost"), "127.0.0.1")
        self.assertEqual(validate_bind_host("100.64.12.34"), "100.64.12.34")
        with self.assertRaises(ValueError):
            validate_bind_host("0.0.0.0")
        with self.assertRaises(ValueError):
            validate_bind_host("192.168.1.10")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "test1.py").write_text("print('hello')", encoding="utf-8")
        (self.workspace / "sub").mkdir()
        (self.workspace / "sub" / "test2.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_file_operations(self):
        service = UnifiedCoreService(str(self.workspace))
        files = service.list_files()
        self.assertIn("test1.py", files)
        self.assertIn("sub/test2.json", files)

        # Read
        content = service.read_file("test1.py")
        self.assertEqual(content, "print('hello')")

        # Save (Direct Save)
        service.save_file("test1.py", "print('updated')")
        self.assertEqual(service.read_file("test1.py"), "print('updated')")

        # Create new file via save
        service.save_file("sub/new_file.txt", "new content")
        self.assertEqual(service.read_file("sub/new_file.txt"), "new content")

        service.create_file("created.txt", "created")
        self.assertEqual(service.read_file("created.txt"), "created")
        service.move_file("created.txt", "renamed.txt")
        self.assertEqual(service.read_file("renamed.txt"), "created")
        self.assertTrue(service.search_files("created"))
        service.delete_file("renamed.txt")

    def test_error_recording_and_self_healing(self):
        service = UnifiedCoreService(str(self.workspace))
        entry = service.record_error("TestComponent", "Simulated error")
        self.assertTrue(entry["healed"])
        self.assertEqual(len(service.errors_log), 1)

    def test_syntax_check(self):
        service = UnifiedCoreService(str(self.workspace))
        # Valid Python
        res_ok = service.check_syntax("test1.py")
        self.assertTrue(res_ok["ok"])

        # Invalid Python syntax
        res_bad = service.check_syntax("test1.py", content="def invalid_func(:")
        self.assertFalse(res_bad["ok"])
        self.assertEqual(len(res_bad["errors"]), 1)
        self.assertEqual(res_bad["errors"][0]["line"], 1)

    def test_code_execution(self):
        service = UnifiedCoreService(str(self.workspace))
        res = service.execute_code("test1.py")
        self.assertTrue(res["ok"])
        self.assertIn("hello", res["stdout"])

    def test_ipynb_parsing(self):
        service = UnifiedCoreService(str(self.workspace))
        nb_path = self.workspace / "demo.ipynb"
        nb_path.write_text(json.dumps({
            "cells": [
                {"cell_type": "markdown", "source": ["# Title"]},
                {"cell_type": "code", "source": ["print(123)"], "outputs": []}
            ]
        }), encoding="utf-8")
        res = service.read_ipynb("demo.ipynb")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["cells"]), 2)

    def test_definition_search(self):
        service = UnifiedCoreService(str(self.workspace))
        source = "def target():\n    return 1\n"
        result = service.find_definitions("test1.py", "target", source)
        self.assertEqual(result["definitions"][0]["line"], 1)

    def test_definition_search_resolves_imported_module(self):
        service = UnifiedCoreService(str(self.workspace))
        (self.workspace / "helpers.py").write_text("def imported_target():\n    return 1\n", encoding="utf-8")
        source = "from helpers import imported_target\nimported_target()\n"
        result = service.find_definitions("test1.py", "imported_target", source)
        self.assertEqual(result["definitions"][0]["path"], "helpers.py")
        self.assertEqual(result["definitions"][0]["line"], 1)

    def test_definition_search_resolves_package_module(self):
        service = UnifiedCoreService(str(self.workspace))
        package = self.workspace / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "mod.py").write_text("class ImportedClass:\n    pass\n", encoding="utf-8")
        source = "from pkg.mod import ImportedClass\n"
        result = service.find_definitions("test1.py", "ImportedClass", source)
        self.assertEqual(result["definitions"][0]["path"], "pkg/mod.py")

    def test_notebook_cell_execution(self):
        service = UnifiedCoreService(str(self.workspace))
        result = service.run_notebook_cell("print('cell output')")
        self.assertTrue(result["ok"])
        self.assertIn("cell output", result["stdout"])

    def test_git_stage_rejects_workspace_escape(self):
        service = UnifiedCoreService(str(self.workspace))
        result = service.git_stage(["../outside.txt"])
        self.assertFalse(result["ok"])

    def test_workspace_guard(self):
        service = UnifiedCoreService(str(self.workspace))
        with self.assertRaises(PermissionError):
            service.read_file("../outside.txt")

    def test_provider_credentials_are_managed_without_exposure(self):
        service = UnifiedCoreService(str(self.workspace))
        secrets_dir = Path(self.temp_dir.name) / "secrets"
        service.secrets = SecretStore(secrets_dir)

        self.assertFalse(service.provider_status()["openai"]["configured"])
        service.save_provider_secret("openai", "test-key")

        self.assertTrue(service.provider_status()["openai"]["configured"])
        self.assertEqual(service.provider_api_key("openai"), "test-key")
        with self.assertRaises(ValueError):
            service.save_provider_secret("unknown", "test-key")

    def test_github_mcp_uses_secret_store_token(self):
        service = UnifiedCoreService(str(self.workspace))
        secrets_dir = Path(self.temp_dir.name) / "secrets"
        service.secrets = SecretStore(secrets_dir)
        service.github_mcp.token_getter = lambda: service.provider_api_key("github")
        service.save_provider_secret("github", "stored-pat")
        self.assertEqual(service.github_mcp._environment()["GITHUB_PERSONAL_ACCESS_TOKEN"], "stored-pat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
