import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.insights import calculate_factual_insights
from app.insight_explainer import explain_factual_insights


class TestInsightQuality(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "order_id": [1, 2, 3, 4],
            "category": ["A", "B", "A", "B"],
            "sales": [100, 200, 300, 400],
        })
        self.df.attrs["source_rows"] = 6000
        self.df.attrs["is_sampled"] = True

    def test_unprocessed_rows_are_calculated_correctly(self):
        result = calculate_factual_insights(self.df)

        self.assertEqual(result["scope"]["loaded_rows"], 4)
        self.assertEqual(result["scope"]["source_rows"], 6000)
        self.assertEqual(result["scope"]["unprocessed_rows"], 5996)

    def test_average_definition_is_explicit(self):
        result = calculate_factual_insights(self.df)

        metric = next(
            item for item in result["numeric_metrics"]
            if item["column"] == "sales"
        )

        self.assertEqual(metric["average"], 250.0)
        self.assertIn("Arithmetic mean", metric["average_definition"])
        self.assertIn("not necessarily", metric["average_definition"])

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_receives_unprocessed_rows_and_average_definition(
        self, mock_urlopen
    ):
        response = MagicMock()
        response.read.return_value = json.dumps({
            "message": {"content": "Verified sample analysis."}
        }).encode("utf-8")

        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        mock_urlopen.return_value = context

        factual = calculate_factual_insights(self.df)
        explain_factual_insights(factual)

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        prompt = payload["messages"][1]["content"]

        self.assertIn('"unprocessed_rows": 5996', prompt)
        self.assertIn("Arithmetic mean of non-null values", prompt)
        self.assertIn("Never guess missing or unprocessed row counts", prompt)
        self.assertIn("not necessarily a per-transaction value", prompt)


if __name__ == "__main__":
    unittest.main()
