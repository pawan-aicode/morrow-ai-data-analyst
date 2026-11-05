import unittest

from app.root_cause import build_root_cause_brief, _validate_root_cause_explanation


class TestRootCause(unittest.TestCase):

    def make_evidence(self):
        return {
            "scope": {"loaded_rows": 100, "valid_sales_date_rows": 100},
            "evidence_quality": {"analysis_status": "user_confirmed"},
            "monthly_sales": [
                {
                    "period": "2026-01",
                    "value": 10000,
                    "period_status": "complete",
                    "comparison_status": "first_period",
                },
                {
                    "period": "2026-02",
                    "value": 8000,
                    "previous_period": "2026-01",
                    "previous_value": 10000,
                    "absolute_change": -2000,
                    "percentage_change": -20,
                    "period_status": "complete",
                    "comparison_status": "compared",
                    "evidence_status": "user_confirmed",
                },
            ],
            "category_contributions": [
                {
                    "period": "2026-02",
                    "previous_period": "2026-01",
                    "evidence_status": "user_confirmed",
                    "category_changes": [
                        {"category": "Electronics", "absolute_change": -1500},
                        {"category": "Furniture", "absolute_change": -500},
                        {"category": "Clothing", "absolute_change": 200},
                    ],
                }
            ],
            "product_performance": [],
            "monthly_order_metrics": [
                {
                    "period": "2026-01",
                    "order_count": 100,
                    "average_order_value": 100,
                    "period_status": "complete",
                },
                {
                    "period": "2026-02",
                    "order_count": 80,
                    "average_order_value": 100,
                    "period_status": "complete",
                },
            ],
        }

    def test_latest_eligible_decline_is_selected(self):
        brief = build_root_cause_brief(self.make_evidence())
        self.assertEqual(brief["status"], "decline_detected")
        self.assertEqual(brief["sales_decline"]["current_period"], "2026-02")
        self.assertEqual(brief["sales_decline"]["percentage_change"], -20)

    def test_largest_category_decline_is_ranked_first(self):
        brief = build_root_cause_brief(self.make_evidence())
        self.assertEqual(
            brief["category_changes"]["declines"][0]["name"],
            "Electronics",
        )
        self.assertEqual(
            brief["category_changes"]["declines"][0]["absolute_change"],
            -1500,
        )

    def test_order_count_and_aov_are_compared(self):
        brief = build_root_cause_brief(self.make_evidence())
        self.assertEqual(
            brief["order_metrics"]["order_count"]["percentage_change"],
            -20,
        )
        self.assertEqual(
            brief["order_metrics"]["average_order_value"]["percentage_change"],
            0,
        )

    def test_partial_period_decline_is_not_diagnosed(self):
        evidence = self.make_evidence()
        evidence["monthly_sales"][1]["period_status"] = "partial_period"
        evidence["monthly_sales"][1]["comparison_status"] = "partial_period"
        brief = build_root_cause_brief(evidence)
        self.assertEqual(brief["status"], "no_eligible_decline")

    def test_missing_category_data_is_reported_as_unavailable(self):
        evidence = self.make_evidence()
        evidence["category_contributions"] = []
        brief = build_root_cause_brief(evidence)
        self.assertFalse(brief["category_changes"]["available"])

    def test_ai_numeric_claims_are_rejected(self):
        self.assertTrue(
            _validate_root_cause_explanation("Sales declined by 6.87 percent.")
        )

    def test_ai_currency_symbols_are_rejected(self):
        self.assertTrue(
            _validate_root_cause_explanation("Revenue reached $500.")
        )

    def test_qualitative_ai_interpretation_is_allowed(self):
        self.assertEqual(
            _validate_root_cause_explanation(
                "Sales declined. Category changes are associations, not causes."
            ),
            [],
        )

    def test_diagnosis_uses_evidence_without_customer_visit_claims(self):
        from app.root_cause import explain_root_cause

        brief = build_root_cause_brief(self.make_evidence())
        result = explain_root_cause(brief)

        self.assertIn("Both recorded order count and sales declined", result)
        self.assertNotIn("Average order value decreased", result)
        self.assertIn("Electronics", result)
        self.assertIn("does not establish", result)
        self.assertNotIn("customer visits did not decrease", result.lower())
        self.assertNotIn("purchasing fewer items per visit", result.lower())

    def test_diagnosis_rejects_missing_decline(self):
        from app.root_cause import explain_root_cause

        with self.assertRaises(ValueError):
            explain_root_cause({"status": "no_eligible_decline"})

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(TypeError):
            build_root_cause_brief(None)


if __name__ == "__main__":
    unittest.main()
