import sys
import tempfile
import unittest
from pathlib import Path

from glm_customization import CustomizationRegistry
from glm_mcp_bootstrap import MCPProcessManager


class TestMCPProcessManager(unittest.TestCase):
    def test_disabled_server_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = CustomizationRegistry(Path(directory), Path(directory) / "global")
            registry.mcp_servers = {"demo": {"name": "demo", "command": sys.executable, "args": [], "enabled": False}}
            with self.assertRaises(ValueError):
                MCPProcessManager(registry).list_tools("demo")

    def test_enabled_server_lists_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            script = "import sys,json; [print(json.dumps({'jsonrpc':'2.0','id':2,'result':{'tools':[{'name':'demo'}]} })) for line in sys.stdin if 'tools/list' in line]"
            registry = CustomizationRegistry(Path(directory), Path(directory) / "global")
            registry.mcp_servers = {"demo": {"name": "demo", "command": sys.executable,
                                               "args": ["-c", script], "enabled": True}}
            result = MCPProcessManager(registry).list_tools("demo")
            self.assertEqual(result["tools"][0]["name"], "demo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
