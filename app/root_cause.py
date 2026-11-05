"""Evidence-based business diagnosis for Morrow."""

import json
import re
import math
import urllib.request
import urllib.error

from app.agent import MODEL, OLLAMA_URL


def _number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_root_cause_explanation(explanation):
    """Reject numerical claims in the AI-generated interpretation."""
    issues = []
    if re.search(r"\d", explanation):
        issues.append("Unsupported numerical claim or date.")
    if any(symbol in explanation for symbol in ("₹", "$", "€", "£")):
        issues.append("Unsupported currency symbol.")
    return issues


def build_root_cause_brief(evidence):
    """Build a deterministic diagnosis brief from calculated business evidence."""
    if not isinstance(evidence, dict):
        raise TypeError("Business evidence must be a dictionary.")

    eligible = [
        item for item in evidence.get("monthly_sales", [])
        if item.get("comparison_status") == "compared"
        and item.get("period_status") in {"complete", "not_assessed"}
        and _number(item.get("percentage_change"))
        and item["percentage_change"] < 0
    ]

    if not eligible:
        return {
            "status": "no_eligible_decline",
            "message": (
                "No eligible consecutive-month sales decline was found. "
                "A diagnosis cannot be generated from the available evidence."
            ),
        }

    decline = eligible[-1]
    current_period = decline["period"]
    previous_period = decline["previous_period"]

    def dimension_changes(collection, changes_key, name_key):
        match = next(
            (
                item for item in collection
                if item.get("period") == current_period
                and item.get("previous_period") == previous_period
            ),
            None,
        )
        if not match:
            return {"available": False, "declines": [], "increases": []}

        changes = [
            {
                "name": item.get(name_key),
                "absolute_change": item.get("absolute_change"),
            }
            for item in match.get(changes_key, [])
            if _number(item.get("absolute_change"))
        ]

        changes.sort(key=lambda item: item["absolute_change"])

        return {
            "available": True,
            "evidence_status": match.get("evidence_status"),
            "declines": [item for item in changes if item["absolute_change"] < 0][:5],
            "increases": [
                item for item in changes if item["absolute_change"] > 0
            ][-5:][::-1],
        }

    category = dimension_changes(
        evidence.get("category_contributions", []),
        "category_changes",
        "category",
    )
    product = dimension_changes(
        evidence.get("product_performance", []),
        "product_changes",
        "product",
    )

    order_metrics = {
        item.get("period"): item
        for item in evidence.get("monthly_order_metrics", [])
    }
    previous_order = order_metrics.get(previous_period)
    current_order = order_metrics.get(current_period)

    order_comparison = {"available": False}
    allowed_statuses = {"complete", "not_assessed"}

    if (
        previous_order
        and current_order
        and previous_order.get("period_status") in allowed_statuses
        and current_order.get("period_status") in allowed_statuses
    ):
        order_comparison = {"available": True}

        for metric in ("order_count", "average_order_value"):
            previous_value = previous_order.get(metric)
            current_value = current_order.get(metric)

            if _number(previous_value) and _number(current_value):
                change = current_value - previous_value
                percentage = (
                    round(change / previous_value * 100, 2)
                    if previous_value > 0 else None
                )
                order_comparison[metric] = {
                    "previous": previous_value,
                    "current": current_value,
                    "absolute_change": change,
                    "percentage_change": percentage,
                }
            else:
                order_comparison[metric] = None

    return {
        "status": "decline_detected",
        "analysis_status": (
            evidence.get("evidence_quality", {}).get("analysis_status")
            or "provisional"
        ),
        "scope": evidence.get("scope", {}),
        "sales_decline": {
            "previous_period": previous_period,
            "current_period": current_period,
            "previous_sales": decline.get("previous_value"),
            "current_sales": decline.get("value"),
            "absolute_change": decline.get("absolute_change"),
            "percentage_change": decline.get("percentage_change"),
            "period_status": decline.get("period_status"),
            "evidence_status": decline.get("evidence_status"),
        },
        "category_changes": category,
        "product_changes": product,
        "order_metrics": order_comparison,
        "interpretation_limits": [
            "Observed changes do not establish causation.",
            "Category and product changes are associations with the same period, not proof of cause.",
            "Unselected dimensions cannot be investigated.",
            "External factors such as pricing, marketing, stock availability and competition are not established by these figures.",
        ],
    }


def explain_root_cause(brief):
    """Create a deterministic diagnosis using only calculated evidence."""
    if not isinstance(brief, dict):
        raise TypeError("Diagnosis brief must be a dictionary.")
    if brief.get("status") != "decline_detected":
        raise ValueError("There is no eligible decline to explain.")

    sales = brief["sales_decline"]
    orders = brief.get("order_metrics", {})
    lines = []

    lines.append("## Business interpretation")
    lines.append(
        "Sales declined between "
        f"{sales['previous_period']} and {sales['current_period']}."
    )

    order_count = orders.get("order_count") if orders.get("available") else None
    aov = orders.get("average_order_value") if orders.get("available") else None

    if order_count and isinstance(order_count.get("percentage_change"), (int, float)):
        change = order_count["percentage_change"]
        if abs(change) <= 1:
            lines.append(
                "Recorded order count was broadly stable. The sales decline "
                "coincided with a change in average revenue per recorded order."
            )
        elif change < 0:
            lines.append(
                "Both recorded order count and sales declined. "
                "The order-count change is one measurable part of the decline."
            )
        else:
            lines.append(
                "Recorded order count increased despite lower sales. "
                "Average revenue per recorded order therefore weakened."
            )
    else:
        lines.append(
            "Order-count evidence is unavailable, so the change in sales "
            "cannot be separated into order volume and order value."
        )

    if aov and isinstance(aov.get("percentage_change"), (int, float)):
        if aov["percentage_change"] < 0:
            lines.append(
                "Average order value decreased. This establishes lower "
                "average recorded revenue per order, not why it happened."
            )
        elif aov["percentage_change"] > 0:
            lines.append(
                "Average order value increased, so the sales decline "
                "coincided with a reduction in recorded order count."
            )

    category = brief.get("category_changes", {})
    declines = category.get("declines", []) if category.get("available") else []
    if declines:
        lines.append("")
        lines.append("## Observed category changes")
        for item in declines[:5]:
            lines.append(
                f"- {item['name']}: {item['absolute_change']:,.2f} "
                "in the selected sales units."
            )
        lines.append("")
        lines.append(
            "These are same-period associations. They do not establish "
            "that category performance caused the overall decline."
        )
    else:
        lines.append(
            "Category-level comparison is unavailable for this period pair."
        )

    product = brief.get("product_changes", {})
    if not product.get("available"):
        lines.append(
            "Product-level changes were not available for this diagnosis."
        )

    lines.append("")
    lines.append("## What remains unknown")
    lines.append(
        "The available data does not establish changes in unit prices, "
        "discounts, quantities per order, stock availability, customer "
        "visits, or customer behaviour. It cannot identify the root cause."
    )

    lines.append("")
    lines.append("## Recommended investigations")
    lines.append(
        "- Compare units per order and product mix across the two periods."
    )
    lines.append(
        "- Check selling prices, discounts and promotions by category."
    )
    lines.append(
        "- Review inventory availability and product-level sales for "
        "the categories with the largest observed declines."
    )

    return "\n".join(lines)
