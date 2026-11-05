import pandas as pd
import streamlit as st
from app.agent import ask, AgentError, MODEL
from app.dashboard_builder import render_builder
from app.sales_dashboard import render_sales_dashboard, render_saved_dashboard_controls

st.set_page_config(
    page_title="Morrow | Intelligence",
    page_icon="✳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Cream, sage, peach. Dark ink is used only for readable text.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
 --cream:#F7F5EF; --paper:#FFFDF8; --sage:#9CAF98;
 --sage-dark:#496C53; --sage-pale:#E6EDE1; --peach:#E9A995;
 --peach-pale:#F8E5DC; --ink:#29372D; --muted:#788176;
 --line:#E5E2D8;
}
.stApp {background:var(--cream); color:var(--ink);}
header[data-testid="stHeader"] {background:var(--cream);}
.block-container {max-width:1380px;padding-top:1.6rem;padding-bottom:2rem;}
html,body,[class*="css"] {font-family:'DM Sans',sans-serif;color:var(--ink);}
h1,h2,h3,h4 {font-family:'Manrope',sans-serif!important;color:var(--ink)!important;letter-spacing:-.04em;}
p,li,label,span {color:inherit;}
[data-testid="stMarkdownContainer"] {color:var(--ink);}
[data-testid="stSidebar"] {background:#EEEFE6;border-right:1px solid var(--line);}
[data-testid="stSidebar"] * {color:var(--ink);}
[data-testid="stSidebar"] .block-container {padding-top:1.4rem;}
hr {border-color:var(--line);}
.brand {font-family:'Manrope',sans-serif;font-weight:800;font-size:1.55rem;letter-spacing:-.06em;}
.brand-icon {display:inline-flex;width:36px;height:36px;align-items:center;justify-content:center;
 background:var(--sage);border-radius:12px;margin-right:8px;color:var(--ink);font-size:1.4rem;}
.mono {font-family:'DM Mono',monospace;font-size:.69rem;letter-spacing:.09em;}
.eyebrow {font-size:.69rem;letter-spacing:.17em;font-weight:700;color:var(--sage-dark);}
.hero {font-family:'Manrope',sans-serif;font-size:clamp(2.2rem,4.2vw,4rem);line-height:1.03;
 letter-spacing:-.075em;font-weight:800;color:var(--ink);margin:.5rem 0;}
.sub {color:var(--muted);font-size:.96rem;line-height:1.65;max-width:580px;}
.status {display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border:1px solid #D4E0D0;
 border-radius:99px;background:var(--sage-pale);font-size:.76rem;color:var(--sage-dark);font-weight:700;}
.status-dot {height:7px;width:7px;border-radius:50%;background:#648E6C;box-shadow:0 0 0 4px #D4E5D1;}
.core-stage {display:flex;justify-content:center;align-items:center;min-height:245px;position:relative;overflow:hidden;}
.core-stage:before,.core-stage:after {content:"";position:absolute;border:1px solid #D8DFD1;border-radius:50%;
 width:220px;height:220px;animation:orbit 24s linear infinite;}
.core-stage:after {width:178px;height:178px;border-style:dashed;animation-direction:reverse;animation-duration:18s;}
.core {width:126px;height:126px;border-radius:50%;position:relative;z-index:2;
 background:radial-gradient(circle at 35% 30%,#FFFDF8 0%,#DCE8D6 22%,#9CAF98 55%,#E9A995 100%);
 box-shadow:0 0 30px #B7C9B080,0 0 75px #DCE8D660,inset 0 0 24px #FFFDF8;
 animation:breathe 4s ease-in-out infinite;}
.core:before {content:"";position:absolute;inset:13px;border:1px solid #FFFDF8B0;border-radius:50%;}
.core:after {content:"✳";position:absolute;inset:0;display:grid;place-items:center;font-size:2.8rem;color:#3E6046;}
.core-label {position:absolute;bottom:5px;left:0;right:0;text-align:center;font-size:.68rem;
 letter-spacing:.18em;color:var(--sage-dark);font-weight:700;}
@keyframes breathe {0%,100%{transform:scale(.96);filter:saturate(.9)}50%{transform:scale(1.04);filter:saturate(1.1)}}
@keyframes orbit {to{transform:rotate(360deg)}}
.panel {background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:18px;}
.stat {background:var(--paper);border:1px solid var(--line);border-radius:15px;padding:14px 16px;min-height:88px;}
.stat-label {font-size:.68rem;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;}
.stat-value {font-family:'Manrope',sans-serif;font-size:1.3rem;font-weight:800;margin-top:7px;color:var(--ink);}
.user-bubble {background:var(--sage-pale);border:1px solid #D8E2D3;border-radius:18px 18px 5px 18px;
 padding:13px 17px;margin:10px 0 16px auto;max-width:85%;width:fit-content;line-height:1.6;}
.assistant-card {background:var(--paper);border:1px solid var(--line);border-radius:5px 18px 18px 18px;padding:18px;margin:8px 0 18px;}
.answer-tag {font-size:.67rem;color:var(--sage-dark);letter-spacing:.14em;font-weight:800;margin-bottom:9px;}
div.stButton>button {border-radius:12px;border:1px solid var(--line);background:var(--paper);color:var(--ink);
 padding:.65rem .8rem;font-weight:600;transition:all .15s;}
div.stButton>button:hover {background:var(--sage-pale);border-color:var(--sage);color:var(--sage-dark);}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button {
 background:var(--sage-dark)!important;color:white!important;border:1px solid var(--sage-dark)!important;
 border-radius:12px!important;font-weight:700!important;}
div[data-testid="stTextInput"] input {background:var(--paper)!important;color:var(--ink)!important;border:1px solid #D9DCCF!important;border-radius:12px!important;}
div[data-testid="stMetric"] {background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:12px;}
div[data-testid="stMetricLabel"] {color:var(--muted);}
div[data-testid="stMetricValue"] {color:var(--ink);font-family:'Manrope',sans-serif;}
div[data-testid="stDataFrame"] {border:1px solid var(--line);border-radius:12px;overflow:hidden;}
div[data-testid="stExpander"] {background:var(--paper);border:1px solid var(--line);border-radius:12px;}
[data-testid="stChatInput"],[data-testid="stBottom"] {background:var(--cream)!important;}
.small-muted {font-size:.79rem;color:var(--muted);}
footer {visibility:hidden;}

/* Morrow interaction polish */
.status-dot { animation: statusPulse 2.2s ease-in-out infinite; }
@keyframes statusPulse {
  0%,100% { box-shadow: 0 0 0 3px #D4E5D1; opacity: 1; }
  50% { box-shadow: 0 0 0 7px #D4E5D140; opacity: .72; }
}
.panel, .assistant-card, .stat {
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.panel:hover, .assistant-card:hover {
  border-color: #C8D5C2;
  box-shadow: 0 8px 26px #29372D0B;
}
div.stButton > button {
  transition: transform .15s ease, background .15s ease, border-color .15s ease;
}
div.stButton > button:hover { transform: translateY(-1px); }
.core-stage { isolation: isolate; }
.core-stage:before { animation: orbit 28s linear infinite; }
.core-stage:after { animation: orbit 20s linear infinite reverse; }

</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None



def render_result(result, idx):
    rows = result.get("rows", [])
    columns = result.get("columns", [])
    elapsed = result.get("elapsed_seconds", 0)

    with st.container(border=True):
        st.markdown("**✳  MORROW ANALYSIS**")
        explanation = result.get("explanation", "").strip()
        st.write(explanation or "Query completed. Review the results below.")

    a, b, c = st.columns(3)
    with a:
        st.metric("Rows returned", result.get("row_count", len(rows)))
    with b:
        st.metric("Execution time", f"{elapsed}s")
    with c:
        st.metric("Assistant", "Morrow AI")

    if not columns:
        st.info("The query returned no columns to display.")
        return
    if not rows:
        st.info("No rows matched this question.")
        with st.expander("Inspect generated SQL"):
            st.code(result.get("sql", "-- no SQL returned"), language="sql")
        return

    df = pd.DataFrame(rows, columns=columns)
    currency_cols = [
        col for col in df.columns
        if any(term in col.lower() for term in
               ("revenue", "amount", "price", "sales", "total_value"))
    ]
    for col in currency_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    formatters = {
        col: (lambda value: f"₹{value:,.2f}" if pd.notna(value) else "—")
        for col in currency_cols
    }

    tab_data, tab_visual = st.tabs(["▤  Results", "◌  Visual analysis"])
    with tab_data:
        display_df = df.style.format(formatters, na_rep="—") if formatters else df
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.download_button(
            "↓  Export CSV",
            df.to_csv(index=False).encode("utf-8"),
            "morrow_results.csv",
            "text/csv",
            key=f"csv_{idx}",
        )

    with tab_visual:
        numeric = df.select_dtypes(include="number").columns.tolist()
        categories = [
            col for col in df.columns
            if col not in numeric and df[col].nunique(dropna=True) <= 50
        ]
        if len(df) < 2:
            st.info(
                "A chart needs at least two data points. "
                "This result is best shown as a KPI or table."
            )
        elif numeric and categories:
            left, right = st.columns(2)
            with left:
                x = st.selectbox("Group by", categories, key=f"x_{idx}")
            with right:
                y = st.selectbox("Measure", numeric, key=f"y_{idx}")
            chart_type = st.segmented_control(
                "Chart type", ["Bar", "Line", "Area"],
                default="Bar", key=f"chart_{idx}",
            )
            chart_df = df[[x, y]].copy()
            chart_df[y] = pd.to_numeric(chart_df[y], errors="coerce")
            chart_df = chart_df.dropna().set_index(x)
            if not chart_df.empty:
                if chart_type == "Line":
                    st.line_chart(chart_df, use_container_width=True)
                elif chart_type == "Area":
                    st.area_chart(chart_df, use_container_width=True)
                else:
                    st.bar_chart(chart_df, use_container_width=True)
            else:
                st.info("No numeric values available to chart.")
        elif numeric:
            chart_type = st.segmented_control(
                "Chart type", ["Bar", "Line", "Area"],
                default="Line", key=f"chart_{idx}",
            )
            chart_df = df[numeric].apply(pd.to_numeric, errors="coerce")
            if chart_type == "Bar":
                st.bar_chart(chart_df, use_container_width=True)
            elif chart_type == "Area":
                st.area_chart(chart_df, use_container_width=True)
            else:
                st.line_chart(chart_df, use_container_width=True)
        else:
            st.info("This result is best explored as a table.")

    with st.expander("Inspect generated SQL"):
        st.code(result.get("sql", "-- no SQL returned"), language="sql")
        st.caption("Generated by Morrow and executed against your local SQLite database.")



def run_question(question):
    question = question.strip()
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})

    normalized = question.lower().strip(" !.,?;")
    greetings = {
        "hi", "hello", "hey", "hello morrow", "hey morrow", "hi morrow",
        "good morning", "good afternoon", "good evening",
    }
    if normalized in greetings:
        st.session_state.messages.append({
            "role": "assistant",
            "content": (
                "Hey! I'm Morrow, your data analyst. 🌿\n\n"
                "I can explore sales, compare revenue, find customer patterns, "
                "and explain query results. What would you like to investigate?"
            ),
        })
        return

    try:
        with st.spinner("Morrow is working · preparing and running your query…"):
            result = ask(question)
        st.session_state.messages.append({"role": "assistant", "result": result})
    except Exception as exc:
        st.session_state.messages.append({
            "role": "assistant",
            "error": f"I couldn't complete that request: {exc}",
        })


# Sidebar
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-icon">✳</span>Morrow</div>', unsafe_allow_html=True)
    st.markdown('<div class="mono">PERSONAL DATA INTELLIGENCE</div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("**SYSTEM STATUS**")
    st.markdown('<div class="status"><span class="status-dot"></span> Agent ready</div>', unsafe_allow_html=True)
    st.caption("Engine · Morrow Intelligence")
    st.caption("Source · Local SQLite")
    st.caption("Mode · Private workspace")
    st.markdown("---")
    st.markdown("**QUICK COMMANDS**")
    quick = [
        "How many orders are there?",
        "Show order counts by status",
        "Which cities have the most customers?",
        "Top 5 products by completed-order revenue",
        "Show monthly revenue for completed orders in 2026",
    ]
    for i, prompt in enumerate(quick):
        if st.button(prompt, key=f"quick_{i}", use_container_width=True):
            st.session_state.pending = prompt
            st.rerun()
    st.markdown("---")
    if st.button("＋  New session", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pending = None
        st.rerun()
    st.markdown('<div class="small-muted">MORROW SYSTEMS · LOCAL-FIRST AI</div>', unsafe_allow_html=True)

# Header
left, right = st.columns([1.45, 1])
with left:
    st.markdown('<div class="eyebrow">MORROW / INTELLIGENCE SYSTEM</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero">Your data.<br>Your intelligence.</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub">A local AI analyst for exploring your business data. Ask naturally; inspect every query and result.</div>',
                unsafe_allow_html=True)
    st.markdown('<br><div class="status"><span class="status-dot"></span> Morrow Core online &nbsp; · &nbsp; Data source ready</div>',
                unsafe_allow_html=True)
with right:
    st.markdown("""
    <div class="core-stage">
      <div class="core"></div>
      <div class="core-label">MORROW CORE &nbsp; / &nbsp; STANDBY</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Dashboard Studio: isolated from the existing chat and query flow.
with st.expander("▦  Dashboard Studio · Generate interactive dashboards", expanded=False):
    render_builder()

# Persistent dashboard presets live outside nested expanders.
render_saved_dashboard_controls()

# Multi-table Sales Intelligence.
with st.expander("✳  Sales Intelligence · Revenue and product analytics", expanded=True):
    render_sales_dashboard()

# Conversation
if not st.session_state.messages:
    st.markdown("### What should I investigate?")
    st.markdown('<div class="small-muted">Select a mission or enter your own question below.</div>', unsafe_allow_html=True)
    s1, s2, s3 = st.columns(3)
    missions = [
        ("01  /  REVENUE", "Top products by revenue",
         "Which are the top 5 products by revenue from completed orders?"),
        ("02  /  OPERATIONS", "Orders by status",
         "Show the number of orders in each status."),
        ("03  /  TRENDS", "Monthly revenue",
         "Show monthly revenue for completed orders in 2026, sorted from January to December."),
    ]
    for col, (tag, label, query) in zip((s1, s2, s3), missions):
        with col:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown(f'<div class="eyebrow">{tag}</div>', unsafe_allow_html=True)
            st.markdown(f"**{label}**")
            if st.button("Run mission  ↗", key=f"mission_{tag}", use_container_width=True):
                st.session_state.pending = query
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
else:
    st.markdown("### Conversation log")

    for i, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            st.markdown(
                '<div style="display:flex;justify-content:flex-end">'
                '<div class="user-bubble">'
                + message["content"] +
                '</div></div>',
                unsafe_allow_html=True,
            )
        elif message.get("result"):
            render_result(message["result"], i)
        else:
            with st.container(border=True):
                st.markdown("**✳  MORROW**")
                st.write(message.get("content", message.get("error", "No response.")))

# Composer placed in normal page flow
st.markdown("---")
st.markdown('<div class="eyebrow">ASK MORROW</div>', unsafe_allow_html=True)
with st.form("morrow_composer", clear_on_submit=True):
    prompt = st.text_input(
        "Your question",
        placeholder="e.g. Which products generated the most completed-order revenue?",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Analyze  ↗", type="primary", use_container_width=True)

if submitted and prompt.strip():
    run_question(prompt)
    st.rerun()

if st.session_state.pending:
    pending = st.session_state.pending
    st.session_state.pending = None
    run_question(pending)
    st.rerun()

st.markdown('<div class="small-muted" style="text-align:center;padding:15px">Morrow · Local-first intelligence · Review SQL before relying on results</div>',
            unsafe_allow_html=True)
