import unittest

import pandas as pd

from app.profiling import profile_dataframe


class TestDataProfiling(unittest.TestCase):

    def test_dataset_overview(self):
        df = pd.DataFrame({
            "sales": [100, 200, 300],
            "city": ["Delhi", "Mumbai", "Delhi"],
        })

        result = profile_dataframe(df)

        overview = result["overview"]

        self.assertEqual(overview["loaded_rows"], 3)
        self.assertEqual(overview["total_rows"], 3)
        self.assertEqual(overview["columns"], 2)
        self.assertFalse(overview["is_sampled"])

    def test_numeric_statistics(self):
        df = pd.DataFrame({
            "sales": [100, 200, 300, 400],
        })

        result = profile_dataframe(df)
        column = result["columns"][0]

        self.assertEqual(column["type"], "numeric")
        self.assertEqual(column["statistics"]["min"], 100)
        self.assertEqual(column["statistics"]["max"], 400)
        self.assertEqual(column["statistics"]["mean"], 250)
        self.assertEqual(column["statistics"]["median"], 250)

    def test_missing_values(self):
        df = pd.DataFrame({
            "name": ["A", None, "C", None],
        })

        result = profile_dataframe(df)
        column = result["columns"][0]

        self.assertEqual(column["missing"], 2)
        self.assertEqual(column["missing_percent"], 50)
        self.assertTrue(any(
            issue["severity"] == "high"
            for issue in result["issues"]
        ))

    def test_low_missing_values_are_reported(self):
        df = pd.DataFrame({
            "sales": [1200, 800, None, 1500, 1500, 950],
        })

        result = profile_dataframe(df)

        missing_issue = next(
            issue for issue in result["issues"]
            if issue["column"] == "sales"
            and "missing" in issue["issue"]
        )

        self.assertEqual(missing_issue["severity"], "medium")
        self.assertIn("16.67%", missing_issue["issue"])

    def test_identifier_columns_excluded_from_recommendations(self):
        df = pd.DataFrame({
            "order_id": [101, 102, 103, 104],
            "customer_id": [1, 2, 3, 4],
            "order_date": [
                "2026-01-01", "2026-01-02",
                "2026-01-03", "2026-01-04",
            ],
            "sales": [100, 200, 300, 400],
            "category": ["A", "B", "A", "B"],
        })

        result = profile_dataframe(df)
        recommendations = " ".join(result["recommendations"])

        self.assertNotIn("order_id", recommendations)
        self.assertNotIn("customer_id", recommendations)
        self.assertIn("sales", recommendations)
        self.assertIn("category", recommendations)

    def test_camel_case_identifier_columns_are_excluded(self):
        from app.profiling import _is_identifier_column

        self.assertTrue(_is_identifier_column("customerId"))
        self.assertTrue(_is_identifier_column("orderId"))
        self.assertTrue(_is_identifier_column("userUUID"))
        self.assertFalse(_is_identifier_column("salesAmount"))

    def test_identifier_filter_handles_camel_case_recommendations(self):
        df = pd.DataFrame({
            "customerId": [1, 2, 3, 4],
            "salesAmount": [100, 200, 300, 400],
        })

        result = profile_dataframe(df)
        recommendations = " ".join(result["recommendations"])

        self.assertNotIn("customerId", recommendations)
        self.assertIn("salesAmount", recommendations)

    def test_high_cardinality_categories_not_recommended(self):
        df = pd.DataFrame({
            "name": [
                "A", "B", "C", "D", "E", "F",
            ],
            "sales": [100, 200, 300, 400, 500, 600],
        })

        result = profile_dataframe(df)
        recommendations = " ".join(result["recommendations"])

        self.assertNotIn("name", recommendations)
        self.assertIn("sales", recommendations)

    def test_duplicate_rows(self):
        df = pd.DataFrame({
            "id": [1, 2, 2, 3],
            "city": ["Delhi", "Mumbai", "Mumbai", "Pune"],
        })

        result = profile_dataframe(df)

        self.assertEqual(result["overview"]["duplicate_rows"], 1)

    def test_date_detection(self):
        df = pd.DataFrame({
            "order_date": [
                "2026-01-01",
                "2026-02-01",
                "2026-03-01",
            ],
        })

        result = profile_dataframe(df)
        column = result["columns"][0]

        self.assertEqual(column["type"], "date")
        self.assertIn("earliest", column["statistics"])
        self.assertIn("latest", column["statistics"])

    def test_categorical_top_values(self):
        df = pd.DataFrame({
            "city": ["Delhi", "Delhi", "Mumbai", "Pune", "Delhi"],
        })

        result = profile_dataframe(df)
        column = result["columns"][0]

        self.assertEqual(column["type"], "categorical")
        self.assertEqual(column["top_values"][0]["value"], "Delhi")
        self.assertEqual(column["top_values"][0]["count"], 3)

    def test_sample_coverage(self):
        df = pd.DataFrame({
            "sales": [100, 200, 300],
        })

        result = profile_dataframe(
            df,
            source_rows=10000,
            is_sampled=True,
        )

        self.assertTrue(result["overview"]["is_sampled"])
        self.assertEqual(result["overview"]["total_rows"], 10000)
        self.assertEqual(result["overview"]["coverage_percent"], 0.03)

    def test_sampled_dataset_can_have_unknown_total(self):
        df = pd.DataFrame({"sales": [100, 200, 300]})

        result = profile_dataframe(df, is_sampled=True)

        self.assertTrue(result["overview"]["is_sampled"])
        self.assertIsNone(result["overview"]["total_rows"])
        self.assertIsNone(result["overview"]["coverage_percent"])
        self.assertEqual(result["overview"]["loaded_rows"], 3)

    def test_empty_dataframe_rejected(self):
        with self.assertRaises(ValueError):
            profile_dataframe(pd.DataFrame())

    def test_invalid_source_row_count_rejected(self):
        df = pd.DataFrame({"sales": [100, 200]})

        with self.assertRaises(ValueError):
            profile_dataframe(df, source_rows=1)


if __name__ == "__main__":
    unittest.main()
