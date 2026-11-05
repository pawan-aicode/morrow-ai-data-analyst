"""Reusable data profiling engine for Morrow."""

import re

import pandas as pd
from pandas.api import types as ptypes


TOP_VALUES_LIMIT = 5
HIGH_MISSING_THRESHOLD = 0.50
DATE_PARSE_THRESHOLD = 0.80
MEDIUM_MISSING_THRESHOLD = 0.10


def _is_identifier_column(name):
    """Recognize conventional identifier column names."""
    normalized = re.sub(
        r"([a-z0-9])([A-Z])", r"\1_\2", str(name)
    )
    tokens = [
        token for token in re.split(r"[^a-zA-Z0-9]+", normalized.lower())
        if token
    ]
    return (
        "id" in tokens
        or "identifier" in tokens
        or "uuid" in tokens
    )




def _detect_column_type(series):
    """Identify a useful analytical type for a pandas Series."""
    dtype = series.dtype

    if ptypes.is_bool_dtype(dtype):
        return "boolean"

    if ptypes.is_numeric_dtype(dtype):
        return "numeric"

    if ptypes.is_datetime64_any_dtype(dtype):
        return "date"

    non_null = series.dropna()

    if non_null.empty:
        return "empty"

    # Avoid interpreting ordinary numeric-looking text as dates.
    if ptypes.is_object_dtype(dtype) or ptypes.is_string_dtype(dtype):
        sample = non_null.astype(str).head(100)

        if len(sample) >= 2:
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
            ratio = parsed.notna().mean()

            if ratio >= DATE_PARSE_THRESHOLD:
                return "date"

    return "categorical"


def _safe_number(value):
    """Convert pandas/numpy numeric values to JSON-friendly Python values."""
    if pd.isna(value):
        return None

    return float(value)


def _column_profile(name, series):
    """Generate analytical and quality information for one column."""
    total = len(series)
    missing = int(series.isna().sum())
    non_missing = total - missing

    column_type = _detect_column_type(series)

    profile = {
        "name": str(name),
        "dtype": str(series.dtype),
        "type": column_type,
        "total_values": total,
        "non_missing": non_missing,
        "missing": missing,
        "missing_percent": round(
            missing / total * 100, 2
        ) if total else 0.0,
        "unique_values": int(series.nunique(dropna=True)),
        "examples": [
            str(value)[:100]
            for value in series.dropna().drop_duplicates().head(3)
        ],
    }

    if column_type == "numeric":
        values = pd.to_numeric(series, errors="coerce")

        if values.notna().any():
            profile["statistics"] = {
                "min": _safe_number(values.min()),
                "max": _safe_number(values.max()),
                "mean": _safe_number(values.mean()),
                "median": _safe_number(values.median()),
                "std": _safe_number(values.std()),
            }

    elif column_type == "date":
        values = pd.to_datetime(series, errors="coerce")

        if values.notna().any():
            profile["statistics"] = {
                "earliest": str(values.min()),
                "latest": str(values.max()),
            }

    elif column_type in {"categorical", "boolean"}:
        counts = series.value_counts(dropna=True).head(TOP_VALUES_LIMIT)

        profile["top_values"] = [
            {
                "value": str(value)[:100],
                "count": int(count),
            }
            for value, count in counts.items()
        ]

    return profile


def profile_dataframe(
    df,
    source_rows=None,
    is_sampled=False,
):
    """
    Profile a DataFrame.

    source_rows: known total rows in the original source, if available.
    is_sampled: whether the DataFrame represents only part of the source.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame.")

    if df.empty:
        raise ValueError("Cannot profile an empty dataset.")

    if df.columns.duplicated().any():
        raise ValueError("Dataset contains duplicate column names.")

    if source_rows is not None:
        if not isinstance(source_rows, int) or source_rows < len(df):
            raise ValueError(
                "source_rows must be an integer greater than or equal "
                "to the loaded row count."
            )

    loaded_rows = len(df)
    total_rows = (
        source_rows
        if source_rows is not None
        else (None if is_sampled else loaded_rows)
    )

    sampled = bool(
        is_sampled
        or (total_rows is not None and total_rows > loaded_rows)
    )

    columns = [
        _column_profile(name, df[name])
        for name in df.columns
    ]

    duplicate_rows = int(df.duplicated().sum())

    missing_cells = int(df.isna().sum().sum())
    total_cells = loaded_rows * len(df.columns)

    issues = []

    for column in columns:
        if column["missing"] > 0:
            missing_ratio = column["missing_percent"] / 100

            if missing_ratio >= HIGH_MISSING_THRESHOLD:
                severity = "high"
            elif missing_ratio >= MEDIUM_MISSING_THRESHOLD:
                severity = "medium"
            else:
                severity = "low"

            count = column["missing"]
            label = "value" if count == 1 else "values"

            issues.append({
                "column": column["name"],
                "severity": severity,
                "issue": (
                    f"{count:,} missing {label} "
                    f"({column['missing_percent']:.2f}%)."
                ),
            })

        if column["unique_values"] <= 1:
            issues.append({
                "column": column["name"],
                "severity": "medium",
                "issue": "Column has one or fewer distinct non-missing values.",
            })

    if duplicate_rows:
        issues.append({
            "column": None,
            "severity": "medium",
            "issue": f"{duplicate_rows:,} duplicate rows detected.",
        })

    recommendations = []

    analytical_columns = [
        item for item in columns
        if not _is_identifier_column(item["name"])
    ]

    numeric_columns = [
        item["name"] for item in analytical_columns
        if item["type"] == "numeric"
    ]

    # Avoid recommending categories that are nearly unique per row.
    categorical_columns = [
        item["name"] for item in analytical_columns
        if (
            item["type"] in {"categorical", "boolean"}
            and 2 <= item["unique_values"] <= 50
            and item["unique_values"] / loaded_rows <= 0.50
        )
    ]

    date_columns = [
        item["name"] for item in analytical_columns
        if item["type"] == "date"
    ]

    if numeric_columns:
        recommendations.append(
            "Explore distributions and summary statistics for "
            + ", ".join(numeric_columns[:5]) + "."
        )

    if date_columns and numeric_columns:
        recommendations.append(
            "Explore trends over time using "
            + date_columns[0] + " and "
            + numeric_columns[0] + "."
        )

    if categorical_columns and numeric_columns:
        recommendations.append(
            "Compare numerical measures across categories such as "
            + categorical_columns[0] + "."
        )

    if duplicate_rows:
        recommendations.append(
            "Review duplicate rows before performing detailed analysis."
        )

    if any(item["missing"] for item in columns):
        recommendations.append(
            "Review missing values before using affected columns."
        )

    return {
        "overview": {
            "loaded_rows": loaded_rows,
            "total_rows": total_rows,
            "columns": len(df.columns),
            "duplicate_rows": duplicate_rows,
            "missing_cells": missing_cells,
            "total_cells": total_cells,
            "missing_percent": round(
                missing_cells / total_cells * 100, 2
            ) if total_cells else 0.0,
            "memory_mb": round(
                df.memory_usage(index=True, deep=True).sum()
                / (1024 * 1024),
                3,
            ),
            "is_sampled": sampled,
            "coverage_percent": (
                round(loaded_rows / total_rows * 100, 2)
                if total_rows is not None and total_rows > 0
                else (None if sampled else 100.0)
            ),
        },
        "columns": columns,
        "issues": issues,
        "recommendations": recommendations,
    }
