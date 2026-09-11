import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_integrations import IntegrationRegistry
from glm_security import SecretStore


class TestIntegrationRegistry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = self.root / "integrations.json"
        self.secrets = self.root / "secrets"
        self.secrets.mkdir()
        self.registry.write_text(json.dumps({"integrations": {"notion": {
            "enabled": True, "mode": "read_only", "required_secrets": ["notion_token"],
            "minimum_scopes": ["read_content"], "available_features": ["search_pages"],
            "blocked_features": ["update_page"]
        }}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_reports_missing_secrets_without_values(self):
        status = IntegrationRegistry(self.registry, SecretStore(self.secrets)).status("notion")["notion"]
        self.assertFalse(status["ready"])
        self.assertEqual(status["missing_secrets"], ["notion_token"])

    def test_reports_ready_after_secret_is_registered(self):
        (self.secrets / "notion_token").write_text("value", encoding="utf-8")
        status = IntegrationRegistry(self.registry, SecretStore(self.secrets)).status("notion")["notion"]
        self.assertTrue(status["ready"])
        self.assertNotIn("value", json.dumps(status))

    def test_refuses_enable_until_required_secret_exists(self):
        registry = IntegrationRegistry(self.registry, SecretStore(self.secrets))
        (self.registry).write_text(json.dumps({"integrations": {"notion": {
            "enabled": False, "mode": "read_only", "required_secrets": ["notion_token"],
            "minimum_scopes": [], "available_features": [], "blocked_features": []
        }}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            registry.set_enabled("notion", True)
        (self.secrets / "notion_token").write_text("value", encoding="utf-8")
        self.assertTrue(registry.set_enabled("notion", True)["ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)