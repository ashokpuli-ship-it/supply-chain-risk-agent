import sys
from pathlib import Path
import tempfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from bom_fetcher import fetch_from_excel
from bom_graph_builder import build_graph
from models import SKURiskReport
from risk_engine import compute_risk_report

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BOM Intelligence Agent",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Constants ─────────────────────────────────────────────────────────────────
_SAMPLE_BOM = Path(__file__).parent.parent.parent / "project docs" / "Sample BOM.xlsx"

_RISK_COLOURS = {
    "CRITICAL": "#ef4444",
    "HIGH":     "#f97316",
    "MEDIUM":   "#f59e0b",
    "LOW":      "#22c55e",
}

_RISK_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🟢",
}

# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Parsing BOM and computing risk…")
def _load_from_bytes(file_bytes: bytes, filename: str) -> SKURiskReport:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        bom = fetch_from_excel(tmp_path)
        G = build_graph(bom)
        return compute_risk_report(bom, G)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@st.cache_data(show_spinner="Loading sample BOM…")
def _load_sample() -> SKURiskReport:
    bom = fetch_from_excel(str(_SAMPLE_BOM))
    G = build_graph(bom)
    return compute_risk_report(bom, G)


# ── Plotly gauge ──────────────────────────────────────────────────────────────
def _gauge(score: float, level: str) -> go.Figure:
    colour = _RISK_COLOURS.get(level, "#6366f1")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"font": {"size": 44, "color": "white"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#64748b", "tickfont": {"color": "#64748b"}},
            "bar": {"color": colour, "thickness": 0.25},
            "bgcolor": "#0f172a",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  30], "color": "#052e16"},
                {"range": [30, 55], "color": "#422006"},
                {"range": [55, 80], "color": "#431407"},
                {"range": [80, 100], "color": "#450a0a"},
            ],
            "threshold": {"line": {"color": colour, "width": 3}, "value": score},
        },
        title={"text": "Risk Score (0–100)", "font": {"color": "#94a3b8", "size": 13}},
    ))
    fig.update_layout(
        paper_bgcolor="#1e293b",
        plot_bgcolor="#1e293b",
        font={"color": "white"},
        height=240,
        margin={"t": 60, "b": 0, "l": 20, "r": 20},
    )
    return fig


# ── Component DataFrame ───────────────────────────────────────────────────────
def _to_df(report: SKURiskReport) -> pd.DataFrame:
    rows = []
    for c in report.component_risks:
        rows.append({
            "Risk":        c.substitute_risk.value,
            "Score":       c.risk_score,
            "Item #":      c.item_number,
            "Description": (c.description or "")[:60],
            "Manufacturer": c.manufacturer or "—",
            "MPN":         c.mpn or "—",
            "Lifecycle":   c.lifecycle_phase or "—",
            "Criticality": c.criticality_type or "—",
            "Alternates":  len(c.substitutes),
            "Drivers":     "; ".join(c.risk_drivers[:2]),
        })
    return pd.DataFrame(rows)


def _colour_risk(val: str) -> str:
    return {
        "HIGH":     "color: #f97316; font-weight: 600",
        "MEDIUM":   "color: #f59e0b; font-weight: 600",
        "LOW":      "color: #22c55e; font-weight: 600",
        "CRITICAL": "color: #ef4444; font-weight: 600",
    }.get(val, "")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ◈ BOM Intelligence Agent")
    st.caption("Supply Chain Risk Platform — Phase 1 POC")
    st.divider()

    uploaded = st.file_uploader(
        "Upload Propel BOM Export (.xlsx)",
        type=["xlsx"],
        help="Export a BOM from Propel PLM and upload here.",
    )

    if not uploaded and _SAMPLE_BOM.exists():
        st.info("No file uploaded — using built-in sample BOM.", icon="ℹ️")

    st.divider()
    st.markdown("**Local dev — FastAPI**")
    st.code("uvicorn api:app --reload --port 8000", language="bash")
    st.caption("`/docs` for interactive API explorer")


# ── Load report ───────────────────────────────────────────────────────────────
report: SKURiskReport | None = None

if uploaded:
    report = _load_from_bytes(uploaded.read(), uploaded.name)
elif _SAMPLE_BOM.exists():
    report = _load_sample()
else:
    st.warning(
        "No BOM file loaded. Upload a Propel BOM Excel export using the sidebar.",
        icon="⚠️",
    )
    st.stop()


# ── Header ────────────────────────────────────────────────────────────────────
level_emoji = _RISK_EMOJI.get(report.risk_level, "⚪")
st.markdown(f"## {level_emoji} BOM Risk Report — `{report.sku_id}`")
st.caption(report.description)


# ── Summary row ───────────────────────────────────────────────────────────────
col_gauge, col_stats = st.columns([1, 2.5], gap="large")

with col_gauge:
    st.plotly_chart(_gauge(report.risk_score, report.risk_level), use_container_width=True)
    colour = _RISK_COLOURS[report.risk_level]
    st.markdown(
        f"<div style='text-align:center;margin-top:-16px'>"
        f"<span style='font-size:18px;font-weight:700;color:{colour}'>"
        f"{report.risk_level} RISK</span></div>",
        unsafe_allow_html=True,
    )

with col_stats:
    r1, r2 = st.columns(2)
    r3, r4 = st.columns(2)

    total = report.total_components
    ss_pct = round(report.single_source_count / total * 100) if total else 0

    r1.metric("Total Components",  total)
    r2.metric("Single Source",     report.single_source_count,
              delta=f"{ss_pct}% of BOM", delta_color="inverse")
    r3.metric("With Substitutes",  report.components_with_substitutes)
    r4.metric("Development Phase", report.development_lifecycle_count,
              help="Components not yet production-qualified")


# ── Top risk drivers ──────────────────────────────────────────────────────────
st.subheader("Top Risk Drivers", divider="red")
for risk_msg in report.top_risks:
    st.markdown(f"› {risk_msg}")


# ── Component table ───────────────────────────────────────────────────────────
st.subheader("Components", divider="gray")

df = _to_df(report)

counts = {r: len(df[df.Risk == r]) for r in ["HIGH", "MEDIUM", "LOW"]}
tab_all, tab_high, tab_medium, tab_low = st.tabs([
    f"All ({len(df)})",
    f"HIGH ({counts['HIGH']})",
    f"MEDIUM ({counts['MEDIUM']})",
    f"LOW ({counts['LOW']})",
])


def _show_table(data: pd.DataFrame, key_suffix: str) -> None:
    search = st.text_input(
        "Search", placeholder="Item # / description / manufacturer…",
        key=f"search_{key_suffix}", label_visibility="collapsed",
    )
    if search:
        mask = data.apply(lambda row: search.lower() in str(row).lower(), axis=1)
        data = data[mask]

    styled = (
        data.style
        .map(_colour_risk, subset=["Risk"])
        .background_gradient(subset=["Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
        .format({"Score": "{:.1f}"})
    )
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":       st.column_config.NumberColumn("Score", format="%.1f"),
            "Alternates":  st.column_config.NumberColumn("Alts", width="small"),
            "Drivers":     st.column_config.TextColumn("Risk Drivers", width="large"),
            "Description": st.column_config.TextColumn("Description", width="large"),
        },
    )
    st.caption(f"{len(data)} components shown")


with tab_all:    _show_table(df, "all")
with tab_high:   _show_table(df[df.Risk == "HIGH"].copy(),   "high")
with tab_medium: _show_table(df[df.Risk == "MEDIUM"].copy(), "medium")
with tab_low:    _show_table(df[df.Risk == "LOW"].copy(),    "low")
