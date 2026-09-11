import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_mcp_gate import ensure_auth_token, is_private_client


class TestRemoteGate(unittest.TestCase):
    def test_allows_private_and_loopback_addresses(self):
        self.assertTrue(is_private_client("127.0.0.1"))
        self.assertTrue(is_private_client("192.168.1.10"))
        self.assertTrue(is_private_client("10.0.0.5"))

    def test_rejects_public_address(self):
        self.assertFalse(is_private_client("8.8.8.8"))

    def test_creates_and_reuses_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth_token"
            first = ensure_auth_token(path)
            second = ensure_auth_token(path)
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main(verbosity=2)