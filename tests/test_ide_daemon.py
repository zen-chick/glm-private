import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_ide_daemon import IDEDaemonService

class TestIDEDaemonService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "file1.py").write_text("print('test1')", encoding="utf-8")
        (self.workspace / "file2.json").write_text("{}", encoding="utf-8")
        (self.workspace / "sub").mkdir()
        (self.workspace / "sub" / "file3.md").write_text("# Hello", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_files(self):
        service = IDEDaemonService(str(self.workspace))
        files = service.list_files()
        self.assertIn("file1.py", files)
        self.assertIn("file2.json", files)
        self.assertIn("sub/file3.md", files)

    def test_workspace_guard(self):
        service = IDEDaemonService(str(self.workspace))
        inside = service.guard.require_contained(self.workspace / "file1.py")
        self.assertEqual(inside, (self.workspace / "file1.py").resolve())

        with self.assertRaises(PermissionError):
            service.guard.require_contained(Path(self.temp_dir.name) / "outside.txt")

    def test_status(self):
        service = IDEDaemonService(str(self.workspace))
        status = service.get_status()
        self.assertEqual(status["workspace"], str(self.workspace.resolve()))
        self.assertIn("daemon_pid", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
