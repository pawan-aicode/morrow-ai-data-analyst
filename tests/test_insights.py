import unittest

import pandas as pd

from app.insights import calculate_factual_insights


class TestFactualInsights(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "order_id": [1, 2, 3, 4, 5, 6],
            "order_date": [
                "2026-01-01", "2026-01-15",
                "2026-02-01", "2026-02-15",
                "2026-03-01", "2026-03-15",
            ],
            "category": [
                "A", "B", "A", "B", "A", "B"
            ],
            "sales": [100, 200, 300, 400, 500, 600],
        })

    def test_numeric_metrics_are_calculated_correctly(self):
        result = calculate_factual_insights(self.df)

        sales = result["numeric_metrics"][0]
        self.assertEqual(sales["column"], "sales")
        self.assertEqual(sales["total"], 2100.0)
        self.assertEqual(sales["average"], 350.0)
        self.assertEqual(sales["count"], 6)

    def test_identifier_columns_are_excluded(self):
        result = calculate_factual_insights(self.df)

        metric_columns = [
            item["column"] for item in result["numeric_metrics"]
        ]
        self.assertNotIn("order_id", metric_columns)

    def test_monthly_trend_is_calculated_correctly(self):
        result = calculate_factual_insights(self.df)

        trend = result["monthly_trends"][0]
        self.assertEqual(trend["highest_period"], "2026-03")
        self.assertEqual(trend["highest_value"], 1100.0)
        self.assertEqual(trend["lowest_period"], "2026-01")
        self.assertEqual(trend["lowest_value"], 300.0)

    def test_category_comparison_is_calculated_correctly(self):
        result = calculate_factual_insights(self.df)

        comparison = result["category_comparisons"][0]
        self.assertEqual(comparison["highest_category"], "B")
        self.assertEqual(comparison["highest_value"], 1200.0)
        self.assertEqual(comparison["lowest_category"], "A")
        self.assertEqual(comparison["lowest_value"], 900.0)
        self.assertAlmostEqual(
            comparison["percentage_difference"], 33.33, places=2
        )

    def test_sampling_metadata_is_preserved(self):
        self.df.attrs["source_rows"] = 6000
        self.df.attrs["is_sampled"] = True

        result = calculate_factual_insights(self.df)

        self.assertTrue(result["scope"]["is_sampled"])
        self.assertEqual(result["scope"]["source_rows"], 6000)
        self.assertEqual(result["scope"]["coverage_percent"], 0.1)
        self.assertTrue(result["limitations"])

    def test_missing_numeric_values_are_ignored(self):
        df = self.df.copy()
        df.loc[0, "sales"] = None

        result = calculate_factual_insights(df)
        sales = result["numeric_metrics"][0]

        self.assertEqual(sales["count"], 5)
        self.assertEqual(sales["total"], 2000.0)

    def test_no_category_comparison_when_only_one_category(self):
        df = self.df.copy()
        df["category"] = "A"

        result = calculate_factual_insights(df)
        self.assertEqual(result["category_comparisons"], [])

    def test_business_context_defaults_to_unknown(self):
        result = calculate_factual_insights(self.df)

        self.assertEqual(result["business_context"], {
            "currency": None,
            "row_granularity": None,
            "measure_meaning": None,
        })

    def test_explicit_business_context_is_preserved(self):
        context = {
            "currency": "INR",
            "row_granularity": "One row per completed order",
            "measure_meaning": "Completed order sales",
        }

        result = calculate_factual_insights(
            self.df, business_context=context
        )

        self.assertEqual(result["business_context"], context)

    def test_business_context_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            calculate_factual_insights(
                self.df,
                business_context={"currency": "INR", "guess": "anything"},
            )

    def test_business_context_rejects_non_text_values(self):
        with self.assertRaisesRegex(TypeError, "must be text"):
            calculate_factual_insights(
                self.df, business_context={"currency": 123}
            )

    def test_empty_dataframe_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_factual_insights(pd.DataFrame())


if __name__ == "__main__":
    unittest.main()
