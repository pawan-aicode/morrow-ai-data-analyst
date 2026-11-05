"""Deterministic, evidence-linked business recommendations."""

import math


DEFAULT_DECLINE_THRESHOLD_PERCENT = 2.0


def generate_recommendations(
    evidence,
    decline_threshold_percent=DEFAULT_DECLINE_THRESHOLD_PERCENT,
):
    """Generate recommendations using only supplied business evidence."""

    if not isinstance(evidence, dict):
        raise TypeError("Evidence must be a dictionary.")

    if (
        isinstance(decline_threshold_percent, bool)
        or not isinstance(decline_threshold_percent, (int, float))
        or not math.isfinite(float(decline_threshold_percent))
        or decline_threshold_percent < 0
    ):
        raise ValueError(
            "Decline threshold must be a finite, non-negative number."
        )

    monthly_sales = evidence.get("monthly_sales")
    if not isinstance(monthly_sales, list):
        raise ValueError("Evidence must contain a monthly_sales list.")

    recommendations = []

    for item in monthly_sales:
        if not isinstance(item, dict):
            continue

        if item.get("comparison_status") != "compared":
            continue

        change = item.get("absolute_change")
        percentage = item.get("percentage_change")

        if (
            isinstance(change, bool)
            or not isinstance(change, (int, float))
            or isinstance(percentage, bool)
            or not isinstance(percentage, (int, float))
        ):
            continue

        if percentage > -decline_threshold_percent:
            continue

        row_status = item.get("evidence_status")
        quality = evidence.get("evidence_quality") or {}
        overall_status = quality.get("analysis_status")

        evidence_status = (
            "user_confirmed"
            if row_status == "user_confirmed"
            and overall_status == "user_confirmed"
            else "provisional"
        )

        recommendations.append({
            "recommendation_type": "sales_decline",
            "title": (
                f"Monthly sales decline: "
                f"{item.get('previous_period')} to {item.get('period')}"
            ),
            "priority": "high" if percentage <= -10 else "medium",
            "observation": (
                f"Sales declined by {abs(percentage):.2f}% "
                f"between {item.get('previous_period')} "
                f"and {item.get('period')}."
            ),
            "recommended_action": (
                (
                    "Review " + " and ".join(
                        label for selected, label in (
                            (bool((evidence.get("selected_columns") or {}).get("category")), "category"),
                            (bool((evidence.get("selected_columns") or {}).get("product")), "product"),
                        )
                        if selected
                    ) + "-level sales changes for the same period. "
                    if any((evidence.get("selected_columns") or {}).get(key)
                           for key in ("category", "product"))
                    else "Review order volume and average order value for the same period. "
                    if evidence.get("monthly_order_metrics")
                    else "Review the underlying sales records for the same period. "
                )
                + "Investigate possible causes separately; the supplied figures do not establish causation."
            ),
            "evidence_status": evidence_status,
            "evidence": {
                "current_period": item.get("period"),
                "previous_period": item.get("previous_period"),
                "current_value": item.get("value"),
                "previous_value": item.get("previous_value"),
                "absolute_change": change,
                "percentage_change": percentage,
                "comparison_status": item.get("comparison_status"),
            },
            "limitations": [
                "The comparison establishes a change, not its cause."
            ],
        })


    # Only use category/product comparisons matching a qualifying
    # overall monthly sales decline.
    qualifying_periods = {
        (item.get("period"), item.get("previous_period"))
        for item in monthly_sales
        if isinstance(item, dict)
        and item.get("comparison_status") == "compared"
        and isinstance(item.get("percentage_change"), (int, float))
        and not isinstance(item.get("percentage_change"), bool)
        and item["percentage_change"] <= -decline_threshold_percent
    }

    quality = evidence.get("evidence_quality") or {}
    overall_status = quality.get("analysis_status")

    def resolve_status(row_status):
        if (
            row_status == "user_confirmed"
            and overall_status == "user_confirmed"
        ):
            return "user_confirmed"
        return "provisional"

    for section, changes_key, entity_key, recommendation_type in (
        (
            "category_contributions",
            "category_changes",
            "category",
            "category_decline",
        ),
        (
            "product_performance",
            "product_changes",
            "product",
            "product_decline",
        ),
    ):
        comparisons = evidence.get(section) or []
        if not isinstance(comparisons, list):
            continue

        for comparison in comparisons:
            if not isinstance(comparison, dict):
                continue

            period_pair = (
                comparison.get("period"),
                comparison.get("previous_period"),
            )
            if period_pair not in qualifying_periods:
                continue

            changes = comparison.get(changes_key)
            if not isinstance(changes, list):
                continue

            valid_changes = [
                change for change in changes
                if isinstance(change, dict)
                and isinstance(change.get("absolute_change"), (int, float))
                and not isinstance(change.get("absolute_change"), bool)
                and change["absolute_change"] < 0
                and isinstance(change.get(entity_key), str)
            ]

            if not valid_changes:
                continue

            largest_decline = min(
                valid_changes,
                key=lambda change: change["absolute_change"],
            )

            entity_name = largest_decline[entity_key]
            amount = float(largest_decline["absolute_change"])
            evidence_status = resolve_status(
                comparison.get("evidence_status")
            )

            recommendations.append({
                "recommendation_type": recommendation_type,
                "title": (
                    f"{entity_key.capitalize()} decline: {entity_name} "
                    f"({period_pair[1]} to {period_pair[0]})"
                ),
                "priority": "medium",
                "observation": (
                    f"{entity_key.capitalize()} {entity_name} "
                    f"recorded a sales decrease of {abs(amount):.2f} "
                    f"between {period_pair[1]} and {period_pair[0]}."
                ),
                "recommended_action": (
                    f"Review the sales records and relevant operational "
                    f"information for {entity_name} during this period. "
                    "The supplied figures identify a decline but do not "
                    "establish its cause."
                ),
                "evidence_status": evidence_status,
                "evidence": {
                    entity_key: entity_name,
                    "current_period": period_pair[0],
                    "previous_period": period_pair[1],
                    "absolute_change": amount,
                },
                "limitations": [
                    "The observed decrease does not establish its cause."
                ],
            })


    # Compare monthly order count and average order value when order IDs
    # are available. Only consecutive, assessed periods are compared.
    order_metrics = evidence.get("monthly_order_metrics") or []

    def month_number(period):
        try:
            year, month = str(period).split("-")
            year, month = int(year), int(month)
            if not 1 <= month <= 12:
                return None
            return year * 12 + month
        except (TypeError, ValueError):
            return None

    for previous, current in zip(order_metrics, order_metrics[1:]):
        if not isinstance(previous, dict) or not isinstance(current, dict):
            continue

        previous_month = month_number(previous.get("period"))
        current_month = month_number(current.get("period"))
        if (
            previous_month is None
            or current_month is None
            or current_month - previous_month != 1
        ):
            continue

        allowed_statuses = {"complete", "not_assessed"}
        if (
            previous.get("period_status") not in allowed_statuses
            or current.get("period_status") not in allowed_statuses
        ):
            continue

        status = (
            "user_confirmed"
            if overall_status == "user_confirmed"
            and previous.get("evidence_status") == "user_confirmed"
            and current.get("evidence_status") == "user_confirmed"
            else "provisional"
        )

        for metric_key, recommendation_type, label in (
            ("order_count", "order_count_decline", "order count"),
            ("average_order_value", "aov_decline", "average order value"),
        ):
            old_value = previous.get(metric_key)
            new_value = current.get(metric_key)

            if (
                isinstance(old_value, bool)
                or isinstance(new_value, bool)
                or not isinstance(old_value, (int, float))
                or not isinstance(new_value, (int, float))
                or not math.isfinite(float(old_value))
                or not math.isfinite(float(new_value))
                or old_value <= 0
            ):
                continue

            absolute_change = float(new_value) - float(old_value)
            percentage_change = absolute_change / float(old_value) * 100

            if percentage_change > -decline_threshold_percent:
                continue

            recommendations.append({
                "recommendation_type": recommendation_type,
                "title": (
                    f"{label.capitalize()} decline: "
                    f"{previous.get('period')} to {current.get('period')}"
                ),
                "priority": "high" if percentage_change <= -10 else "medium",
                "observation": (
                    f"Monthly {label} declined by "
                    f"{abs(percentage_change):.2f}% between "
                    f"{previous.get('period')} and {current.get('period')}."
                ),
                "recommended_action": (
                    f"Review the transactions and operational factors "
                    f"affecting {label} during this period. "
                    "The comparison identifies a change, not its cause."
                ),
                "evidence_status": status,
                "evidence": {
                    "metric": metric_key,
                    "current_period": current.get("period"),
                    "previous_period": previous.get("period"),
                    "current_value": new_value,
                    "previous_value": old_value,
                    "absolute_change": absolute_change,
                    "percentage_change": percentage_change,
                },
                "limitations": [
                    "The comparison identifies a change, not its cause."
                ],
            })

    # Consolidate repeated monthly declines into one card per metric.
    grouped_types = {
        "sales_decline",
        "order_count_decline",
        "aov_decline",
    }
    grouped = {}
    remaining = []

    for recommendation in recommendations:
        kind = recommendation.get("recommendation_type")
        if kind in grouped_types:
            grouped.setdefault(kind, []).append(recommendation)
        else:
            remaining.append(recommendation)

    labels = {
        "sales_decline": "sales",
        "order_count_decline": "order count",
        "aov_decline": "average order value",
    }

    for kind, items in grouped.items():
        if len(items) == 1:
            remaining.append(items[0])
            continue

        details = [item["evidence"] for item in items]
        worst = min(
            details,
            key=lambda item: item.get("percentage_change", 0),
        )
        periods = [
            f"{item.get('previous_period')} to {item.get('current_period')}"
            for item in details
        ]
        label = labels[kind]
        worst_change = worst.get("percentage_change")

        remaining.append({
            "recommendation_type": kind,
            "title": f"Multiple {label} declines ({len(items)} periods)",
            "priority": (
                "high"
                if any(item["priority"] == "high" for item in items)
                else "medium"
            ),
            "observation": (
                f"{label.capitalize()} declined in {len(items)} "
                f"month-to-month comparisons. The largest decline was "
                f"{abs(worst_change):.2f}% "
                f"from {worst.get('previous_period')} "
                f"to {worst.get('current_period')}."
            ),
            "recommended_action": items[0]["recommended_action"],
            "evidence_status": (
                "user_confirmed"
                if all(item["evidence_status"] == "user_confirmed"
                       for item in items)
                else "provisional"
            ),
            "evidence": {
                "decline_period_count": len(items),
                "periods": periods,
                "largest_decline": worst,
                "period_comparisons": details,
            },
            "limitations": list(dict.fromkeys(
                limitation
                for item in items
                for limitation in item["limitations"]
            )),
        })

    recommendations = remaining

    return recommendations
