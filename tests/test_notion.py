import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_notion import NotionReadClient
from glm_security import SecretStore


class TestNotionReadClient(unittest.TestCase):
    def test_refuses_when_secret_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = NotionReadClient(SecretStore(Path(directory))).search("notes")
        self.assertIn("not configured", result["error"])

    def test_search_bounds_size_and_redacts_properties(self):
        called = []
        def request(method, endpoint, body):
            called.append((method, endpoint, body))
            return {"results": [{"id": "1", "url": "https://notion.so/1", "object": "page", "properties": {"secret": "no"}}]}
        result = NotionReadClient(request=request).search("note", 100)
        self.assertEqual(called[0][2]["page_size"], 20)
        redacted = NotionReadClient._redact(result)
        self.assertNotIn("properties", redacted["results"][0])

    def test_page_requires_an_id(self):
        self.assertIn("required", NotionReadClient(request=lambda *_: {}).page("")["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)