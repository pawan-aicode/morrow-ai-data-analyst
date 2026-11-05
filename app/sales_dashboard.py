"""Read-only, multi-table Sales Intelligence dashboard for Morrow."""

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from app.agent import DB_PATH
from app.saved_dashboards import (
    list_dashboards, save_dashboard, load_dashboard, delete_dashboard,
)


COLORS = ["#496C53", "#9CAF98", "#E9A995", "#C9D8C3", "#D7A96B"]


@st.cache_data(ttl=60, show_spinner=False)
def load_sales_data():
    """Join sales tables using a read-only SQLite connection."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Sales database not found: {DB_PATH}")

    uri = DB_PATH.resolve().as_uri() + "?mode=ro"

    query = """
        SELECT
            o.order_id,
            o.order_date,
            o.status,
            c.city,
            p.product_id,
            p.product_name,
            p.category,
            oi.quantity,
            oi.unit_price,
            oi.quantity * oi.unit_price AS revenue
        FROM orders AS o
        JOIN order_items AS oi ON oi.order_id = o.order_id
        JOIN products AS p ON p.product_id = oi.product_id
        LEFT JOIN customers AS c ON c.customer_id = o.customer_id
        ORDER BY o.order_date, o.order_id
    """

    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        df = pd.read_sql_query(query, conn)

    if df.empty:
        raise ValueError("No joined sales records were found.")

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0)
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0)
    df = df.dropna(subset=["order_date"])

    return df


def _money(value):
    return f"₹{value:,.0f}"


def _load_selected_dashboard():
    """Restore saved filters in a Streamlit callback before the next script run."""
    try:
        selected = st.session_state.get("sales_saved_select")
        if not selected:
            raise ValueError("Select a saved dashboard first.")

        cfg = load_dashboard(selected)

        start = date.fromisoformat(cfg["start_date"])
        end = date.fromisoformat(cfg["end_date"])
        if start > end:
            raise ValueError("Saved start date is after end date.")

        st.session_state["sales_date_range"] = (start, end)
        st.session_state["sales_status_filter"] = cfg.get(
            "status", "All statuses"
        )
        st.session_state["sales_category_filter"] = cfg.get(
            "category", "All categories"
        )
        st.session_state["sales_completed_only"] = bool(
            cfg.get("completed_only", False)
        )

        st.session_state["sales_load_notice"] = (
            f"Loaded dashboard setup: {selected}"
        )
        st.session_state.pop("sales_load_error", None)

    except Exception as exc:
        st.session_state["sales_load_error"] = str(exc)


def render_saved_dashboard_controls():
    # Saved configurations survive app and machine restarts.
    saved_items = list_dashboards()
    saved_names = [item["name"] for item in saved_items]

    with st.expander("Save / load dashboard setup", expanded=True):
        if saved_names:
            st.selectbox(
                "Saved dashboards",
                saved_names,
                key="sales_saved_select",
            )
            a, b = st.columns(2)

            a.button(
                "Load setup",
                key="sales_load_saved",
                use_container_width=True,
                on_click=_load_selected_dashboard,
            )

            if b.button(
                "Delete setup",
                key="sales_delete_saved",
                use_container_width=True,
            ):
                try:
                    selected = st.session_state["sales_saved_select"]
                    delete_dashboard(selected)
                    st.success(f"Deleted {selected}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not delete setup: {exc}")
        else:
            st.caption("No saved dashboard setups yet.")

        load_error = st.session_state.pop("sales_load_error", None)
        if load_error:
            st.error(f"Could not load setup: {load_error}")



def render_sales_dashboard():
    st.markdown(
        '<div class="eyebrow">MORROW / SALES INTELLIGENCE</div>',
        unsafe_allow_html=True,
    )
    st.markdown("## Sales Intelligence")
    st.write(
        "A joined view of orders, line items, products, and customer cities. "
        "All metrics below are calculated from database records."
    )

    try:
        df = load_sales_data()
    except Exception as exc:
        st.error(f"Could not load sales data: {type(exc).__name__}: {exc}")
        return

    first_date = df["order_date"].min().date()
    last_date = df["order_date"].max().date()

    f1, f2, f3, f4 = st.columns([1.5, 1, 1, 1])
    with f1:
        # The session-state value takes precedence when restoring a preset.
        # Use the full data range only when no valid selection exists yet.
        default_range = st.session_state.get(
            "sales_date_range", (first_date, last_date)
        )
        if (
            not isinstance(default_range, (tuple, list))
            or len(default_range) != 2
            or not all(isinstance(d, date) for d in default_range)
            or default_range[0] < first_date
            or default_range[1] > last_date
            or default_range[0] > default_range[1]
        ):
            default_range = (first_date, last_date)

        date_range = st.date_input(
            "Order date range",
            value=tuple(default_range),
            min_value=first_date,
            max_value=last_date,
            key="sales_date_range",
        )
    with f2:
        statuses = ["All statuses"] + sorted(
            df["status"].dropna().astype(str).unique().tolist()
        )
        selected_status = st.selectbox(
            "Order status", statuses, key="sales_status_filter"
        )
    with f3:
        categories = ["All categories"] + sorted(
            df["category"].dropna().astype(str).unique().tolist()
        )
        selected_category = st.selectbox(
            "Product category", categories, key="sales_category_filter"
        )
    with f4:
        completed_only = st.checkbox(
            "Completed only", key="sales_completed_only"
        )

    load_notice = st.session_state.pop("sales_load_notice", None)
    if load_notice:
        st.success(load_notice)

    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select both a start date and an end date.")
        return

    start_date, end_date = date_range
    if start_date > end_date:
        st.warning("Start date must be on or before end date.")
        return

    filtered = df[
        df["order_date"].dt.date.between(start_date, end_date)
    ].copy()

    if selected_status != "All statuses":
        filtered = filtered[filtered["status"] == selected_status]

    if selected_category != "All categories":
        filtered = filtered[filtered["category"] == selected_category]

    if completed_only:
        filtered = filtered[filtered["status"] == "completed"]

    # Capture the exact filter values currently selected in the UI.
    current_config = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": selected_status,
        "category": selected_category,
        "completed_only": bool(completed_only),
    }
    st.session_state["sales_current_config"] = current_config

    # Save is deliberately placed after reading the current filter widgets.
    st.markdown("**Save these filter settings**")
    save_col, button_col = st.columns([2, 1])
    with save_col:
        save_name = st.text_input(
            "Name this dashboard setup",
            placeholder="e.g. Completed sales 2026",
            key="sales_save_name",
        )
    with button_col:
        st.write("")
        if st.button(
            "Save current setup",
            key="sales_save_current",
            use_container_width=True,
        ):
            if not save_name.strip():
                st.warning("Enter a name for this setup.")
            else:
                try:
                    save_dashboard(save_name, current_config)
                    st.success(f"Saved setup: {save_name.strip()}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save setup: {exc}")

    if filtered.empty:
        st.warning("No records match these filters. You can still save this setup.")
        return

    # Order-level metrics must count distinct orders, not line items.
    order_summary = filtered.groupby("order_id", as_index=False).agg(
        order_revenue=("revenue", "sum"),
        order_status=("status", "first"),
        order_date=("order_date", "first"),
    )

    total_revenue = filtered["revenue"].sum()
    order_count = filtered["order_id"].nunique()
    units_sold = filtered["quantity"].sum()
    average_order_value = (
        order_summary["order_revenue"].mean()
        if not order_summary.empty else 0
    )

    st.caption(
        f"{len(filtered):,} line items · "
        f"{order_count:,} distinct orders · "
        f"{start_date} to {end_date}"
    )

    k1, k2, k3, k4 = st.columns(4)
    revenue_label = (
        "Completed revenue" if completed_only else "Revenue · all selected statuses"
    )
    k1.metric(revenue_label, _money(total_revenue))
    k2.metric("Distinct orders", f"{order_count:,}")
    k3.metric("Units sold", f"{units_sold:,.0f}")
    k4.metric("Average order value", _money(average_order_value))

    st.markdown("---")

    # Aggregate revenue by month after applying all active filters.
    monthly_source = filtered.copy()
    monthly_source["month"] = (
        monthly_source["order_date"].dt.to_period("M").dt.to_timestamp()
    )
    monthly = (
        monthly_source.groupby("month", as_index=False)["revenue"]
        .sum()
        .sort_values("month")
    )

    product_revenue = (
        filtered.groupby("product_name", as_index=False)["revenue"]
        .sum()
        .sort_values("revenue", ascending=False)
        .head(5)
    )

    status_counts = (
        filtered.groupby("status", as_index=False)["order_id"]
        .nunique()
        .rename(columns={"order_id": "orders"})
        .sort_values("orders", ascending=False)
    )

    category_revenue = (
        filtered.groupby("category", as_index=False)["revenue"]
        .sum()
        .sort_values("revenue", ascending=False)
    )

    left, right = st.columns(2)

    with left:
        st.markdown("**Monthly revenue**")
        fig = px.line(
            monthly, x="month", y="revenue", markers=True,
            color_discrete_sequence=[COLORS[0]],
        )
        fig.update_layout(
            template="plotly_white",
            xaxis_title=None,
            yaxis_title="Revenue (₹)",
            margin=dict(l=10, r=10, t=15, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("**Top 5 products by revenue**")
        product_revenue = product_revenue.sort_values("revenue")
        fig = px.bar(
            product_revenue, x="revenue", y="product_name",
            orientation="h",
            color_discrete_sequence=[COLORS[0]],
        )
        fig.update_layout(
            template="plotly_white",
            xaxis_title="Revenue (₹)",
            yaxis_title=None,
            margin=dict(l=10, r=10, t=15, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)

    with left:
        st.markdown("**Distinct orders by status**")
        fig = px.pie(
            status_counts, names="status", values="orders",
            color_discrete_sequence=COLORS,
            hole=0.48,
        )
        fig.update_layout(
            template="plotly_white",
            margin=dict(l=10, r=10, t=15, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("**Revenue by product category**")
        fig = px.bar(
            category_revenue, x="category", y="revenue",
            color_discrete_sequence=[COLORS[2]],
        )
        fig.update_layout(
            template="plotly_white",
            xaxis_title=None,
            yaxis_title="Revenue (₹)",
            margin=dict(l=10, r=10, t=15, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Auditable monthly totals: the table uses the same filtered rows as the chart.
    st.markdown("**Monthly revenue detail**")
    monthly_detail = monthly.copy()
    monthly_detail["month"] = monthly_detail["month"].dt.strftime("%b %Y")
    monthly_detail["revenue"] = monthly_detail["revenue"].round(2)
    st.dataframe(
        monthly_detail.rename(columns={
            "month": "Month",
            "revenue": "Revenue (₹)",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # Reconciliation: monthly totals must equal revenue in the filtered rows.
    monthly_total = float(monthly["revenue"].sum())
    filtered_total = float(filtered["revenue"].sum())
    if abs(monthly_total - filtered_total) > 0.01:
        st.warning(
            "Monthly revenue totals do not reconcile with filtered revenue. "
            "Please inspect the source data before relying on this dashboard."
        )
    else:
        st.caption("Monthly revenue reconciles with the selected revenue total.")

    with st.expander("Inspect joined sales records"):
        st.dataframe(
            filtered.sort_values("order_date", ascending=False),
            use_container_width=True,
        )

    st.download_button(
        "Export filtered sales records as CSV",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name="morrow_sales_intelligence.csv",
        mime="text/csv",
        key="sales_intelligence_export",
    )

    st.caption(
        "Revenue = quantity × order-item unit price. "
        + (
            "Completed-only mode excludes cancelled, processing, and shipped orders. "
            if completed_only else
            "Revenue includes every selected order status unless filtered above. "
        )
        + "Average order value is calculated from distinct order totals."
    )
