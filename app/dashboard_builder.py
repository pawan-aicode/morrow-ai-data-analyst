"""Morrow's safe, natural-language dashboard builder."""

import json
import re
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from app.agent import MODEL, OLLAMA_URL
from app.profiling import profile_dataframe
from app.insights import calculate_factual_insights
from app.insight_explainer import explain_factual_insights
from app.business_evidence import calculate_business_evidence
from app.recommendations import generate_recommendations
from app.root_cause import build_root_cause_brief, explain_root_cause


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PREVIEW_ROWS = 5000
MAX_CHARTS = 6


def read_upload(upload):
    """Load a bounded CSV or Excel upload into memory."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValueError("Please upload a file smaller than 25 MB.")

    suffix = Path(upload.name).suffix.lower()

    if suffix == ".csv":
        upload.seek(0)
        df = pd.read_csv(upload)
        df.attrs["source_rows"] = len(df)
        df.attrs["is_sampled"] = False

    elif suffix in {".xlsx", ".xlsm"}:
        upload.seek(0)
        df = pd.read_excel(upload)
        df.attrs["source_rows"] = len(df)
        df.attrs["is_sampled"] = False

    else:
        raise ValueError("Supported formats are CSV, XLSX, and XLSM.")

    if df.empty:
        raise ValueError("This file contains no data rows.")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    return df


def read_sqlite_readonly(path, table):
    """Read a table from SQLite using a read-only connection."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Database file does not exist.")

    # The table name must be selected from the inspected table list.
    uri = path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        if table not in tables:
            raise ValueError("Select a table from the available table list.")

        quoted = '"' + table.replace('"', '""') + '"'
        source_rows = int(
            conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        )
        df = pd.read_sql_query(
            f"SELECT * FROM {quoted}", conn
        )
        df.attrs["source_rows"] = source_rows
        df.attrs["is_sampled"] = False
        return df


def _column_summary(df):
    summary = []
    for col in df.columns:
        series = df[col]
        item = {
            "name": str(col)[:100],
            "dtype": str(series.dtype),
            "examples": [
                str(v)[:80] for v in series.dropna().head(3).tolist()
            ],
        }
        if pd.api.types.is_numeric_dtype(series):
            item["min"] = float(series.min()) if series.notna().any() else None
            item["max"] = float(series.max()) if series.notna().any() else None
        summary.append(item)
    return summary



def _dashboard_profile_context(df):
    """Build a compact, JSON-safe profile for AI dashboard planning."""
    result = profile_dataframe(
        df,
        source_rows=df.attrs.get("source_rows"),
        is_sampled=df.attrs.get("is_sampled", False),
    )

    overview = result["overview"]

    return {
        "overview": {
            "loaded_rows": overview["loaded_rows"],
            "source_rows": overview["total_rows"],
            "is_sampled": overview["is_sampled"],
            "coverage_percent": overview["coverage_percent"],
            "missing_percent": overview["missing_percent"],
            "duplicate_rows": overview["duplicate_rows"],
        },
        "columns": [
            {
                "name": item["name"],
                "type": item["type"],
                "dtype": item["dtype"],
                "missing_percent": item["missing_percent"],
                "unique_values": item["unique_values"],
                "statistics": item.get("statistics", {}),
                "top_values": item.get("top_values", []),
            }
            for item in result["columns"]
        ],
        "recommendations": result["recommendations"],
    }


def generate_dashboard_plan(question, df):
    """Ask local Ollama for a JSON-only, declarative dashboard plan."""
    columns = _column_summary(df)
    data_profile = _dashboard_profile_context(df)

    prompt = f"""
Create an interactive business dashboard plan for this dataset.

User request: {question[:1000]}
Dataset rows loaded: {len(df)}
Dataset columns: {json.dumps(columns, ensure_ascii=False)}
Data profile: {json.dumps(data_profile, ensure_ascii=False)}

Use the data profile when choosing KPIs and charts:
- Prefer meaningful business measures over identifier columns.
- Do not use columns with many missing values without a good reason.
- Use detected date columns for time-based trends where appropriate.
- Use categorical columns with manageable numbers of unique values for comparisons.
- Use numeric statistics to choose sensible aggregations.
- Respect the sample warning: all statistics describe only the loaded rows.
- Treat profiling recommendations as suggestions, not mandatory instructions.

Return ONLY valid JSON with this schema:
{{
  "title": "short dashboard title",
  "summary": "one sentence",
  "kpis": [{{"column":"existing numeric column","aggregation":"sum|mean|count|min|max","label":"short label"}}],
  "charts": [
    {{"type":"bar|line|scatter|pie","x":"existing column",
      "y":"existing numeric column or null","aggregation":"sum|mean|count",
      "title":"short title"}}
  ]
}}

Rules:
- Use only exact column names from the supplied dataset.
- Never invent data or column names.
- Use at most 4 KPIs and 6 charts.
- Use line charts for time trends when a date column exists.
- Use pie charts only for a small number of categories.
- If the request cannot be fulfilled, return a useful dashboard from available columns.
- Do not return SQL, Python, HTML, or executable code.
"""
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": "You design dashboards. Return valid JSON only."
            },
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0, "num_predict": 1200},
    }).encode()

    request = urllib.request.Request(
        OLLAMA_URL, data=body,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode())
        plan = json.loads(result["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        raise RuntimeError(
            "Morrow couldn't generate a dashboard plan. "
            "Check that Ollama is running and the model is available."
        ) from exc

    if not isinstance(plan, dict):
        raise RuntimeError("The model returned an invalid dashboard plan.")

    return plan


def _safe_plan(plan, df):
    """Allow only known columns and supported chart operations."""
    columns = set(df.columns)
    clean = {
        "title": str(plan.get("title", "Morrow Dashboard"))[:100],
        "summary": str(plan.get("summary", ""))[:500],
        "kpis": [],
        "charts": [],
    }

    numeric = {
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])
    }
    allowed_aggs = {"sum", "mean", "count", "min", "max"}

    for item in plan.get("kpis", [])[:4]:
        if not isinstance(item, dict):
            continue
        col = item.get("column")
        agg = item.get("aggregation")
        if col not in columns or agg not in allowed_aggs:
            continue
        if agg != "count" and col not in numeric:
            continue
        # Keep labels factual: derive them from the operation and column.
        safe_labels = {
            "sum": f"Total {col}",
            "mean": f"Average {col}",
            "count": f"Count of {col}",
            "min": f"Minimum {col}",
            "max": f"Maximum {col}",
        }
        clean["kpis"].append({
            "column": col,
            "aggregation": agg,
            "label": safe_labels[agg][:60],
        })

    for item in plan.get("charts", [])[:MAX_CHARTS]:
        if not isinstance(item, dict):
            continue
        kind, x, y = item.get("type"), item.get("x"), item.get("y")
        agg = item.get("aggregation", "sum")

        if kind not in {"bar", "line", "scatter", "pie"}:
            continue
        if x not in columns or agg not in {"sum", "mean", "count"}:
            continue
        if kind != "pie" and agg != "count" and y not in numeric:
            continue
        if kind == "pie" and y is not None and y not in numeric:
            continue
        if kind == "count":
            y = None

        clean["charts"].append({
            "type": kind, "x": x, "y": y,
            "aggregation": agg,
            "title": str(item.get("title", "Analysis"))[:100],
        })

    return clean


def _aggregate_chart(df, spec):
    x, y, agg = spec["x"], spec["y"], spec["aggregation"]
    if spec["type"] == "pie":
        if y is None:
            grouped = df[x].fillna("Unknown").astype(str).value_counts().head(12)
            return grouped.rename_axis(x).reset_index(name="count"), "count"
        result = df.groupby(x, dropna=False)[y].agg(agg).reset_index()
        return result.head(100), y

    if spec["type"] == "scatter":
        return df[[x, y]].dropna().head(2000), y

    # Automatically group date-like x columns by month for line charts.
    if spec["type"] == "line":
        dates = pd.to_datetime(df[x], errors="coerce")
        if dates.notna().sum() > 0 and dates.notna().mean() >= 0.8:
            working = df[[y]].copy()
            working["_month"] = dates.dt.to_period("M").astype(str)
            working = working.dropna(subset=[y])
            if agg == "count":
                result = working.groupby("_month").size().reset_index(name="count")
                return result.rename(columns={"_month": x}), "count"
            result = working.groupby("_month")[y].agg(agg).reset_index()
            return result.rename(columns={"_month": x}), y

    if agg == "count":
        result = df.groupby(x, dropna=False).size().reset_index(name="count")
        return result.head(100), "count"

    result = df.groupby(x, dropna=False)[y].agg(agg).reset_index()
    return result.head(100), y




def _render_data_profile(df):
    """Display a data-quality and statistical profile for the loaded data."""
    source_rows = df.attrs.get("source_rows")
    is_sampled = df.attrs.get("is_sampled", False)

    try:
        profile = profile_dataframe(
            df,
            source_rows=source_rows,
            is_sampled=is_sampled,
        )
    except Exception as exc:
        st.error(f"Could not profile this dataset: {exc}")
        return

    overview = profile["overview"]

    st.markdown("---")
    st.markdown("### Data Profile")
    st.caption(
        "An automatic inspection of dataset structure, column statistics, "
        "and data quality."
    )

    if overview["is_sampled"]:
        if overview["total_rows"] is not None:
            st.warning(
                f"Profiling a sample of {overview['loaded_rows']:,} "
                f"of {overview['total_rows']:,} source rows "
                f"({overview['coverage_percent']:.1f}% coverage). "
                "Statistics and quality checks below apply to the loaded "
                "sample, not necessarily the full dataset."
            )
        else:
            st.warning(
                f"Profiling the first {overview['loaded_rows']:,} rows. "
                "The full source row count is unknown, so full-dataset "
                "coverage cannot be calculated."
            )

    metrics = st.columns(5)
    metrics[0].metric("Loaded rows", f"{overview['loaded_rows']:,}")
    metrics[1].metric("Columns", f"{overview['columns']:,}")
    metrics[2].metric("Missing cells", f"{overview['missing_percent']:.1f}%")
    metrics[3].metric("Duplicate rows", f"{overview['duplicate_rows']:,}")
    metrics[4].metric("Memory", f"{overview['memory_mb']:.2f} MB")

    overview_tab, columns_tab, quality_tab, recommendations_tab = st.tabs(
        ["Overview", "Column analysis", "Data quality", "Recommendations"]
    )

    with overview_tab:
        st.write({
            "Loaded rows": overview["loaded_rows"],
            "Source rows": overview["total_rows"],
            "Coverage": (
                f"{overview['coverage_percent']:.1f}%"
                if overview["coverage_percent"] is not None
                else "Unknown"
            ),
            "Missing cells": overview["missing_cells"],
            "Total cells": overview["total_cells"],
            "Duplicate rows": overview["duplicate_rows"],
            "Memory usage": f"{overview['memory_mb']:.3f} MB",
        })

    with columns_tab:
        column_rows = []
        for item in profile["columns"]:
            stats = item.get("statistics", {})
            top_values = item.get("top_values", [])
            column_rows.append({
                "Column": item["name"],
                "Type": item["type"],
                "Data type": item["dtype"],
                "Unique": item["unique_values"],
                "Missing": item["missing"],
                "Missing %": item["missing_percent"],
                "Min / earliest": stats.get("min", stats.get("earliest", "")),
                "Max / latest": stats.get("max", stats.get("latest", "")),
                "Mean": stats.get("mean", ""),
                "Median": stats.get("median", ""),
                "Top values": ", ".join(
                    f"{v['value']} ({v['count']})" for v in top_values
                ),
            })

        st.dataframe(
            pd.DataFrame(column_rows),
            use_container_width=True,
            hide_index=True,
        )

        selected_column = st.selectbox(
            "Inspect a column",
            [item["name"] for item in profile["columns"]],
            key="morrow_profile_column",
        )
        selected_profile = next(
            item for item in profile["columns"]
            if item["name"] == selected_column
        )
        st.json(selected_profile)

    with quality_tab:
        if profile["issues"]:
            st.dataframe(
                pd.DataFrame(profile["issues"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("No data-quality issues were detected in the loaded rows.")

    with recommendations_tab:
        if profile["recommendations"]:
            for recommendation in profile["recommendations"]:
                st.markdown(f"- {recommendation}")
        else:
            st.info(
                "No specific recommendations were generated from "
                "the detected column types."
            )


def render_dashboard(df, question, source_label):
    _render_data_profile(df)

    st.markdown("### Your data")
    st.caption(
        f"{source_label} · {len(df):,} rows loaded · "
        f"{len(df.columns)} columns"
    )
    with st.expander("Preview data and column types"):
        st.dataframe(df.head(100), use_container_width=True)
        st.json({
            str(c): str(t) for c, t in df.dtypes.items()
        })

    request = st.text_input(
        "Describe the dashboard you want",
        value=question,
        key="morrow_dashboard_request",
        placeholder="e.g. Monthly sales, top products, and order status",
    )

    if st.button("Generate dashboard ↗", type="primary",
                 key="morrow_generate_dashboard"):
        if not request.strip():
            st.warning("Describe the dashboard first.")
        else:
            try:
                with st.spinner("Morrow is planning your dashboard…"):
                    raw_plan = generate_dashboard_plan(request, df)
                    plan = _safe_plan(raw_plan, df)
                st.session_state.morrow_dashboard_plan = plan
                st.session_state.morrow_dashboard_df = df
                st.session_state.morrow_dashboard_source = source_label
            except Exception as exc:
                import traceback
                st.error(f"Dashboard generation failed: {type(exc).__name__}: {exc}")
                with st.expander("Technical details"):
                    st.code(traceback.format_exc())

    plan = st.session_state.get("morrow_dashboard_plan")
    saved_df = st.session_state.get("morrow_dashboard_df")
    if plan is None or saved_df is None:
        return

    # Only render the saved plan against the dataframe that generated it.
    if list(saved_df.columns) != list(df.columns):
        st.info("Generate a new dashboard for this data source.")
        return

    st.markdown("---")
    st.markdown(f"## {plan['title']}")
    if plan["summary"]:
        st.write(plan["summary"])

    metrics = []
    for item in plan["kpis"]:
        col, agg = item["column"], item["aggregation"]
        series = df[col] if agg == "count" else pd.to_numeric(
            df[col], errors="coerce"
        )
        if agg == "sum":
            value = series.sum()
        elif agg == "mean":
            value = series.mean()
        elif agg == "min":
            value = series.min()
        elif agg == "max":
            value = series.max()
        else:
            value = df[col].count()
        metrics.append((item["label"], value))

    if metrics:
        cards = st.columns(len(metrics))
        for card, (label, value) in zip(cards, metrics):
            if pd.isna(value):
                display = "—"
            elif isinstance(value, (int, float)) and abs(value) >= 1000:
                display = f"{value:,.2f}".rstrip("0").rstrip(".")
            elif isinstance(value, (int, float)):
                display = f"{value:,.2f}".rstrip("0").rstrip(".")
            else:
                display = str(value)
            card.metric(label, display)

    for start in range(0, len(plan["charts"]), 2):
        pair = plan["charts"][start:start + 2]
        slots = st.columns(len(pair))
        for slot, spec in zip(slots, pair):
            try:
                data, y_col = _aggregate_chart(df, spec)
                with slot:
                    st.markdown(f"**{spec['title']}**")
                    if spec["type"] == "pie":
                        fig = px.pie(data, names=spec["x"], values=y_col)
                    elif spec["type"] == "line":
                        fig = px.line(data, x=spec["x"], y=y_col, markers=True)
                    elif spec["type"] == "scatter":
                        fig = px.scatter(data, x=spec["x"], y=y_col)
                    else:
                        fig = px.bar(data, x=spec["x"], y=y_col)
                    fig.update_layout(
                        template="plotly_white",
                        margin=dict(l=12, r=12, t=25, b=12),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    with st.expander("View chart data"):
                        st.dataframe(data, use_container_width=True)
            except Exception as exc:
                st.warning(f"Couldn't render {spec['title']}: {exc}")

    # Deterministic insights: all figures come from the loaded DataFrame.
    st.markdown("---")
    st.markdown("### Key Data Insights")

    try:
        as_of_date = None

        if st.checkbox(
            "I can confirm the date through which this data is complete",
            value=False,
            key="insights_completeness_enabled",
        ):
            as_of_date = st.date_input(
                "Data complete through",
                value=None,
                key="insights_data_complete_through",
            )

            if as_of_date is None:
                st.info(
                    "Select the date through which the source data is complete. "
                    "Partial-period detection will remain inactive until then."
                )

        # Optional business context for grounded AI interpretation.
        with st.expander("Business context (optional)", expanded=False):
            currency_choice = st.selectbox(
                "Currency",
                [
                    "Not specified",
                    "INR (₹)",
                    "USD ($)",
                    "EUR (€)",
                    "GBP (£)",
                    "Other",
                ],
                key="insights_business_currency",
                help="Morrow will not assume a currency if you leave this unspecified.",
            )

            if currency_choice == "Other":
                currency = st.text_input(
                    "Specify currency",
                    key="insights_business_currency_other",
                    placeholder="e.g. JPY",
                ).strip() or None
            elif currency_choice == "Not specified":
                currency = None
            else:
                currency = currency_choice

            row_granularity = st.text_input(
                "What does one row represent?",
                key="insights_row_granularity",
                placeholder="e.g. One row per completed order",
            ).strip() or None

            measure_meaning = st.text_input(
                "What does the main numeric measure represent?",
                key="insights_measure_meaning",
                placeholder="e.g. Sales value of a completed order",
            ).strip() or None

        business_context = {
            "currency": currency,
            "row_granularity": row_granularity,
            "measure_meaning": measure_meaning,
        }


        # Explicit column mapping for deterministic business evidence.
        st.markdown("**Evidence engine configuration**")
        evidence_columns = [None] + list(df.columns)

        def evidence_column_label(value):
            return "Not selected" if value is None else str(value)

        col1, col2 = st.columns(2)

        with col1:
            evidence_sales_col = st.selectbox(
                "Sales / revenue column",
                evidence_columns,
                format_func=evidence_column_label,
                key="evidence_sales_column",
            )
            evidence_date_col = st.selectbox(
                "Date column",
                evidence_columns,
                format_func=evidence_column_label,
                key="evidence_date_column",
            )
            evidence_category_col = st.selectbox(
                "Category column (optional)",
                evidence_columns,
                format_func=evidence_column_label,
                key="evidence_category_column",
            )

        with col2:
            evidence_product_col = st.selectbox(
                "Product column (optional)",
                evidence_columns,
                format_func=evidence_column_label,
                key="evidence_product_column",
            )
            evidence_order_col = st.selectbox(
                "Order ID column (optional)",
                evidence_columns,
                format_func=evidence_column_label,
                key="evidence_order_column",
            )

        business_evidence = None
        recommendations = []

        if evidence_sales_col and evidence_date_col:
            business_evidence = calculate_business_evidence(
                df,
                sales_col=evidence_sales_col,
                date_col=evidence_date_col,
                category_col=evidence_category_col,
                product_col=evidence_product_col,
                order_id_col=evidence_order_col,
                as_of_date=as_of_date,
            )

            # A sampled dataset cannot establish full-source completeness.
            if df.attrs.get("is_sampled", False):
                business_evidence["evidence_quality"]["analysis_status"] = (
                    "provisional"
                )

            recommendations = generate_recommendations(business_evidence)

        factual = calculate_factual_insights(
            df,
            as_of_date=as_of_date,
            business_context=business_context,
        )
        scope = factual["scope"]

        if evidence_sales_col and evidence_date_col:
            st.markdown("---")

            if scope["is_sampled"]:
                st.warning(
                    "Sample-based analysis: recommendations below use only "
                    f"{scope['loaded_rows']:,} loaded rows. Sampling can omit "
                    "orders or order lines, so order counts and average order "
                    "values may be incomplete or distorted. Treat findings "
                    "as provisional, not full-dataset conclusions."
                )

            coverage_check = business_evidence.get(
                "automatic_coverage_check", {}
            )

            if coverage_check.get("status") == "potentially_partial":
                st.warning(
                    "Potentially incomplete latest month detected: "
                    f"{coverage_check['latest_period']}. "
                    f"Latest observed date: "
                    f"{coverage_check['latest_observed_date']} "
                    f"({coverage_check['days_before_month_end']} days "
                    "before month-end). This period is excluded from "
                    "normal monthly recommendations and AI diagnosis. "
                    "This is an automatic warning, not proof of missing data."
                )

            st.markdown("### Evidence-Based Diagnosis")

            diagnosis_brief = build_root_cause_brief(business_evidence)

            if diagnosis_brief["status"] == "decline_detected":
                sales = diagnosis_brief["sales_decline"]

                def display_amount(value):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        return f"{value:,.2f}"
                    return "Not available"

                def display_count(value):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
                    return "Not available"

                st.markdown("#### Revenue performance")
                sales_cols = st.columns(3)
                sales_cols[0].metric(
                    f"Previous sales · {sales['previous_period']}",
                    display_amount(sales.get("previous_sales")),
                )
                sales_cols[1].metric(
                    f"Current sales · {sales['current_period']}",
                    display_amount(sales.get("current_sales")),
                )
                sales_cols[2].metric(
                    "Sales change",
                    display_amount(sales.get("absolute_change")),
                    delta=(
                        f"{sales['percentage_change']:+.2f}%"
                        if isinstance(sales.get("percentage_change"), (int, float))
                        else None
                    ),
                )
                st.caption(
                    "Amounts use the dataset's units; no currency is assumed."
                )

                order_metrics = diagnosis_brief.get("order_metrics", {})
                if order_metrics.get("available"):
                    order_count = order_metrics.get("order_count")
                    aov = order_metrics.get("average_order_value")

                    st.markdown("#### Order intelligence")
                    order_cols = st.columns(3)
                    order_cols[0].metric(
                        "Previous orders",
                        display_count(order_count.get("previous"))
                        if order_count else "Not available",
                    )
                    order_cols[1].metric(
                        "Current orders",
                        display_count(order_count.get("current"))
                        if order_count else "Not available",
                    )
                    order_cols[2].metric(
                        "Order count change",
                        display_count(order_count.get("absolute_change"))
                        if order_count else "Not available",
                        delta=(
                            f"{order_count['percentage_change']:+.2f}%"
                            if order_count and isinstance(
                                order_count.get("percentage_change"), (int, float)
                            ) else None
                        ),
                    )

                    st.markdown("**Average order value**")
                    aov_cols = st.columns(3)
                    aov_cols[0].metric(
                        "Previous AOV",
                        display_amount(aov.get("previous")) if aov else "Not available",
                    )
                    aov_cols[1].metric(
                        "Current AOV",
                        display_amount(aov.get("current")) if aov else "Not available",
                    )
                    aov_cols[2].metric(
                        "AOV change",
                        display_amount(aov.get("absolute_change")) if aov else "Not available",
                        delta=(
                            f"{aov['percentage_change']:+.2f}%"
                            if aov and isinstance(
                                aov.get("percentage_change"), (int, float)
                            ) else None
                        ),
                    )

                category = diagnosis_brief.get("category_changes", {})
                if category.get("available") and category.get("declines"):
                    st.markdown("#### Category performance")
                    category_rows = [
                        {
                            "Category": item["name"],
                            "Sales change": display_amount(item["absolute_change"]),
                        }
                        for item in category["declines"]
                    ]
                    st.dataframe(
                        pd.DataFrame(category_rows),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.caption(
                    "Explains the latest eligible consecutive-month sales decline "
                    "using deterministic, calculated evidence."
                )

                if st.button(
                    "Generate Evidence-Based Diagnosis",
                    key="generate_root_cause_diagnosis",
                    type="primary",
                ):
                    with st.spinner(
                        "Morrow is investigating the available evidence..."
                    ):
                        try:
                            diagnosis_text = explain_root_cause(diagnosis_brief)
                            st.session_state["root_cause_result"] = {
                                "version": 3,
                                "brief": diagnosis_brief,
                                "text": diagnosis_text,
                            }
                        except Exception as exc:
                            st.error(str(exc))

                saved_diagnosis = st.session_state.get("root_cause_result")
                if (
                    saved_diagnosis
                    and saved_diagnosis.get("version") == 3
                    and saved_diagnosis.get("brief") == diagnosis_brief
                ):
                    st.markdown("#### Evidence interpretation")
                    st.markdown(saved_diagnosis["text"])
                    with st.expander("View evidence used by the diagnosis"):
                        st.json(diagnosis_brief)
            else:
                st.info(diagnosis_brief["message"])

            st.markdown("### Evidence-Based Recommendations")

            groups = [
                ("Sales performance", {"sales_decline"}),
                ("Category and product performance", {
                    "category_decline", "product_decline"
                }),
                ("Order intelligence", {
                    "order_count_decline", "aov_decline"
                }),
            ]

            if recommendations:
                for group_title, types in groups:
                    group_items = [
                        item for item in recommendations
                        if item.get("recommendation_type") in types
                    ]
                    if not group_items:
                        continue

                    st.markdown(f"#### {group_title}")

                    for index, recommendation in enumerate(group_items, 1):
                        with st.expander(
                            f"{recommendation['title']} "
                            f"({recommendation['priority'].upper()})",
                            expanded=(index == 1 and group_title == "Sales performance"),
                        ):
                            st.write(recommendation["observation"])

                            evidence = recommendation.get("evidence") or {}
                            previous_value = evidence.get("previous_value")
                            current_value = evidence.get("current_value")
                            percentage = evidence.get("percentage_change")
                            absolute_change = evidence.get("absolute_change")

                            if previous_value is not None and current_value is not None:
                                metric_cols = st.columns(3)
                                metric_cols[0].metric(
                                    "Previous period", f"{previous_value:,.2f}"
                                    if isinstance(previous_value, (int, float))
                                    else str(previous_value)
                                )
                                metric_cols[1].metric(
                                    "Current period", f"{current_value:,.2f}"
                                    if isinstance(current_value, (int, float))
                                    else str(current_value)
                                )
                                metric_cols[2].metric(
                                    "Change",
                                    f"{percentage:+.2f}%"
                                    if isinstance(percentage, (int, float))
                                    else (
                                        f"{absolute_change:,.2f}"
                                        if isinstance(absolute_change, (int, float))
                                        else "Not available"
                                    ),
                                )
                            elif isinstance(absolute_change, (int, float)):
                                st.metric("Absolute change", f"{absolute_change:,.2f}")

                            st.markdown("**Recommended action**")
                            st.write(recommendation["recommended_action"])
                            st.caption(
                                f"Evidence status: "
                                f"{recommendation['evidence_status']}"
                            )
                            with st.expander("Supporting evidence details"):
                                st.json(evidence)

                            for limitation in recommendation["limitations"]:
                                st.caption(f"Limitation: {limitation}")
            else:
                st.info(
                    "No recommendations meet the current evidence "
                    "and decline thresholds."
                )
        else:
            st.info(
                "Select both a sales/revenue column and a date column "
                "to activate evidence-based recommendations."
            )


        st.caption(
            f"Calculated from {scope['loaded_rows']:,} loaded rows."
        )

        if factual["numeric_metrics"]:
            st.markdown("**Numeric performance**")
            metric_table = pd.DataFrame(factual["numeric_metrics"])
            metric_table = metric_table.drop(
                columns=["average_definition"], errors="ignore"
            )
            metric_table = metric_table.rename(columns={
                "column": "Measure",
                "count": "Valid values",
                "total": "Total",
                "average": "Average",
                "minimum": "Minimum",
                "maximum": "Maximum",
            })
            st.dataframe(
                metric_table,
                use_container_width=True,
                hide_index=True,
            )

        if factual["monthly_trends"]:
            st.markdown("**Monthly trends**")
            for trend in factual["monthly_trends"]:
                if trend["highest_period"] is not None:
                    st.markdown(
                        f"- **{trend['measure']}** was highest in "
                        f"**{trend['highest_period']}** "
                        f"({trend['highest_value']:,.2f}) and lowest in "
                        f"**{trend['lowest_period']}** "
                        f"({trend['lowest_value']:,.2f}) among eligible months."
                    )
                else:
                    st.info(
                        "No complete months are available for highest/lowest "
                        "monthly performance rankings."
                    )

                changes = trend["monthly_changes"]

                partial_periods = [
                    item["period"] for item in changes
                    if item["period_status"] == "partial_period"
                ]
                future_periods = [
                    item["period"] for item in changes
                    if item["period_status"] == "after_completeness_date"
                ]

                if partial_periods:
                    st.warning(
                        "Partial month(s): "
                        + ", ".join(partial_periods)
                        + ". Their changes are provisional and excluded "
                        "from performance rankings."
                    )

                if future_periods:
                    st.warning(
                        "Month(s) outside declared data coverage: "
                        + ", ".join(future_periods)
                        + ". These periods are excluded from comparisons "
                        "and performance rankings."
                    )

                st.markdown("**Month-over-month performance**")
                change_table = pd.DataFrame(changes)
                change_table = change_table.drop(
                    columns=["is_provisional"], errors="ignore"
                )
                change_table = change_table.rename(columns={
                    "period": "Month",
                    "value": "Sales",
                    "previous_period": "Previous month",
                    "previous_value": "Previous sales",
                    "absolute_change": "Change",
                    "percentage_change": "Change (%)",
                    "comparison_status": "Comparison status",
                    "period_status": "Period status",
                })
                st.dataframe(
                    change_table,
                    use_container_width=True,
                    hide_index=True,
                )

                increase = trend["largest_increase"]
                decline = trend["largest_decline"]

                if increase:
                    st.markdown(
                        f"- Largest monthly increase: "
                        f"**{increase['period']}** "
                        f"({increase['absolute_change']:+,.2f}, "
                        f"{increase['percentage_change']:+.2f}%)."
                    )
                if decline:
                    st.markdown(
                        f"- Largest monthly decline: "
                        f"**{decline['period']}** "
                        f"({decline['absolute_change']:+,.2f}, "
                        f"{decline['percentage_change']:+.2f}%)."
                    )

        if factual["category_comparisons"]:
            st.markdown("**Category comparisons**")
            for comparison in factual["category_comparisons"]:
                line = (
                    f"- **{comparison['highest_category']}** had the "
                    f"highest {comparison['measure']} "
                    f"({comparison['highest_value']:,.2f}); "
                    f"**{comparison['lowest_category']}** had the lowest "
                    f"({comparison['lowest_value']:,.2f})."
                )
                difference = comparison["percentage_difference"]
                if difference is not None:
                    line += (
                        f" The highest was {difference:,.2f}% above "
                        "the lowest."
                    )
                else:
                    line += (
                        " Percentage difference was not calculated "
                        "because the lowest value was not positive."
                    )
                st.markdown(line)

        if not (
            factual["numeric_metrics"]
            or factual["monthly_trends"]
            or factual["category_comparisons"]
        ):
            st.info(
                "There are not enough suitable numeric, date, or "
                "categorical columns to calculate additional insights."
            )

        st.markdown("---")
        st.markdown("### AI Business Analysis")

        try:
            with st.spinner("Morrow is interpreting the verified findings…"):
                explanation = explain_factual_insights(factual)
            st.text(explanation)
        except Exception as exc:
            st.warning(f"AI explanation unavailable: {exc}")
            st.caption(
                "Your calculated factual insights above remain available."
            )

    except Exception as exc:
        st.warning(f"Could not calculate factual insights: {exc}")

    st.download_button(
        "Export loaded data as CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="morrow_dashboard_data.csv",
        mime="text/csv",
        key="morrow_dashboard_csv",
    )


def render_builder():
    st.markdown('<div class="eyebrow">MORROW / DASHBOARD STUDIO</div>',
                unsafe_allow_html=True)
    st.markdown("## Build a dashboard from a request")
    st.write(
        "Upload a dataset or connect to a local SQLite database. "
        "Morrow will plan charts and KPIs using your local Ollama model."
    )

    source = st.radio(
        "Data source",
        ["Upload CSV / Excel", "SQLite database"],
        horizontal=True,
        key="morrow_dashboard_source_choice",
    )

    if source == "Upload CSV / Excel":
        upload = st.file_uploader(
            "Choose a CSV or Excel file",
            type=["csv", "xlsx", "xlsm"],
            key="morrow_dashboard_upload",
            help="Files are read in memory; the first 5,000 rows are loaded.",
        )
        if upload is None:
            st.info("Upload a file to begin.")
            return
        try:
            df = read_upload(upload)
        except Exception as exc:
            st.error(f"Could not read the uploaded file: {exc}")
            return
        label = upload.name
    else:
        default_path = str(
            Path(__file__).resolve().parent.parent / "data" / "sales.db"
        )
        db_path = st.text_input(
            "SQLite database path",
            value=default_path,
            key="morrow_sqlite_path",
        )
        try:
            resolved = Path(db_path).expanduser().resolve()
            if not resolved.is_file():
                st.info("Enter the path to an existing SQLite database.")
                return
            uri = resolved.as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as conn:
                conn.execute("PRAGMA query_only=ON")
                tables = [
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    ).fetchall()
                ]
            if not tables:
                st.warning("No tables were found in this database.")
                return
            table = st.selectbox(
                "Choose a table", tables, key="morrow_sqlite_table"
            )
            df = read_sqlite_readonly(resolved, table)
            label = f"{resolved.name} · {table}"
        except Exception as exc:
            st.error(f"Could not inspect this database: {exc}")
            return

    render_dashboard(
        df,
        question="Show key metrics, trends, and useful breakdowns",
        source_label=label,
    )
