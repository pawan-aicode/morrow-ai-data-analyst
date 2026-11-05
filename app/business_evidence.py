"""Deterministic business evidence calculations for Morrow."""

import pandas as pd


def _validate_columns(df, sales_col, date_col):
    if sales_col not in df.columns:
        raise ValueError(f"Sales column not found: {sales_col}")

    if date_col not in df.columns:
        raise ValueError(f"Date column not found: {date_col}")

    sales = pd.to_numeric(df[sales_col], errors="coerce")
    dates = pd.to_datetime(df[date_col], errors="coerce", format="mixed")

    if not sales.notna().any():
        raise ValueError("Sales column has no valid numeric values.")

    if not dates.notna().any():
        raise ValueError("Date column has no valid dates.")

    return sales, dates


def _monthly_comparison(grouped, as_of_date=None, suspected_partial_period=None):
    """Compare consecutive calendar months without treating gaps as zero."""
    entries = []

    for index, (period, value) in enumerate(grouped.items()):
        current = pd.Period(str(period), freq="M")

        if as_of_date is None and str(current) == suspected_partial_period:
            status = "potentially_partial"
        elif as_of_date is None:
            status = "not_assessed"
        elif current.end_time.date() <= as_of_date:
            status = "complete"
        elif current.start_time.date() <= as_of_date:
            status = "partial_period"
        else:
            status = "after_completeness_date"

        entry = {
            "period": str(period),
            "value": float(value),
            "previous_period": None,
            "previous_value": None,
            "absolute_change": None,
            "percentage_change": None,
            "comparison_status": "first_period",
            "period_status": status,
        }

        if status == "after_completeness_date":
            entry["comparison_status"] = "outside_coverage"
        elif status == "partial_period":
            entry["comparison_status"] = "partial_period"
        elif status == "potentially_partial":
            entry["comparison_status"] = "potentially_partial"
        elif index > 0:
            previous_period, previous_value = list(grouped.items())[index - 1]
            previous = pd.Period(str(previous_period), freq="M")

            entry["previous_period"] = str(previous_period)
            entry["previous_value"] = float(previous_value)

            if current.ordinal - previous.ordinal != 1:
                entry["comparison_status"] = "missing_calendar_month"
            elif previous_value <= 0:
                entry["absolute_change"] = float(value - previous_value)
                entry["comparison_status"] = "non_positive_previous"
            else:
                change = float(value - previous_value)
                entry["absolute_change"] = change
                entry["percentage_change"] = round(
                    change / float(previous_value) * 100, 2
                )
                entry["comparison_status"] = "compared"

        entries.append(entry)

    return entries


def _monthly_grouped(working):
    return (
        working.groupby("period")["sales"]
        .sum()
        .sort_index()
    )


def _detect_potentially_partial_period(dates):
    """Flag a latest month whose observed cutoff is unusually early."""
    valid = dates.dropna()
    if valid.empty:
        return {"status": "insufficient_history"}

    periods = valid.dt.to_period("M")
    latest_period = periods.max()
    latest_date = valid[periods == latest_period].max()

    historical = valid[periods < latest_period]
    if historical.empty:
        return {
            "status": "insufficient_history",
            "latest_period": str(latest_period),
            "latest_observed_date": latest_date.date().isoformat(),
        }

    historical_periods = periods[periods < latest_period]
    historical_cutoffs = (
        pd.DataFrame({
            "period": historical_periods,
            "date": historical,
        })
        .groupby("period")["date"]
        .max()
        .dt.day
    )
    median_cutoff = float(historical_cutoffs.median())
    days_before_month_end = (
        latest_period.end_time.normalize() - latest_date.normalize()
    ).days
    historical_gap = median_cutoff - latest_date.day

    suspected = days_before_month_end >= 7 and historical_gap >= 7

    return {
        "status": (
            "potentially_partial" if suspected else "no_anomaly_detected"
        ),
        "latest_period": str(latest_period),
        "latest_observed_date": latest_date.date().isoformat(),
        "days_before_month_end": int(days_before_month_end),
        "historical_median_last_day": median_cutoff,
        "historical_day_gap": float(historical_gap),
    }


def _evidence_status(period_status):
    """Translate completeness assessment into an evidence label."""
    return {
        "complete": "user_confirmed",
        "not_assessed": "provisional",
        "partial_period": "partial",
        "after_completeness_date": "outside_coverage",
        "potentially_partial": "provisional",
    }.get(period_status, "insufficient_evidence")


def calculate_business_evidence(
    df,
    sales_col,
    date_col,
    category_col=None,
    product_col=None,
    order_id_col=None,
    as_of_date=None,
):
    """Calculate evidence from explicitly selected dataset columns."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("A non-empty DataFrame is required.")

    if as_of_date is not None:
        as_of_date = pd.Timestamp(as_of_date).date()

    sales, dates = _validate_columns(df, sales_col, date_col)

    working = pd.DataFrame({
        "sales": sales,
        "date": dates,
    }).dropna()

    working["period"] = working["date"].dt.to_period("M").astype(str)

    automatic_coverage = _detect_potentially_partial_period(working["date"])
    suspected_partial_period = (
        automatic_coverage.get("latest_period")
        if as_of_date is None
        and automatic_coverage.get("status") == "potentially_partial"
        else None
    )

    if as_of_date is not None:
        automatic_coverage = {
            "status": "manual_completeness_date_supplied",
            "as_of_date": as_of_date.isoformat(),
        }

    monthly = _monthly_grouped(working)

    result = {
        "scope": {
            "loaded_rows": int(len(df)),
            "valid_sales_date_rows": int(len(working)),
        },
        "monthly_sales": _monthly_comparison(
            monthly, as_of_date, suspected_partial_period
        ),
        "automatic_coverage_check": automatic_coverage,
        "category_contributions": [],
        "product_performance": [],
        "monthly_order_metrics": [],
        "selected_columns": {
            "sales": sales_col,
            "date": date_col,
            "category": category_col,
            "product": product_col,
            "order_id": order_id_col,
        },
    }

    result["evidence_quality"] = {
        "completeness_status": (
            "user_confirmed" if as_of_date is not None else "not_assessed"
        ),
        "analysis_status": (
            "user_confirmed" if as_of_date is not None else "provisional"
        ),
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "loaded_rows": int(len(df)),
        "valid_rows": int(len(working)),
        "excluded_rows": int(len(df) - len(working)),
    }

    for item in result["monthly_sales"]:
        item["evidence_status"] = _evidence_status(item["period_status"])

    if category_col is not None:
        if category_col not in df.columns:
            raise ValueError(f"Category column not found: {category_col}")

        category_data = pd.DataFrame({
            "period": dates.dt.to_period("M").astype(str),
            "category": df[category_col].fillna("Unknown").astype(str),
            "sales": sales,
        }).dropna(subset=["period", "sales"])

        grouped = (
            category_data.groupby(["period", "category"])["sales"]
            .sum()
            .unstack(fill_value=0)
            .sort_index()
        )

        for index in range(1, len(grouped)):
            period = grouped.index[index]
            previous_period = grouped.index[index - 1]

            if str(period) == suspected_partial_period:
                continue

            if (
                pd.Period(period, freq="M").ordinal
                - pd.Period(previous_period, freq="M").ordinal
                != 1
            ):
                continue

            current_month = pd.Period(period, freq="M")
            if as_of_date is not None and (
                current_month.end_time.date() > as_of_date
            ):
                continue

            current = grouped.loc[period]
            previous = grouped.loc[previous_period]
            changes = current.subtract(previous).sort_values()

            result["category_contributions"].append({
                "period": period,
                "previous_period": previous_period,
                "evidence_status": (
                    "user_confirmed" if as_of_date is not None else "provisional"
                ),
                "category_changes": [
                    {
                        "category": str(category),
                        "absolute_change": float(change),
                    }
                    for category, change in changes.items()
                ],
            })

    if product_col is not None:
        if product_col not in df.columns:
            raise ValueError(f"Product column not found: {product_col}")

        product_data = pd.DataFrame({
            "period": dates.dt.to_period("M").astype(str),
            "product": df[product_col].fillna("Unknown").astype(str),
            "sales": sales,
        }).dropna(subset=["period", "sales"])

        grouped = (
            product_data.groupby(["period", "product"])["sales"]
            .sum()
            .unstack(fill_value=0)
            .sort_index()
        )

        for index in range(1, len(grouped)):
            period = grouped.index[index]
            previous_period = grouped.index[index - 1]

            if str(period) == suspected_partial_period:
                continue

            if (
                pd.Period(period, freq="M").ordinal
                - pd.Period(previous_period, freq="M").ordinal
                != 1
            ):
                continue

            current_month = pd.Period(period, freq="M")
            if as_of_date is not None and (
                current_month.end_time.date() > as_of_date
            ):
                continue

            changes = (
                grouped.loc[period] - grouped.loc[previous_period]
            ).sort_values()

            result["product_performance"].append({
                "period": period,
                "previous_period": previous_period,
                "evidence_status": (
                    "user_confirmed" if as_of_date is not None else "provisional"
                ),
                "product_changes": [
                    {
                        "product": str(product),
                        "absolute_change": float(change),
                    }
                    for product, change in changes.items()
                ],
            })

    if order_id_col is not None:
        if order_id_col not in df.columns:
            raise ValueError(f"Order ID column not found: {order_id_col}")

        order_data = pd.DataFrame({
            "date": dates,
            "order_id": df[order_id_col],
            "sales": sales,
        }).dropna(subset=["date", "order_id", "sales"])

        order_data = order_data[
            order_data["order_id"].astype(str).str.strip() != ""
        ].copy()

        # Normalize integer-like IDs while preserving string leading zeros.
        def normalize_order_id(value):
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, int):
                return str(value)
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value).strip()

        order_data["normalized_order_id"] = (
            order_data["order_id"].map(normalize_order_id)
        )

        # Consolidate every order before assigning it to a month.
        order_data["order_month"] = (
            order_data.groupby("normalized_order_id")["date"]
            .transform("min")
            .dt.to_period("M")
            .astype(str)
        )

        order_totals = order_data.groupby(
            ["normalized_order_id", "order_month"], as_index=False
        ).agg(order_sales=("sales", "sum"))

        order_months = order_totals.groupby("order_month").agg(
            order_count=("normalized_order_id", "nunique"),
            sales=("order_sales", "sum"),
        ).sort_index()

        for period, row in order_months.iterrows():
            current_month = pd.Period(period, freq="M")

            if as_of_date is not None and (
                current_month.start_time.date() > as_of_date
            ):
                continue

            order_count = int(row["order_count"])

            result["monthly_order_metrics"].append({
                "period": period,
                "order_count": order_count,
                "sales": float(row["sales"]),
                "average_order_value": (
                    float(row["sales"]) / order_count
                    if order_count else None
                ),
                "period_status": (
                    "potentially_partial"
                    if as_of_date is None
                    and period == suspected_partial_period
                    else "not_assessed"
                    if as_of_date is None
                    else "complete"
                    if current_month.end_time.date() <= as_of_date
                    else "partial_period"
                    if current_month.start_time.date() <= as_of_date
                    else "after_completeness_date"
                ),
                "evidence_status": _evidence_status(
                    "potentially_partial"
                    if as_of_date is None
                    and period == suspected_partial_period
                    else "not_assessed"
                    if as_of_date is None
                    else "complete"
                    if current_month.end_time.date() <= as_of_date
                    else "partial_period"
                    if current_month.start_time.date() <= as_of_date
                    else "after_completeness_date"
                ),
            })

    return result
