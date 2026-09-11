import tempfile
import unittest
from pathlib import Path

from glm_marketplace import Marketplace


class TestMarketplace(unittest.TestCase):
    def test_catalog_install_and_builtin_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            marketplace = Marketplace(Path(directory))
            self.assertTrue(marketplace.list("pylance")[0]["builtin"])
            installed = marketplace.install("glm.pylance-mcp")
            self.assertTrue(installed["installed"])
            with self.assertRaises(ValueError):
                marketplace.uninstall("glm.pylance-mcp")

    def test_unknown_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                Marketplace(Path(directory)).install("unknown.extension")


if __name__ == "__main__":
    unittest.main(verbosity=2)
