import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from governance_report import add_effectiveness_entry, generate_report, load_effectiveness_log


class TestEffectivenessLog(unittest.TestCase):
    def test_missing_log_returns_empty_template(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            self.assertEqual(load_effectiveness_log(path), {"entries": []})

    def test_add_entry_persists_and_reloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            add_effectiveness_entry("ルーティング精度", "日本語入力での誤判定を確認", "session-42のログ参照", "needs_attention", path=path)
            log = load_effectiveness_log(path)
            self.assertEqual(len(log["entries"]), 1)
            self.assertEqual(log["entries"][0]["area"], "ルーティング精度")
            self.assertEqual(log["entries"][0]["status"], "needs_attention")

    def test_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            with self.assertRaises(ValueError):
                add_effectiveness_entry("area", "finding", status="bogus", path=path)

    def test_rejects_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            with self.assertRaises(ValueError):
                add_effectiveness_entry("", "finding", path=path)

    def test_multiple_entries_accumulate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            add_effectiveness_entry("A", "finding1", path=path)
            add_effectiveness_entry("B", "finding2", path=path)
            log = load_effectiveness_log(path)
            self.assertEqual(len(log["entries"]), 2)


class TestGenerateReport(unittest.TestCase):
    def test_report_contains_all_axes_and_manual_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.json"
            add_effectiveness_entry("LSP診断精度", "実運用で誤検知なし", "テスト89件通過", "good", path=path)
            report = generate_report(effectiveness_path=path)
            self.assertIn("safety_security", report)
            self.assertIn("privacy", report)
            self.assertIn("transparency_accountability", report)
            self.assertIn("fairness_effectiveness_manual_log", report)
            entries = report["fairness_effectiveness_manual_log"]["entries"]
            self.assertEqual(entries[0]["area"], "LSP診断精度")

    def test_report_reflects_audit_integrity(self):
        report = generate_report()
        self.assertIn("ok", report["safety_security"]["audit_integrity"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
