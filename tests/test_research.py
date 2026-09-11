import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from glm_research import ResearchLibrary, ResearchTool


class TestResearchLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "research.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_search_bounds_limit_and_marks_external_data(self):
        calls = []
        def request(query, limit):
            calls.append((query, limit))
            return {"source": "Semantic Scholar", "external_data": True, "papers": []}
        result = ResearchLibrary(self.database, request).search("secure AI", 100)
        self.assertEqual(calls, [("secure AI", 20)])
        self.assertTrue(result["external_data"])

    def test_saves_structured_paper(self):
        library = ResearchLibrary(self.database)
        self.assertEqual(library.save({"paper_id": "p1", "title": "Paper", "authors": ["Author"]}), {"saved": "p1"})
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute("SELECT title, authors_json FROM papers WHERE paper_id = 'p1'").fetchone()
        finally:
            connection.close()
        self.assertEqual(row[0], "Paper")
        self.assertEqual(json.loads(row[1]), ["Author"])

    def test_tool_rejects_invalid_action(self):
        output = ResearchTool(ResearchLibrary(self.database)).execute({"action": "delete"})
        self.assertIn("error", json.loads(output))


if __name__ == "__main__":
    unittest.main(verbosity=2)