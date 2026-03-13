import sys
from pathlib import Path
import tempfile

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from bom_fetcher import fetch_from_excel
from bom_graph_builder import build_graph, get_where_used
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
_SAMPLE_BOM = Path(__file__).parent.parent.parent / "Project Docs" / "Sample BOM.xlsx"

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
def _load_from_bytes(file_bytes: bytes, filename: str) -> tuple[SKURiskReport, nx.DiGraph]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        bom = fetch_from_excel(tmp_path)
        G = build_graph(bom)
        return compute_risk_report(bom, G), G
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@st.cache_data(show_spinner="Loading sample BOM…")
def _load_sample() -> tuple[SKURiskReport, nx.DiGraph]:
    bom = fetch_from_excel(str(_SAMPLE_BOM))
    G = build_graph(bom)
    return compute_risk_report(bom, G), G


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
        _AT_RISK = {"EOL", "LTB", "NRND"}
        sub_items = "; ".join(s.item_number for s in c.substitutes) or "—"
        sub_mfrs  = "; ".join(s.manufacturer or "?" for s in c.substitutes) or "—"
        sub_mpns  = "; ".join(s.mpn or "?" for s in c.substitutes) or "—"
        sub_lc    = "; ".join(
            f"{s.item_number}: {s.lifecycle_phase}"
            for s in c.substitutes if s.lifecycle_phase in _AT_RISK
        ) or "—"
        rows.append({
            "Risk":         c.substitute_risk.value,
            "Score":        c.risk_score,
            "Item #":       c.item_number,
            "Description":  (c.description or "")[:60],
            "Manufacturer": c.manufacturer or "—",
            "MPN":          c.mpn or "—",
            "Lifecycle":    c.lifecycle_phase or "—",
            "Criticality":  c.criticality_type or "—",
            "Origin":       c.country_of_origin or "—",
            "Lead Time":    str(int(c.lead_time_days)) if c.lead_time_days else "—",
            "MOQ":          str(int(c.moq)) if c.moq else "—",
            "Multi Source": c.multiple_source_status or "—",
            "Unique":       "Yes" if c.unique_to_samsara else ("No" if c.unique_to_samsara is not None else "—"),
            "Sub Item #":   sub_items,
            "Sub Mfr":      sub_mfrs,
            "Sub MPN":      sub_mpns,
            "Sub Lifecycle": sub_lc,
            "Drivers":      "; ".join(c.risk_drivers[:2]),
        })
    return pd.DataFrame(rows)


def _colour_risk(val: str) -> str:
    return {
        "HIGH":     "color: #f97316; font-weight: 600",
        "MEDIUM":   "color: #f59e0b; font-weight: 600",
        "LOW":      "color: #22c55e; font-weight: 600",
        "CRITICAL": "color: #ef4444; font-weight: 600",
    }.get(val, "")


def _build_comp_lookup(report: SKURiskReport) -> dict:
    return {c.item_number: c for c in report.component_risks}


def _show_component_detail(comp, G: nx.DiGraph, key_suffix: str) -> None:
    colour = _RISK_COLOURS.get(comp.substitute_risk.value, "#94a3b8")
    with st.expander(
        f"{comp.item_number} — {comp.description or 'No description'} "
        f"| Risk: {comp.substitute_risk.value}  Score: {comp.risk_score}",
        expanded=True,
    ):
        col_meta, col_risk = st.columns(2)

        with col_meta:
            st.markdown("**Component Details**")
            unique_str = ("Yes" if comp.unique_to_samsara else
                          ("No" if comp.unique_to_samsara is not None else "—"))
            lt = f"{int(comp.lead_time_days)} days" if comp.lead_time_days else "—"
            moq = int(comp.moq) if comp.moq else "—"
            st.markdown(f"""
| Field | Value |
|---|---|
| Criticality | {comp.criticality_type or '—'} |
| Country of Origin | {comp.country_of_origin or '—'} |
| Lead Time | {lt} |
| MOQ | {moq} |
| Unique to Samsara | {unique_str} |
| Multi Source Status | {comp.multiple_source_status or '—'} |
""")
            st.markdown("**Where Used**")
            used_by_ids = get_where_used(G, comp.item_number)
            if used_by_ids:
                node_data = [
                    {"SKU ID": sid, "Description": G.nodes.get(sid, {}).get("description", "—")}
                    for sid in used_by_ids
                ]
                st.dataframe(pd.DataFrame(node_data), hide_index=True, use_container_width=True)
            else:
                st.caption("Not directly used as a primary component in any loaded SKU.")

        with col_risk:
            st.markdown("**Risk Drivers**")
            if comp.risk_drivers:
                for d in comp.risk_drivers:
                    st.markdown(f"› {d}")
            else:
                st.caption("No risk drivers recorded.")

            _AT_RISK = {"EOL", "LTB", "NRND"}
            if comp.substitutes:
                st.markdown("**Substitutes**")
                sub_rows = []
                for s in comp.substitutes:
                    viable = s.lifecycle_phase not in _AT_RISK
                    same_mfr = (
                        "Yes ⚠" if (s.manufacturer and comp.manufacturer and s.manufacturer == comp.manufacturer)
                        else ("No" if (s.manufacturer and comp.manufacturer) else "—")
                    )
                    same_region = (
                        "Yes ⚠" if (s.country_of_origin and comp.country_of_origin and s.country_of_origin == comp.country_of_origin)
                        else ("No" if (s.country_of_origin and comp.country_of_origin) else "—")
                    )
                    sub_rows.append({
                        "Item #":            s.item_number,
                        "Manufacturer":      s.manufacturer or "—",
                        "MPN":               s.mpn or "—",
                        "Lifecycle":         s.lifecycle_phase or "—",
                        "Country of Origin": s.country_of_origin or "—",
                        "Viable":            "Yes" if viable else "No ⚠",
                        "Same Mfr":          same_mfr,
                        "Same Region":       same_region,
                    })
                st.dataframe(pd.DataFrame(sub_rows), hide_index=True, use_container_width=True)
            else:
                st.caption("No substitutes listed.")


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
    report, G = _load_from_bytes(uploaded.read(), uploaded.name)
elif _SAMPLE_BOM.exists():
    report, G = _load_sample()
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
    r1, r2, r3 = st.columns(3)
    r4, r5, r6 = st.columns(3)

    total = report.total_components
    ss_pct = round(report.single_source_count / total * 100) if total else 0

    r1.metric("Total Components",   total)
    r2.metric("Single Source",      report.single_source_count,
              delta=f"{ss_pct}% of BOM", delta_color="inverse")
    r3.metric("With Substitutes",   report.components_with_substitutes)
    r4.metric("EOL / LTB / NRND",  report.at_risk_lifecycle_count,
              help="Components with at-risk lifecycle phase")
    r5.metric("Critical Parts",     report.critical_parts_count,
              help="Field / Safety / Field & Safety components")
    r6.metric("Unique to Samsara",  report.unique_to_samsara_count,
              help="No ecosystem alternatives if discontinued")


# ── Category drill-down ──────────────────────────────────────────────────────
_DRILL_CATS = [
    ("Single Source",     report.single_source_count,         lambda c: c.substitute_risk.value == "HIGH"),
    ("With Substitutes",  report.components_with_substitutes, lambda c: len(c.substitutes) > 0),
    ("EOL / LTB / NRND",  report.at_risk_lifecycle_count,     lambda c: c.lifecycle_phase in {"EOL", "LTB", "NRND"}),
    ("Critical Parts",    report.critical_parts_count,        lambda c: c.criticality_type in {"Field", "Safety", "Field & Safety"}),
    ("Unique to Samsara", report.unique_to_samsara_count,     lambda c: c.unique_to_samsara is True),
]

for _label, _count, _filter in _DRILL_CATS:
    if _count == 0:
        continue
    with st.expander(f"{_label} — {_count} component{'s' if _count != 1 else ''}"):
        _rows = [
            {
                "Risk":         c.substitute_risk.value,
                "Score":        c.risk_score,
                "Item #":       c.item_number,
                "Description":  (c.description or "")[:60],
                "Manufacturer": c.manufacturer or "—",
                "MPN":          c.mpn or "—",
                "Lifecycle":    c.lifecycle_phase or "—",
            }
            for c in report.component_risks if _filter(c)
        ]
        _drill_styled = (
            pd.DataFrame(_rows).style
            .map(_colour_risk, subset=["Risk"])
            .background_gradient(subset=["Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
            .format({"Score": "{:.1f}"})
        )
        st.dataframe(_drill_styled, hide_index=True, use_container_width=True)


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


def _show_table(data: pd.DataFrame, key_suffix: str, report: SKURiskReport, G: nx.DiGraph) -> None:
    comp_lookup = _build_comp_lookup(report)

    # Feature 4 — CSV export
    st.download_button(
        label="Export CSV",
        data=data.to_csv(index=False).encode("utf-8"),
        file_name=f"bom-risk-{key_suffix}.csv",
        mime="text/csv",
        key=f"csv_{key_suffix}",
    )

    search = st.text_input(
        "Search", placeholder="Item # / description / manufacturer…",
        key=f"search_{key_suffix}", label_visibility="collapsed",
    )
    if search:
        mask = data.apply(lambda row: search.lower() in str(row).lower(), axis=1)
        data = data[mask]

    # Feature 3 — sortable columns: built into st.dataframe by default
    styled = (
        data.style
        .map(_colour_risk, subset=["Risk"])
        .background_gradient(subset=["Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
        .format({"Score": "{:.1f}"})
        .set_properties(subset=["Sub Item #", "Sub Mfr", "Sub MPN", "Sub Lifecycle"], **{"color": "#94a3b8"})
    )
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":        st.column_config.NumberColumn("Score", format="%.1f"),
            "Description":  st.column_config.TextColumn("Description", width="large"),
            "Criticality":  st.column_config.TextColumn("Criticality", width="small"),
            "Origin":       st.column_config.TextColumn("Country of Origin", width="small"),
            "Lead Time":    st.column_config.TextColumn("Lead Time (Days)", width="small"),
            "MOQ":          st.column_config.TextColumn("MOQ", width="small"),
            "Multi Source": st.column_config.TextColumn("Multi Source Status", width="small"),
            "Unique":       st.column_config.TextColumn("Unique to Samsara", width="small"),
            "Sub Item #":    st.column_config.TextColumn("Sub Item #", width="medium"),
            "Sub Mfr":       st.column_config.TextColumn("Sub Manufacturer", width="medium"),
            "Sub MPN":       st.column_config.TextColumn("Sub MPN", width="medium"),
            "Sub Lifecycle": st.column_config.TextColumn("Sub Lifecycle ⚠", width="medium"),
            "Drivers":      st.column_config.TextColumn("Risk Drivers", width="large"),
        },
    )
    st.caption(f"{len(data)} components shown")

    # Features 1 + 2 — two-step: Manufacturer → MPN → component detail
    mfrs = sorted(m for m in data["Manufacturer"].unique() if m != "—")
    mfr_options = ["— Select manufacturer —"] + mfrs
    sel_mfr = st.selectbox(
        "Manufacturer:", options=mfr_options,
        key=f"mfr_{key_suffix}", label_visibility="collapsed",
    )
    if sel_mfr != mfr_options[0]:
        mfr_df = data[data["Manufacturer"] == sel_mfr]
        mpn_display = [f"{row['MPN']}  ({row['Item #']})" for _, row in mfr_df.iterrows()]
        mpn_to_item = {f"{row['MPN']}  ({row['Item #']})": row['Item #'] for _, row in mfr_df.iterrows()}
        mpn_options = ["— Select MPN —"] + mpn_display
        sel_mpn = st.selectbox(
            "MPN:", options=mpn_options,
            key=f"mpn_{key_suffix}", label_visibility="collapsed",
        )
        if sel_mpn != mpn_options[0]:
            comp = comp_lookup.get(mpn_to_item[sel_mpn])
            if comp:
                _show_component_detail(comp, G, key_suffix)


with tab_all:    _show_table(df,                             "all",    report, G)
with tab_high:   _show_table(df[df.Risk == "HIGH"].copy(),   "high",   report, G)
with tab_medium: _show_table(df[df.Risk == "MEDIUM"].copy(), "medium", report, G)
with tab_low:    _show_table(df[df.Risk == "LOW"].copy(),    "low",    report, G)
