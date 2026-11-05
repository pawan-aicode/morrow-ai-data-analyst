import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import saved_dashboards as store


class TestSavedDashboards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch_dir = patch.object(store, "SAVE_DIR", Path(self.temp.name))
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)

    def test_save_load_and_list(self):
        config = {
            "start_date": "2026-01-01",
            "end_date": "2026-10-25",
            "status": "completed",
            "category": "Electronics",
            "completed_only": True,
        }
        saved = store.save_dashboard("Completed Sales", config)
        loaded = store.load_dashboard("Completed Sales")
        self.assertEqual(loaded["start_date"], "2026-01-01")
        self.assertEqual(loaded["status"], "completed")
        self.assertTrue(loaded["completed_only"])
        self.assertEqual(store.list_dashboards()[0]["name"], "Completed Sales")
        self.assertEqual(saved["category"], "Electronics")

    def test_case_insensitive_overwrite(self):
        store.save_dashboard("Monthly Sales", {
            "start_date": "2026-01-01", "end_date": "2026-02-01"
        })
        store.save_dashboard("monthly sales", {
            "start_date": "2026-02-01", "end_date": "2026-03-01"
        })
        self.assertEqual(len(store.list_dashboards()), 1)
        self.assertEqual(
            store.load_dashboard("MONTHLY SALES")["start_date"], "2026-02-01"
        )

    def test_reject_path_traversal_name(self):
        with self.assertRaises(ValueError):
            store.save_dashboard("../unsafe", {})

    def test_reject_invalid_date_range(self):
        with self.assertRaises(ValueError):
            store.save_dashboard("Invalid dates", {
                "start_date": "2026-10-25",
                "end_date": "2026-01-01",
            })

    def test_delete(self):
        store.save_dashboard("Temporary", {})
        store.delete_dashboard("Temporary")
        self.assertEqual(store.list_dashboards(), [])
        with self.assertRaises(FileNotFoundError):
            store.load_dashboard("Temporary")


if __name__ == "__main__":
    unittest.main()
