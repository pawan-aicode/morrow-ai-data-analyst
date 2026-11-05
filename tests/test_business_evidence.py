import unittest

import pandas as pd

from app.business_evidence import calculate_business_evidence


class TestBusinessEvidence(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame({
            "order_id": [1, 1, 2, 3, 4, 4],
            "order_date": [
                "2026-01-05", "2026-01-05",
                "2026-01-15", "2026-02-05",
                "2026-02-10", "2026-02-10",
            ],
            "category": [
                "Electronics", "Furniture",
                "Electronics", "Electronics",
                "Furniture", "Electronics",
            ],
            "product": [
                "Phone", "Desk", "Phone",
                "Phone", "Chair", "Laptop",
            ],
            "sales": [600, 400, 500, 700, 300, 500],
        })

    def calculate(self, **kwargs):
        return calculate_business_evidence(
            self.df,
            sales_col="sales",
            date_col="order_date",
            **kwargs,
        )

    def test_monthly_sales_are_calculated(self):
        result = self.calculate()

        self.assertEqual(
            [item["value"] for item in result["monthly_sales"]],
            [1500.0, 1500.0],
        )

    def test_category_contributions_are_calculated(self):
        result = self.calculate(category_col="category")

        changes = result["category_contributions"][0]["category_changes"]
        values = {item["category"]: item["absolute_change"] for item in changes}

        self.assertEqual(values["Electronics"], 100.0)
        self.assertEqual(values["Furniture"], -100.0)

    def test_product_changes_are_calculated(self):
        result = self.calculate(product_col="product")

        changes = result["product_performance"][0]["product_changes"]
        values = {item["product"]: item["absolute_change"] for item in changes}

        self.assertEqual(values["Phone"], -400.0)
        self.assertEqual(values["Laptop"], 500.0)
        self.assertEqual(values["Chair"], 300.0)

    def test_order_count_uses_distinct_order_ids(self):
        result = self.calculate(order_id_col="order_id")

        metrics = result["monthly_order_metrics"]

        self.assertEqual(metrics[0]["order_count"], 2)
        self.assertEqual(metrics[1]["order_count"], 2)

    def test_average_order_value_uses_monthly_sales_and_distinct_orders(self):
        result = self.calculate(order_id_col="order_id")

        metrics = result["monthly_order_metrics"]

        self.assertEqual(metrics[0]["average_order_value"], 750.0)
        self.assertEqual(metrics[1]["average_order_value"], 750.0)

    def test_missing_calendar_month_is_not_compared(self):
        df = self.df.copy()
        df["order_date"] = [
            "2026-01-05", "2026-01-05", "2026-01-15",
            "2026-03-05", "2026-03-10", "2026-03-10",
        ]

        result = calculate_business_evidence(
            df, "sales", "order_date"
        )

        self.assertEqual(
            result["monthly_sales"][1]["comparison_status"],
            "missing_calendar_month",
        )
        self.assertIsNone(
            result["monthly_sales"][1]["percentage_change"]
        )

    def test_invalid_sales_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Sales column not found"):
            calculate_business_evidence(
                self.df, "unknown_sales", "order_date"
            )

    def test_invalid_order_id_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Order ID column not found"):
            self.calculate(order_id_col="unknown_id")

    def test_cross_month_order_is_assigned_to_earliest_month(self):
        df = pd.DataFrame({
            "order_id": [1, 1, 2],
            "date": ["2026-01-30", "2026-02-02", "2026-02-10"],
            "sales": [100, 200, 300],
        })

        result = calculate_business_evidence(
            df, "sales", "date", order_id_col="order_id"
        )

        metrics = {
            item["period"]: item
            for item in result["monthly_order_metrics"]
        }

        self.assertEqual(metrics["2026-01"]["order_count"], 1)
        self.assertEqual(metrics["2026-01"]["sales"], 300.0)
        self.assertEqual(metrics["2026-01"]["average_order_value"], 300.0)

        self.assertEqual(metrics["2026-02"]["order_count"], 1)
        self.assertEqual(metrics["2026-02"]["sales"], 300.0)
        self.assertEqual(metrics["2026-02"]["average_order_value"], 300.0)

    def test_zero_previous_sales_has_no_percentage_change(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [0, 500],
        })

        result = calculate_business_evidence(df, "sales", "date")
        february = result["monthly_sales"][1]

        self.assertEqual(february["absolute_change"], 500.0)
        self.assertIsNone(february["percentage_change"])
        self.assertEqual(
            february["comparison_status"],
            "non_positive_previous",
        )

    def test_partial_current_month_is_excluded_from_contributions(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [100, 200],
            "category": ["A", "A"],
        })

        result = calculate_business_evidence(
            df,
            "sales",
            "date",
            category_col="category",
            as_of_date="2026-02-10",
        )

        self.assertEqual(result["category_contributions"], [])

    def test_missing_categories_are_grouped_as_unknown(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [100, 150],
            "category": [None, None],
        })

        result = calculate_business_evidence(
            df, "sales", "date", category_col="category"
        )

        changes = result["category_contributions"][0]["category_changes"]
        self.assertEqual(changes[0]["category"], "Unknown")
        self.assertEqual(changes[0]["absolute_change"], 50.0)



    def test_mixed_type_order_ids_are_handled_consistently(self):
        df = pd.DataFrame({
            "order_id": [123, "123"],
            "date": ["2026-01-05", "2026-01-06"],
            "sales": [100, 200],
        })

        result = calculate_business_evidence(
            df, "sales", "date", order_id_col="order_id"
        )

        self.assertEqual(
            result["monthly_order_metrics"][0]["order_count"], 1
        )
        self.assertEqual(
            result["monthly_order_metrics"][0]["average_order_value"],
            300.0,
        )

    def test_order_metrics_expose_partial_period_status(self):
        df = pd.DataFrame({
            "order_id": [1, 2],
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [100, 200],
        })

        result = calculate_business_evidence(
            df,
            "sales",
            "date",
            order_id_col="order_id",
            as_of_date="2026-02-10",
        )

        february = next(
            item for item in result["monthly_order_metrics"]
            if item["period"] == "2026-02"
        )

        self.assertEqual(february["period_status"], "partial_period")


    def test_partial_month_is_not_compared_in_monthly_sales(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [1000, 200],
        })

        result = calculate_business_evidence(
            df, "sales", "date", as_of_date="2026-02-10"
        )

        february = result["monthly_sales"][1]

        self.assertEqual(february["period_status"], "partial_period")
        self.assertIsNone(february["percentage_change"])
        self.assertIsNone(february["absolute_change"])
        self.assertEqual(
            february["comparison_status"], "partial_period"
        )

    def test_complete_months_can_be_compared(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [1000, 1200],
        })

        result = calculate_business_evidence(
            df, "sales", "date", as_of_date="2026-02-28"
        )

        february = result["monthly_sales"][1]

        self.assertEqual(february["period_status"], "complete")
        self.assertEqual(february["absolute_change"], 200.0)
        self.assertEqual(february["percentage_change"], 20.0)
        self.assertEqual(february["comparison_status"], "compared")


    def test_unverified_data_is_marked_provisional(self):
        result = self.calculate(category_col="category")

        quality = result["evidence_quality"]

        self.assertEqual(quality["completeness_status"], "not_assessed")
        self.assertEqual(quality["analysis_status"], "provisional")
        self.assertEqual(
            result["monthly_sales"][1]["evidence_status"],
            "provisional",
        )
        self.assertEqual(
            result["category_contributions"][0]["evidence_status"],
            "provisional",
        )

    def test_user_confirmed_completeness_is_exposed(self):
        result = calculate_business_evidence(
            self.df,
            "sales",
            "order_date",
            category_col="category",
            as_of_date="2026-02-28",
        )

        quality = result["evidence_quality"]

        self.assertEqual(quality["completeness_status"], "user_confirmed")
        self.assertEqual(quality["analysis_status"], "user_confirmed")
        self.assertEqual(quality["as_of_date"], "2026-02-28")
        self.assertEqual(quality["loaded_rows"], 6)
        self.assertEqual(quality["valid_rows"], 6)
        self.assertEqual(quality["excluded_rows"], 0)
        self.assertEqual(
            result["monthly_sales"][1]["evidence_status"],
            "user_confirmed",
        )
        self.assertEqual(
            result["category_contributions"][0]["evidence_status"],
            "user_confirmed",
        )


    def test_product_comparisons_include_evidence_status(self):
        result = self.calculate(
            product_col="product",
            as_of_date="2026-02-28",
        )

        comparison = result["product_performance"][0]
        self.assertEqual(comparison["evidence_status"], "user_confirmed")

    def test_partial_order_metrics_are_marked_partial(self):
        df = pd.DataFrame({
            "order_id": [1, 2],
            "date": ["2026-01-05", "2026-02-05"],
            "sales": [100, 200],
        })

        result = calculate_business_evidence(
            df,
            "sales",
            "date",
            order_id_col="order_id",
            as_of_date="2026-02-10",
        )

        february = next(
            item for item in result["monthly_order_metrics"]
            if item["period"] == "2026-02"
        )

        self.assertEqual(february["evidence_status"], "partial")

    def test_invalid_rows_are_counted_as_excluded(self):
        df = pd.DataFrame({
            "date": ["2026-01-05", "invalid-date", "2026-01-10"],
            "sales": [100, 200, "invalid-sales"],
        })

        result = calculate_business_evidence(df, "sales", "date")

        quality = result["evidence_quality"]
        self.assertEqual(quality["loaded_rows"], 3)
        self.assertEqual(quality["valid_rows"], 1)
        self.assertEqual(quality["excluded_rows"], 2)

if __name__ == "__main__":
    unittest.main()



class TestAutomaticPartialPeriodDetection(unittest.TestCase):

    def test_early_latest_cutoff_is_flagged_and_excluded(self):
        df = pd.DataFrame({
            "date": [
                "2026-01-05", "2026-01-31",
                "2026-02-05", "2026-02-28",
                "2026-03-01", "2026-03-07",
            ],
            "sales": [100, 200, 150, 250, 50, 60],
            "category": ["A", "A", "A", "B", "A", "B"],
            "order_id": [1, 2, 3, 4, 5, 6],
        })
        result = calculate_business_evidence(
            df, "sales", "date",
            category_col="category",
            order_id_col="order_id",
        )

        self.assertEqual(
            result["automatic_coverage_check"]["status"],
            "potentially_partial",
        )
        self.assertEqual(
            result["monthly_sales"][-1]["comparison_status"],
            "potentially_partial",
        )
        self.assertFalse(any(
            item["period"] == "2026-03"
            for item in result["category_contributions"]
        ))
        march = next(
            item for item in result["monthly_order_metrics"]
            if item["period"] == "2026-03"
        )
        self.assertEqual(march["period_status"], "potentially_partial")

    def test_normal_historical_cutoff_is_not_flagged(self):
        df = pd.DataFrame({
            "date": [
                "2026-01-05", "2026-01-20",
                "2026-02-05", "2026-02-19",
                "2026-03-01", "2026-03-18",
            ],
            "sales": [100, 200, 150, 250, 50, 60],
        })
        result = calculate_business_evidence(df, "sales", "date")
        self.assertEqual(
            result["automatic_coverage_check"]["status"],
            "no_anomaly_detected",
        )

    def test_manual_completeness_date_overrides_auto_detection(self):
        df = pd.DataFrame({
            "date": [
                "2026-01-05", "2026-01-31",
                "2026-02-05", "2026-02-28",
                "2026-03-01", "2026-03-07",
            ],
            "sales": [100, 200, 150, 250, 50, 60],
        })
        result = calculate_business_evidence(
            df, "sales", "date", as_of_date="2026-03-07"
        )
        self.assertEqual(
            result["automatic_coverage_check"]["status"],
            "manual_completeness_date_supplied",
        )
        self.assertEqual(
            result["monthly_sales"][-1]["comparison_status"],
            "partial_period",
        )
