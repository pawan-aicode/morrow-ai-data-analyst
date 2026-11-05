"""Deterministic factual insights calculated from loaded dataset rows."""

import re

import pandas as pd
from pandas.api import types as ptypes


def _is_identifier(name):
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    tokens = [
        token for token in re.split(r"[^a-zA-Z0-9]+", normalized.lower())
        if token
    ]
    return "id" in tokens or "identifier" in tokens or "uuid" in tokens


def _date_values(series):
    """Return parsed dates only when the column is sufficiently date-like."""
    if ptypes.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce")
    elif ptypes.is_object_dtype(series) or ptypes.is_string_dtype(series):
        non_null = series.dropna()
        if len(non_null) < 2:
            return None
        sample = non_null.astype(str).head(100)
        parsed_sample = pd.to_datetime(
            sample, errors="coerce", format="mixed"
        )
        if parsed_sample.notna().mean() < 0.80:
            return None
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    else:
        return None

    if parsed.notna().mean() < 0.80:
        return None
    return parsed


def _monthly_change_analysis(monthly, as_of_date=None):
    """Compare consecutive months while respecting declared data coverage."""
    changes = []
    monthly_items = list(monthly.items())

    for index, (period, value) in enumerate(monthly_items):
        current_month = pd.Period(str(period), freq="M")

        if as_of_date is None:
            period_status = "not_assessed"
        elif current_month.end_time.date() <= as_of_date:
            period_status = "complete"
        elif current_month.start_time.date() <= as_of_date:
            period_status = "partial_period"
        else:
            period_status = "after_completeness_date"

        entry = {
            "period": str(period),
            "value": float(value),
            "previous_period": None,
            "previous_value": None,
            "absolute_change": None,
            "percentage_change": None,
            "comparison_status": "first_period",
            "period_status": period_status,
            "is_provisional": period_status == "partial_period",
        }

        if period_status == "after_completeness_date":
            entry["comparison_status"] = "outside_coverage"
            changes.append(entry)
            continue

        if index == 0:
            changes.append(entry)
            continue

        previous_period, previous_value = monthly_items[index - 1]
        entry["previous_period"] = str(previous_period)
        entry["previous_value"] = float(previous_value)

        prior_month = pd.Period(str(previous_period), freq="M")

        if current_month.ordinal - prior_month.ordinal != 1:
            entry["comparison_status"] = "missing_calendar_month"
        else:
            absolute_change = float(value) - float(previous_value)
            entry["absolute_change"] = absolute_change

            if previous_value <= 0:
                entry["comparison_status"] = "non_positive_previous"
            else:
                entry["percentage_change"] = round(
                    absolute_change / float(previous_value) * 100, 2
                )
                entry["comparison_status"] = "compared"

        changes.append(entry)

    comparable = [
        item for item in changes
        if (
            item["comparison_status"] == "compared"
            and item["period_status"] in ("complete", "not_assessed")
        )
    ]

    increases = [
        item for item in comparable if item["absolute_change"] > 0
    ]
    declines = [
        item for item in comparable if item["absolute_change"] < 0
    ]

    largest_increase = (
        max(increases, key=lambda item: item["absolute_change"])
        if increases else None
    )
    largest_decline = (
        min(declines, key=lambda item: item["absolute_change"])
        if declines else None
    )

    return {
        "monthly_changes": changes,
        "largest_increase": largest_increase,
        "largest_decline": largest_decline,
    }


def calculate_factual_insights(df, as_of_date=None, business_context=None):
    """
    Calculate factual metrics, monthly trends, category comparisons,
    and dataset scope from the DataFrame actually loaded into memory.
    """
    if business_context is None:
        business_context = {}

    if not isinstance(business_context, dict):
        raise TypeError("Business context must be a dictionary.")

    allowed_context_fields = {
        "currency",
        "row_granularity",
        "measure_meaning",
    }
    unknown_fields = set(business_context) - allowed_context_fields
    if unknown_fields:
        raise ValueError(
            f"Unsupported business context fields: {sorted(unknown_fields)}"
        )

    normalized_context = {}
    for field in allowed_context_fields:
        value = business_context.get(field)
        if value is not None and not isinstance(value, str):
            raise TypeError(f"Business context field '{field}' must be text.")
        normalized_context[field] = value.strip() if value else None

    if as_of_date is not None:
        as_of_date = pd.Timestamp(as_of_date).date()

    if not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame.")
    if df.empty:
        raise ValueError("Cannot calculate insights from an empty dataset.")

    numeric_columns = [
        col for col in df.columns
        if (
            not _is_identifier(col)
            and not ptypes.is_bool_dtype(df[col])
            and ptypes.is_numeric_dtype(df[col])
            and pd.to_numeric(df[col], errors="coerce").notna().any()
        )
    ]

    date_columns = [
        col for col in df.columns
        if not _is_identifier(col) and _date_values(df[col]) is not None
    ]

    categorical_columns = [
        col for col in df.columns
        if (
            not _is_identifier(col)
            and col not in numeric_columns
            and col not in date_columns
            and not ptypes.is_bool_dtype(df[col])
            and 2 <= df[col].nunique(dropna=True) <= 50
            and df[col].nunique(dropna=True) / len(df) <= 0.50
        )
    ]

    metrics = []
    for col in numeric_columns[:4]:
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        metrics.append({
            "column": str(col),
            "count": int(values.count()),
            "total": float(values.sum()),
            "average": float(values.mean()),
            "average_definition": (
                "Arithmetic mean of non-null values in this column; "
                "not necessarily a per-transaction value."
            ),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
        })

    trends = []
    comparisons = []

    # Use the first suitable numeric measure for trend and category analysis.
    if numeric_columns:
        measure = numeric_columns[0]
        values = pd.to_numeric(df[measure], errors="coerce")

        if date_columns:
            date_col = date_columns[0]
            parsed_dates = _date_values(df[date_col])
            working = pd.DataFrame({
                "period": parsed_dates.dt.to_period("M").astype(str),
                "value": values,
            }).dropna()

            monthly = (
                working.groupby("period")["value"]
                .sum()
                .sort_index()
            )

            if len(monthly) >= 2:
                mom = _monthly_change_analysis(
                    monthly, as_of_date=as_of_date
                )

                rankable_periods = [
                    item["period"]
                    for item in mom["monthly_changes"]
                    if item["period_status"] in ("complete", "not_assessed")
                ]

                if rankable_periods:
                    rankable_monthly = monthly.loc[rankable_periods]
                    highest_period = rankable_monthly.idxmax()
                    lowest_period = rankable_monthly.idxmin()
                    highest_value = float(rankable_monthly.loc[highest_period])
                    lowest_value = float(rankable_monthly.loc[lowest_period])
                else:
                    highest_period = None
                    lowest_period = None
                    highest_value = None
                    lowest_value = None

                trends.append({
                    "date_column": str(date_col),
                    "measure": str(measure),
                    "aggregation": "sum",
                    "data_complete_through": (
                        str(as_of_date) if as_of_date is not None else None
                    ),
                    "periods": int(len(monthly)),
                    "highest_period": (
                        str(highest_period) if highest_period is not None else None
                    ),
                    "highest_value": highest_value,
                    "lowest_period": (
                        str(lowest_period) if lowest_period is not None else None
                    ),
                    "lowest_value": lowest_value,
                    **mom,
                })

        for category_col in categorical_columns[:3]:
            working = pd.DataFrame({
                "category": df[category_col].fillna("Unknown").astype(str),
                "value": values,
            }).dropna(subset=["value"])

            grouped = (
                working.groupby("category")["value"]
                .sum()
                .sort_values(ascending=False)
            )

            if len(grouped) < 2:
                continue

            highest_category = grouped.index[0]
            lowest_category = grouped.index[-1]
            highest_value = float(grouped.iloc[0])
            lowest_value = float(grouped.iloc[-1])

            percentage_difference = None
            if lowest_value > 0:
                percentage_difference = round(
                    (highest_value - lowest_value) / lowest_value * 100,
                    2,
                )

            comparisons.append({
                "category_column": str(category_col),
                "measure": str(measure),
                "aggregation": "sum",
                "category_count": int(len(grouped)),
                "highest_category": str(highest_category),
                "highest_value": highest_value,
                "lowest_category": str(lowest_category),
                "lowest_value": lowest_value,
                "percentage_difference": percentage_difference,
            })

    source_rows = df.attrs.get("source_rows")
    is_sampled = bool(df.attrs.get("is_sampled", False))

    coverage = None
    if source_rows is not None and source_rows > 0:
        coverage = round(len(df) / source_rows * 100, 2)

    return {
        "scope": {
            "loaded_rows": int(len(df)),
            "source_rows": source_rows,
            "unprocessed_rows": (
                max(int(source_rows) - len(df), 0)
                if source_rows is not None else None
            ),
            "is_sampled": is_sampled,
            "coverage_percent": coverage,
        },
        "numeric_metrics": metrics,
        "monthly_trends": trends,
        "category_comparisons": comparisons,
        "business_context": normalized_context,
        "limitations": (
            ["Results describe only the loaded sample."]
            if is_sampled else []
        ),
    }
