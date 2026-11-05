
from app.recommendations import generate_recommendations


def make_evidence():
    return {
        "selected_columns": {
            "sales": "sales",
            "date": "order_date",
            "category": "category",
            "product": None,
            "order_id": "order_id",
        },
        "evidence_quality": {"analysis_status": "provisional"},
        "monthly_sales": [],
        "category_contributions": [],
        "product_performance": [],
        "monthly_order_metrics": [
            {
                "period": "2025-05",
                "order_count": 100,
                "average_order_value": 500,
                "period_status": "not_assessed",
                "evidence_status": "provisional",
            },
            {
                "period": "2025-06",
                "order_count": 90,
                "average_order_value": 450,
                "period_status": "not_assessed",
                "evidence_status": "provisional",
            },
        ],
    }


def test_order_count_decline_is_detected():
    results = generate_recommendations(make_evidence())
    item = next(r for r in results if r["recommendation_type"] == "order_count_decline")
    assert item["evidence"]["percentage_change"] == -10
    assert item["evidence_status"] == "provisional"


def test_aov_decline_is_detected():
    results = generate_recommendations(make_evidence())
    item = next(r for r in results if r["recommendation_type"] == "aov_decline")
    assert item["evidence"]["percentage_change"] == -10


def test_non_consecutive_months_are_not_compared():
    evidence = make_evidence()
    evidence["monthly_order_metrics"][1]["period"] = "2025-07"
    results = generate_recommendations(evidence)
    assert not any(
        r["recommendation_type"] in {"order_count_decline", "aov_decline"}
        for r in results
    )


def test_incomplete_period_is_not_compared():
    evidence = make_evidence()
    evidence["monthly_order_metrics"][1]["period_status"] = "partial_period"
    results = generate_recommendations(evidence)
    assert not any(
        r["recommendation_type"] in {"order_count_decline", "aov_decline"}
        for r in results
    )


def test_sales_action_does_not_mention_unselected_product():
    evidence = make_evidence()
    evidence["monthly_sales"] = [{
        "period": "2025-06",
        "previous_period": "2025-05",
        "value": 900,
        "previous_value": 1000,
        "absolute_change": -100,
        "percentage_change": -10,
        "comparison_status": "compared",
        "evidence_status": "provisional",
    }]
    result = generate_recommendations(evidence)
    sales = next(r for r in result if r["recommendation_type"] == "sales_decline")
    assert "product-level" not in sales["recommended_action"]
    assert "category-level" in sales["recommended_action"]


def test_multiple_monthly_order_declines_are_consolidated():
    evidence = make_evidence()
    evidence["monthly_order_metrics"] = [
        {
            "period": f"2025-0{month}",
            "order_count": count,
            "average_order_value": aov,
            "period_status": "not_assessed",
            "evidence_status": "provisional",
        }
        for month, count, aov in [
            (1, 120, 500),
            (2, 110, 480),
            (3, 100, 460),
            (4, 90, 440),
        ]
    ]

    results = generate_recommendations(evidence)
    order_items = [
        item for item in results
        if item["recommendation_type"] == "order_count_decline"
    ]
    aov_items = [
        item for item in results
        if item["recommendation_type"] == "aov_decline"
    ]

    assert len(order_items) == 1
    assert len(aov_items) == 1
    assert order_items[0]["evidence"]["decline_period_count"] == 3
    assert aov_items[0]["evidence"]["decline_period_count"] == 3
