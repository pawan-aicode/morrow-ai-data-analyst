import unittest

import pandas as pd

from app.insights import calculate_factual_insights


def make_df(months, values):
    dates = [f"2026-{month:02d}-15" for month in months]
    return pd.DataFrame({
        "order_date": dates,
        "sales": values,
    })


class TestMonthOverMonth(unittest.TestCase):

    def test_normal_monthly_changes_and_extremes(self):
        df = make_df([1, 2, 3, 4], [100, 150, 120, 180])
        trend = calculate_factual_insights(df)["monthly_trends"][0]

        changes = trend["monthly_changes"]
        self.assertEqual(changes[0]["comparison_status"], "first_period")
        self.assertEqual(changes[1]["absolute_change"], 50.0)
        self.assertEqual(changes[1]["percentage_change"], 50.0)
        self.assertEqual(changes[2]["absolute_change"], -30.0)
        self.assertEqual(changes[2]["percentage_change"], -20.0)

        self.assertEqual(trend["largest_increase"]["period"], "2026-04")
        self.assertEqual(trend["largest_decline"]["period"], "2026-03")

    def test_first_month_has_no_comparison(self):
        df = make_df([1], [100])
        result = calculate_factual_insights(df)
        self.assertEqual(result["monthly_trends"], [])

    def test_zero_previous_value_has_no_percentage(self):
        df = make_df([1, 2], [0, 100])
        trend = calculate_factual_insights(df)["monthly_trends"][0]
        change = trend["monthly_changes"][1]

        self.assertEqual(change["absolute_change"], 100.0)
        self.assertIsNone(change["percentage_change"])
        self.assertEqual(
            change["comparison_status"], "non_positive_previous"
        )

    def test_negative_previous_value_has_no_percentage(self):
        df = make_df([1, 2], [-100, 50])
        trend = calculate_factual_insights(df)["monthly_trends"][0]
        change = trend["monthly_changes"][1]

        self.assertEqual(change["absolute_change"], 150.0)
        self.assertIsNone(change["percentage_change"])
        self.assertEqual(
            change["comparison_status"], "non_positive_previous"
        )

    def test_missing_calendar_month_is_not_treated_as_zero(self):
        df = make_df([1, 3], [100, 300])
        trend = calculate_factual_insights(df)["monthly_trends"][0]
        change = trend["monthly_changes"][1]

        self.assertIsNone(change["absolute_change"])
        self.assertIsNone(change["percentage_change"])
        self.assertEqual(
            change["comparison_status"], "missing_calendar_month"
        )
        self.assertIsNone(trend["largest_increase"])
        self.assertIsNone(trend["largest_decline"])

    def test_partial_month_is_provisional_and_excluded_from_extremes(self):
        df = make_df([1, 2, 3], [100, 200, 1000])

        trend = calculate_factual_insights(
            df, as_of_date="2026-03-10"
        )["monthly_trends"][0]

        changes = trend["monthly_changes"]

        self.assertFalse(changes[1]["is_provisional"])
        self.assertTrue(changes[2]["is_provisional"])
        self.assertEqual(changes[2]["comparison_status"], "compared")
        self.assertEqual(changes[2]["percentage_change"], 400.0)

        # March's provisional +400% must not win the ranking.
        self.assertEqual(trend["largest_increase"]["period"], "2026-02")
        self.assertIsNone(trend["largest_decline"])
        self.assertEqual(trend["data_complete_through"], "2026-03-10")

    def test_first_month_can_be_provisional(self):
        df = make_df([1, 2], [100, 200])

        trend = calculate_factual_insights(
            df, as_of_date="2026-01-10"
        )["monthly_trends"][0]

        self.assertTrue(
            trend["monthly_changes"][0]["is_provisional"]
        )

    def test_complete_month_is_not_provisional(self):
        df = make_df([1, 2, 3], [100, 150, 300])

        trend = calculate_factual_insights(
            df, as_of_date="2026-03-31"
        )["monthly_trends"][0]

        self.assertFalse(
            trend["monthly_changes"][2]["is_provisional"]
        )
        self.assertEqual(
            trend["largest_increase"]["period"], "2026-03"
        )

    def test_partial_month_does_not_hide_missing_month_status(self):
        df = make_df([1, 3], [100, 300])

        trend = calculate_factual_insights(
            df, as_of_date="2026-03-10"
        )["monthly_trends"][0]

        march = trend["monthly_changes"][1]

        self.assertTrue(march["is_provisional"])
        self.assertEqual(
            march["comparison_status"], "missing_calendar_month"
        )
        self.assertIsNone(march["absolute_change"])
        self.assertIsNone(trend["largest_increase"])

    def test_no_completeness_date_preserves_existing_behavior(self):
        df = make_df([1, 2, 3], [100, 200, 1000])

        trend = calculate_factual_insights(df)["monthly_trends"][0]

        self.assertFalse(any(
            item["is_provisional"]
            for item in trend["monthly_changes"]
        ))
        self.assertEqual(
            trend["largest_increase"]["period"], "2026-03"
        )

    def test_month_after_completeness_date_is_outside_coverage(self):
        df = make_df([4, 5, 6, 7, 8], [100, 200, 300, 900, 1200])

        trend = calculate_factual_insights(
            df, as_of_date="2026-06-15"
        )["monthly_trends"][0]

        changes = trend["monthly_changes"]

        self.assertEqual(changes[0]["period_status"], "complete")
        self.assertEqual(changes[1]["period_status"], "complete")
        self.assertEqual(changes[2]["period_status"], "partial_period")
        self.assertEqual(
            changes[3]["period_status"], "after_completeness_date"
        )
        self.assertEqual(
            changes[4]["comparison_status"], "outside_coverage"
        )
        self.assertIsNone(changes[3]["absolute_change"])
        self.assertIsNone(changes[4]["percentage_change"])

        # July and August must not affect monthly extrema or MoM rankings.
        self.assertEqual(trend["highest_period"], "2026-05")
        self.assertEqual(trend["lowest_period"], "2026-04")
        self.assertEqual(trend["largest_increase"]["period"], "2026-05")
        self.assertIsNone(trend["largest_decline"])

    def test_partial_month_is_excluded_from_highest_lowest(self):
        df = make_df([1, 2, 3], [100, 200, 5000])

        trend = calculate_factual_insights(
            df, as_of_date="2026-03-10"
        )["monthly_trends"][0]

        self.assertEqual(trend["highest_period"], "2026-02")
        self.assertEqual(trend["lowest_period"], "2026-01")

    def test_all_months_after_completeness_date_have_no_extrema(self):
        df = make_df([5, 6], [100, 200])

        trend = calculate_factual_insights(
            df, as_of_date="2026-04-30"
        )["monthly_trends"][0]

        self.assertIsNone(trend["highest_period"])
        self.assertIsNone(trend["lowest_period"])
        self.assertIsNone(trend["largest_increase"])
        self.assertIsNone(trend["largest_decline"])
        self.assertEqual(
            trend["monthly_changes"][0]["period_status"],
            "after_completeness_date",
        )

    def test_completeness_date_at_month_end_marks_month_complete(self):
        df = make_df([1, 2, 3], [100, 200, 300])

        trend = calculate_factual_insights(
            df, as_of_date="2026-03-31"
        )["monthly_trends"][0]

        self.assertEqual(
            trend["monthly_changes"][2]["period_status"], "complete"
        )
        self.assertFalse(trend["monthly_changes"][2]["is_provisional"])

    def test_sampling_metadata_does_not_disappear(self):
        df = make_df([1, 2], [100, 150])
        df.attrs["source_rows"] = 1000
        df.attrs["is_sampled"] = True

        result = calculate_factual_insights(df)
        self.assertTrue(result["scope"]["is_sampled"])
        self.assertEqual(result["scope"]["source_rows"], 1000)
        self.assertEqual(result["monthly_trends"][0]["monthly_changes"][1]["absolute_change"], 50.0)


if __name__ == "__main__":
    unittest.main()
