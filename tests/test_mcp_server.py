import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_mcp_server import MCPServer
from glm_security import AuditLogger


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audit = AuditLogger(Path(self.temp.name) / "audit.sqlite3")
        self.server = MCPServer(self.audit, lambda endpoint: {"endpoint": endpoint}, notion=FakeNotion())

    def tearDown(self):
        self.temp.cleanup()

    def test_initialize_returns_capabilities(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(response["result"]["serverInfo"]["name"], "glm-router")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_list_returns_read_only_tools(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(
            {tool["name"] for tool in response["result"]["tools"]},
            {"glm_status", "glm_sessions", "notion_search", "notion_page"},
        )

    def test_call_returns_router_data(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "glm_status"}})
        value = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(value["endpoint"], "/status")

    def test_rejects_unknown_tools(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "Bash"}})
        self.assertEqual(response["error"]["code"], -32602)

    def test_calls_notion_search(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "notion_search", "arguments": {"query": "notes"}}})
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["query"], "notes")


class FakeNotion:
    def search(self, query, page_size):
        return {"query": query, "page_size": page_size}

    def page(self, page_id):
        return {"page_id": page_id}


if __name__ == "__main__":
    unittest.main(verbosity=2)