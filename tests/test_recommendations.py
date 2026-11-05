import unittest

from app.recommendations import generate_recommendations


class TestRecommendations(unittest.TestCase):

    def make_evidence(self):
        return {
            "scope": {
                "loaded_rows": 100,
                "valid_sales_date_rows": 100,
            },
            "evidence_quality": {
                "analysis_status": "user_confirmed",
                "completeness_status": "user_confirmed",
                "as_of_date": "2026-02-28",
            },
            "monthly_sales": [
                {
                    "period": "2026-01",
                    "value": 10000.0,
                    "period_status": "complete",
                    "evidence_status": "user_confirmed",
                    "comparison_status": "first_period",
                    "previous_period": None,
                    "previous_value": None,
                    "absolute_change": None,
                    "percentage_change": None,
                },
                {
                    "period": "2026-02",
                    "value": 8000.0,
                    "period_status": "complete",
                    "evidence_status": "user_confirmed",
                    "comparison_status": "compared",
                    "previous_period": "2026-01",
                    "previous_value": 10000.0,
                    "absolute_change": -2000.0,
                    "percentage_change": -20.0,
                },
            ],
            "category_contributions": [
                {
                    "period": "2026-02",
                    "previous_period": "2026-01",
                    "evidence_status": "user_confirmed",
                    "category_changes": [
                        {
                            "category": "Electronics",
                            "absolute_change": -1500.0,
                        },
                        {
                            "category": "Furniture",
                            "absolute_change": -500.0,
                        },
                    ],
                }
            ],
            "product_performance": [],
            "monthly_order_metrics": [],
        }

    def test_confirmed_sales_decline_generates_recommendation(self):
        recommendations = generate_recommendations(
            self.make_evidence()
        )

        self.assertTrue(recommendations)
        self.assertTrue(
            any(
                item["recommendation_type"] == "sales_decline"
                for item in recommendations
            )
        )

    def test_recommendation_references_supporting_periods(self):
        recommendations = generate_recommendations(
            self.make_evidence()
        )

        item = next(
            item for item in recommendations
            if item["recommendation_type"] == "sales_decline"
        )

        self.assertEqual(
            item["evidence"]["current_period"], "2026-02"
        )
        self.assertEqual(
            item["evidence"]["previous_period"], "2026-01"
        )
        self.assertEqual(
            item["evidence"]["absolute_change"], -2000.0
        )

    def test_recommendation_does_not_claim_a_cause(self):
        recommendations = generate_recommendations(
            self.make_evidence()
        )

        combined = " ".join(
            item["recommended_action"].lower()
            for item in recommendations
        )

        self.assertNotIn("caused by", combined)
        self.assertNotIn("because of", combined)

    def test_unassessed_data_is_not_presented_as_confirmed(self):
        evidence = self.make_evidence()
        evidence["evidence_quality"]["analysis_status"] = "provisional"
        evidence["evidence_quality"]["completeness_status"] = "not_assessed"

        for item in evidence["monthly_sales"]:
            item["period_status"] = "not_assessed"
            item["evidence_status"] = "provisional"

        recommendations = generate_recommendations(evidence)

        self.assertFalse(
            any(
                item["evidence_status"] == "user_confirmed"
                for item in recommendations
            )
        )

    def test_partial_period_does_not_generate_confirmed_recommendation(self):
        evidence = self.make_evidence()
        current = evidence["monthly_sales"][-1]
        current["period_status"] = "partial_period"
        current["evidence_status"] = "partial"
        current["comparison_status"] = "partial_period"
        current["absolute_change"] = None
        current["percentage_change"] = None

        recommendations = generate_recommendations(evidence)

        self.assertFalse(
            any(
                item["evidence_status"] == "user_confirmed"
                for item in recommendations
            )
        )

    def test_missing_calendar_month_does_not_generate_sales_decline(self):
        evidence = self.make_evidence()
        current = evidence["monthly_sales"][-1]
        current["comparison_status"] = "missing_calendar_month"

        recommendations = generate_recommendations(evidence)

        self.assertFalse(
            any(
                item["recommendation_type"] == "sales_decline"
                for item in recommendations
            )
        )

    def test_small_decline_does_not_trigger_recommendation(self):
        evidence = self.make_evidence()
        current = evidence["monthly_sales"][-1]
        current["value"] = 9950.0
        current["absolute_change"] = -50.0
        current["percentage_change"] = -0.5

        recommendations = generate_recommendations(evidence)

        self.assertFalse(
            any(
                item["recommendation_type"] == "sales_decline"
                for item in recommendations
            )
        )

    def test_invalid_input_is_rejected(self):
        with self.assertRaises((TypeError, ValueError)):
            generate_recommendations(None)


    def test_overall_provisional_quality_overrides_confirmed_row(self):
        evidence = self.make_evidence()
        evidence["evidence_quality"]["analysis_status"] = "provisional"

        recommendations = generate_recommendations(evidence)

        self.assertTrue(recommendations)
        self.assertTrue(all(
            item["evidence_status"] == "provisional"
            for item in recommendations
        ))

    def test_missing_evidence_quality_is_not_confirmed(self):
        evidence = self.make_evidence()
        evidence.pop("evidence_quality")

        recommendations = generate_recommendations(evidence)

        self.assertTrue(recommendations)
        self.assertTrue(all(
            item["evidence_status"] == "provisional"
            for item in recommendations
        ))

    def test_non_finite_threshold_is_rejected(self):
        for threshold in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    generate_recommendations(
                        self.make_evidence(),
                        decline_threshold_percent=threshold,
                    )


    def test_largest_category_decline_is_identified(self):
        recommendations = generate_recommendations(
            self.make_evidence()
        )

        category = next(
            item for item in recommendations
            if item["recommendation_type"] == "category_decline"
        )

        self.assertEqual(category["evidence"]["category"], "Electronics")
        self.assertEqual(category["evidence"]["absolute_change"], -1500.0)
        self.assertEqual(category["evidence"]["current_period"], "2026-02")

    def test_category_recommendation_requires_matching_period(self):
        evidence = self.make_evidence()
        evidence["category_contributions"][0]["period"] = "2026-03"

        recommendations = generate_recommendations(evidence)

        self.assertFalse(any(
            item["recommendation_type"] == "category_decline"
            for item in recommendations
        ))

    def test_product_decline_is_identified(self):
        evidence = self.make_evidence()
        evidence["product_performance"] = [{
            "period": "2026-02",
            "previous_period": "2026-01",
            "evidence_status": "user_confirmed",
            "product_changes": [
                {"product": "Phone", "absolute_change": -1200.0},
                {"product": "Laptop", "absolute_change": -300.0},
                {"product": "Tablet", "absolute_change": 200.0},
            ],
        }]

        recommendations = generate_recommendations(evidence)

        product = next(
            item for item in recommendations
            if item["recommendation_type"] == "product_decline"
        )

        self.assertEqual(product["evidence"]["product"], "Phone")
        self.assertEqual(product["evidence"]["absolute_change"], -1200.0)

    def test_provisional_category_is_not_confirmed(self):
        evidence = self.make_evidence()
        evidence["evidence_quality"]["analysis_status"] = "provisional"
        evidence["category_contributions"][0]["evidence_status"] = "provisional"

        recommendations = generate_recommendations(evidence)

        category = next(
            item for item in recommendations
            if item["recommendation_type"] == "category_decline"
        )

        self.assertEqual(category["evidence_status"], "provisional")


if __name__ == "__main__":
    unittest.main()
