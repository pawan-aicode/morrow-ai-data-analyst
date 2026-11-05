import json
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

from app.dashboard_builder import (
    _dashboard_profile_context,
    generate_dashboard_plan,
)


class TestDashboardProfileIntegration(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "order_date": [
                "2026-01-01", "2026-01-02",
                "2026-01-03", "2026-01-04",
            ],
            "category": ["A", "B", "A", "B"],
            "sales": [100, 200, None, 400],
            "order_id": [1, 2, 3, 4],
        })

    def test_profile_context_contains_column_statistics(self):
        profile = _dashboard_profile_context(self.df)

        columns = {
            item["name"]: item
            for item in profile["columns"]
        }

        self.assertEqual(columns["sales"]["type"], "numeric")
        self.assertEqual(columns["sales"]["missing_percent"], 25.0)
        self.assertIn("mean", columns["sales"]["statistics"])

        self.assertEqual(columns["order_date"]["type"], "date")
        self.assertEqual(columns["category"]["type"], "categorical")

        self.assertIn("recommendations", profile)

    def test_profile_context_preserves_sampling_metadata(self):
        self.df.attrs["source_rows"] = 6000
        self.df.attrs["is_sampled"] = True

        profile = _dashboard_profile_context(self.df)

        self.assertTrue(profile["overview"]["is_sampled"])
        self.assertEqual(profile["overview"]["loaded_rows"], 4)
        self.assertEqual(profile["overview"]["source_rows"], 6000)
        self.assertAlmostEqual(
            profile["overview"]["coverage_percent"], 0.07
        )

    @patch("app.dashboard_builder.urllib.request.urlopen")
    def test_dashboard_prompt_receives_profile(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps({
            "message": {
                "content": json.dumps({
                    "title": "Sales Overview",
                    "summary": "Sales analysis",
                    "kpis": [],
                    "charts": [],
                })
            }
        }).encode("utf-8")

        response_context = MagicMock()
        response_context.__enter__.return_value = response
        response_context.__exit__.return_value = False
        mock_urlopen.return_value = response_context

        plan = generate_dashboard_plan("Analyse sales", self.df)

        self.assertEqual(plan["title"], "Sales Overview")

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        prompt = payload["messages"][1]["content"]

        self.assertIn("Data profile:", prompt)
        self.assertIn('"name": "sales"', prompt)
        self.assertIn('"type": "numeric"', prompt)
        self.assertIn("Respect the sample warning", prompt)
        self.assertIn("Prefer meaningful business measures", prompt)

    @patch("app.dashboard_builder.urllib.request.urlopen")
    def test_sample_warning_reaches_dashboard_prompt(self, mock_urlopen):
        self.df.attrs["source_rows"] = 6000
        self.df.attrs["is_sampled"] = True

        response = MagicMock()
        response.read.return_value = json.dumps({
            "message": {
                "content": json.dumps({
                    "title": "Sampled Analysis",
                    "summary": "Analysis of loaded sample",
                    "kpis": [],
                    "charts": [],
                })
            }
        }).encode("utf-8")

        response_context = MagicMock()
        response_context.__enter__.return_value = response
        response_context.__exit__.return_value = False
        mock_urlopen.return_value = response_context

        generate_dashboard_plan("Analyse sales", self.df)

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        prompt = payload["messages"][1]["content"]

        self.assertIn('"is_sampled": true', prompt)
        self.assertIn('"source_rows": 6000', prompt)
        self.assertIn('"coverage_percent": 0.07', prompt)


if __name__ == "__main__":
    unittest.main()
