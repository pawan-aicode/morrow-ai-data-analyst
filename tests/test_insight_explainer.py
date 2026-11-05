import json
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.insights import calculate_factual_insights
from app.insight_explainer import (
    explain_factual_insights,
    _validate_explanation,
)


class TestInsightExplainer(unittest.TestCase):

    def setUp(self):
        df = pd.DataFrame({
            "order_id": [1, 2, 3, 4, 5, 6],
            "order_date": [
                "2026-01-01", "2026-01-15",
                "2026-02-01", "2026-02-15",
                "2026-03-01", "2026-03-15",
            ],
            "category": ["A", "B", "A", "B", "A", "B"],
            "sales": [100, 200, 300, 400, 500, 600],
        })
        self.factual = calculate_factual_insights(df)

    def _response(self, content):
        response = MagicMock()
        response.read.return_value = json.dumps({
            "message": {"content": content}
        }).encode("utf-8")

        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        return context

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_valid_explanation(self, mock_urlopen):
        mock_urlopen.return_value = self._response(
            "Sales increased across the observed months."
        )
        result = explain_factual_insights(self.factual)
        self.assertEqual(
            result, "Sales increased across the observed months."
        )

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_uses_calculated_facts(self, mock_urlopen):
        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(self.factual)

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        prompt = payload["messages"][1]["content"]

        self.assertIn('"total": 2100.0', prompt)
        self.assertIn('"highest_period": "2026-03"', prompt)
        self.assertIn("Never invent, estimate, recalculate, or round additional numbers", prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_requires_five_analysis_sections(self, mock_urlopen):
        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(self.factual)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        for heading in (
            "EXECUTIVE SUMMARY",
            "PERFORMANCE FINDINGS",
            "RISKS AND DATA LIMITATIONS",
            "BUSINESS INTERPRETATION",
            "RECOMMENDED NEXT ACTIONS",
        ):
            self.assertIn(heading, prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_handles_partial_and_outside_coverage_periods(
        self, mock_urlopen
    ):
        factual = dict(self.factual)
        factual["monthly_trends"] = [{
            "measure": "sales",
            "monthly_changes": [
                {
                    "period": "2026-03",
                    "period_status": "partial_period",
                    "comparison_status": "compared",
                    "percentage_change": 20.0,
                },
                {
                    "period": "2026-04",
                    "period_status": "after_completeness_date",
                    "comparison_status": "outside_coverage",
                    "percentage_change": None,
                },
            ],
            "largest_increase": None,
            "largest_decline": None,
        }]

        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(factual)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        self.assertIn("partial_period", prompt)
        self.assertIn("after_completeness_date", prompt)
        self.assertIn("outside declared data coverage", prompt)
        self.assertIn("Never rank excluded periods", prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_requires_evidence_linked_recommendations(
        self, mock_urlopen
    ):
        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(self.factual)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        self.assertIn(
            "specific, practical next steps linked to observed findings",
            prompt,
        )
        self.assertIn("Never invent business events", prompt)
        self.assertIn("Distinguish observations from hypotheses", prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_receives_explicit_business_context(self, mock_urlopen):
        factual = dict(self.factual)
        factual["business_context"] = {
            "currency": "INR",
            "row_granularity": "One row per completed order",
            "measure_meaning": "Completed order sales",
        }

        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(factual)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        self.assertIn('"currency": "INR"', prompt)
        self.assertIn('"row_granularity": "One row per completed order"', prompt)
        self.assertIn('"measure_meaning": "Completed order sales"', prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_prompt_prevents_unsupported_currency_and_month_claims(
        self, mock_urlopen
    ):
        mock_urlopen.return_value = self._response("Analysis.")
        explain_factual_insights(self.factual)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        self.assertIn("Otherwise describe amounts without a currency", prompt)
        self.assertIn(
            "It does not mean calendar months are missing.", prompt
        )
        self.assertIn(
            "Do not claim statistical unreliability merely because a dataset has",
            " ".join(prompt.split()),
        )

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_sample_warning_reaches_prompt(self, mock_urlopen):
        sampled = dict(self.factual)
        sampled["scope"] = {
            "loaded_rows": 5000,
            "source_rows": 6000,
            "is_sampled": True,
            "coverage_percent": 83.33,
        }
        sampled["limitations"] = [
            "Results describe only the loaded sample."
        ]

        mock_urlopen.return_value = self._response("Sample analysis.")
        explain_factual_insights(sampled)

        request = mock_urlopen.call_args.args[0]
        prompt = json.loads(request.data)["messages"][1]["content"]

        self.assertIn('"is_sampled": true', prompt)
        self.assertIn('"source_rows": 6000', prompt)
        self.assertIn("loaded sample", prompt)

    def test_validator_rejects_unsupported_currency(self):
        factual = dict(self.factual)
        factual["business_context"] = {"currency": None}

        issues = _validate_explanation(
            "Total sales were $19.45 million.", factual
        )

        self.assertTrue(any("Unsupported currency symbol" in x for x in issues))

    def test_validator_rejects_unconfirmed_completeness_claim(self):
        issues = _validate_explanation(
            "The dataset is complete and no missing calendar months exist.",
            self.factual,
        )

        self.assertTrue(any("Completeness is not assessed" in x for x in issues))

    def test_validator_rejects_contradictory_average_description(self):
        factual = dict(self.factual)
        factual["business_context"] = {
            "currency": "INR (₹)",
            "row_granularity": "One row per completed order",
            "measure_meaning": "Completed order sales",
        }

        issues = _validate_explanation(
            "The average does not necessarily represent a per-transaction value.",
            factual,
        )

        self.assertTrue(any("row granularity establishes" in x for x in issues))

    def test_validator_rejects_average_transaction_contradiction_wording(self):
        factual = dict(self.factual)
        factual["business_context"] = {
            "currency": "INR (₹)",
            "row_granularity": "One row per completed order",
            "measure_meaning": "Total sales value of a completed order",
        }

        issues = _validate_explanation(
            "The average does not necessarily reflect per-transaction figures.",
            factual,
        )

        self.assertTrue(
            any("row granularity establishes" in issue for issue in issues)
        )

    def test_validator_accepts_supported_explanation(self):
        factual = dict(self.factual)
        factual["business_context"] = {
            "currency": "INR (₹)",
            "row_granularity": "One row per completed order",
            "measure_meaning": "Completed order sales",
        }

        issues = _validate_explanation(
            "Total sales were ₹2,100. Average sales per order were ₹350.",
            factual,
        )

        self.assertEqual(issues, [])

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_invalid_first_response_triggers_one_retry(self, mock_urlopen):
        factual = dict(self.factual)
        factual["business_context"] = {"currency": "INR (₹)"}

        mock_urlopen.side_effect = [
            self._response("Total sales were $19.45 million."),
            self._response("Total sales were ₹19.45 million."),
        ]

        result = explain_factual_insights(factual)

        self.assertEqual(result, "Total sales were ₹19.45 million.")
        self.assertEqual(mock_urlopen.call_count, 2)

        retry_request = mock_urlopen.call_args.args[0]
        retry_prompt = json.loads(retry_request.data)["messages"][1]["content"]
        self.assertIn("VALIDATION FEEDBACK", retry_prompt)
        self.assertIn("Unsupported currency symbol", retry_prompt)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_ollama_failure(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("connection refused")

        with self.assertRaisesRegex(RuntimeError, "Check Ollama"):
            explain_factual_insights(self.factual)

    @patch("app.insight_explainer.urllib.request.urlopen")
    def test_empty_response(self, mock_urlopen):
        mock_urlopen.return_value = self._response("   ")

        with self.assertRaisesRegex(RuntimeError, "empty explanation"):
            explain_factual_insights(self.factual)

    def test_invalid_input(self):
        with self.assertRaises(TypeError):
            explain_factual_insights("not factual data")


if __name__ == "__main__":
    unittest.main()
