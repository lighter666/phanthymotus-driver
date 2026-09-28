import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "remove_legacy_cards.py"
spec = importlib.util.spec_from_file_location("remove_legacy_cards", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RemoveLegacyCardsTest(unittest.TestCase):
    def test_preview_and_apply_only_exact_legacy_registration(self):
        records = [
            {"id": "mcp-1", "name": module.LEGACY_NAME, "url": module.LEGACY_URL},
            {"id": "mcp-2", "name": "Bumi Health Check", "url": "http://localhost:15741/mcp"},
            {"id": "mcp-3", "name": module.LEGACY_NAME, "url": "http://other-host:15740/mcp"},
        ]
        calls = []

        def fake_request(url, method="GET"):
            calls.append((method, url))
            if method == "DELETE":
                records[:] = [record for record in records if url.rsplit("/", 1)[-1] != record["id"]]
                return {"code": 200}
            return {"code": 200, "data": records}

        with patch.object(module, "request_json", side_effect=fake_request):
            self.assertEqual(len(module.remove("https://localhost:15678")), 1)
            self.assertEqual([method for method, _ in calls], ["GET"])
            calls.clear()
            self.assertEqual(len(module.remove("https://localhost:15678", apply=True)), 1)

        self.assertEqual([method for method, _ in calls], ["GET", "DELETE", "GET"])
        self.assertEqual([record["id"] for record in records], ["mcp-2", "mcp-3"])


if __name__ == "__main__":
    unittest.main()
