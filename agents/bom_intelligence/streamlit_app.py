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
from lifecycle_agent import compute_lifecycle_report
from models import CompositeRiskReport, LifecycleRiskReport, SKURiskReport
from orchestrator import compute_composite_report
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
def _load_from_bytes(
    file_bytes: bytes, filename: str
) -> tuple[SKURiskReport, nx.DiGraph, LifecycleRiskReport, CompositeRiskReport]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        bom = fetch_from_excel(tmp_path)
        G = build_graph(bom)
        structural = compute_risk_report(bom, G)
        lifecycle = compute_lifecycle_report(bom)
        composite = compute_composite_report(bom, structural, lifecycle)
        return structural, G, lifecycle, composite
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@st.cache_data(show_spinner="Loading sample BOM…")
def _load_sample() -> tuple[SKURiskReport, nx.DiGraph, LifecycleRiskReport, CompositeRiskReport]:
    bom = fetch_from_excel(str(_SAMPLE_BOM))
    G = build_graph(bom)
    structural = compute_risk_report(bom, G)
    lifecycle = compute_lifecycle_report(bom)
    composite = compute_composite_report(bom, structural, lifecycle)
    return structural, G, lifecycle, composite


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


def _show_component_detail(comp, G: nx.DiGraph, key_suffix: str, lc_comp=None, corr_signals=None) -> None:
    """Combined per-component inspection report: structural + lifecycle agents."""
    struct_level = comp.substitute_risk.value
    lc_level = lc_comp.lifecycle_risk_level if lc_comp else None
    lc_score_str = f"{lc_comp.lifecycle_risk_score:.0f}" if lc_comp else "—"

    title = (
        f"{comp.item_number} — {comp.description or 'No description'} "
        f"| Structural: {struct_level}  {comp.risk_score}"
        + (f" | Lifecycle: {lc_level}  {lc_score_str}" if lc_comp else "")
    )
    with st.expander(title, expanded=True):
        # ── Score badges row ──────────────────────────────────────────────────
        badge_cols = st.columns(2 if lc_comp else 1)
        s_colour = _RISK_COLOURS.get(struct_level, "#94a3b8")
        badge_cols[0].markdown(
            f"<div style='text-align:center;padding:8px;border-radius:8px;"
            f"background:#1e293b;border:1px solid #334155'>"
            f"<div style='font-size:11px;color:#64748b;text-transform:uppercase;"
            f"letter-spacing:.05em'>Structural Risk Score</div>"
            f"<div style='font-size:32px;font-weight:700;color:{s_colour}'>{comp.risk_score}</div>"
            f"<div style='font-size:12px;font-weight:600;color:{s_colour}'>{struct_level}</div>"
            f"<div style='font-size:10px;color:#64748b'>BOM Intelligence Agent</div></div>",
            unsafe_allow_html=True,
        )
        if lc_comp:
            lc_colour = _RISK_COLOURS.get(lc_level, "#94a3b8")
            badge_cols[1].markdown(
                f"<div style='text-align:center;padding:8px;border-radius:8px;"
                f"background:#1e293b;border:1px solid #334155'>"
                f"<div style='font-size:11px;color:#64748b;text-transform:uppercase;"
                f"letter-spacing:.05em'>Lifecycle Risk Score</div>"
                f"<div style='font-size:32px;font-weight:700;color:{lc_colour}'>{lc_score_str}</div>"
                f"<div style='font-size:12px;font-weight:600;color:{lc_colour}'>{lc_level}</div>"
                f"<div style='font-size:10px;color:#64748b'>Lifecycle & Obsolescence Agent</div></div>",
                unsafe_allow_html=True,
            )

        # Compound risk signals for this component
        if corr_signals:
            comp_name = (comp.description or "").lower()
            relevant = [s for s in corr_signals
                        if comp_name and comp_name in s.lower()
                        or comp.item_number in s]
            for sig in relevant:
                st.warning(sig, icon="⚡")

        st.markdown("")  # spacer

        # ── 3-column detail ───────────────────────────────────────────────────
        col_meta, col_struct, col_lc = st.columns(3)

        # Column 1 — Component Details + Where Used
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

        # Column 2 — Structural Risk Drivers + Substitutes
        with col_struct:
            st.markdown("**Structural Risk Drivers**")
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

        # Column 3 — Lifecycle & Obsolescence
        with col_lc:
            st.markdown("**Lifecycle & Obsolescence**")
            if lc_comp:
                yrs = f"{lc_comp.estimated_years_to_eol:.1f}" if lc_comp.estimated_years_to_eol is not None else "—"
                dist = str(lc_comp.number_of_distributors) if lc_comp.number_of_distributors is not None else "—"
                st.markdown(f"""
| Field | Value |
|---|---|
| SE Lifecycle Stage | {lc_comp.lifecycle_stage or '—'} |
| Estimated Years to EOL | {yrs} |
| EOL Date | {lc_comp.estimated_eol_date or '—'} |
| # Distributors | {dist} |
| Counterfeit Risk | {lc_comp.counterfeit_risk or '—'} |
""")
                if lc_comp.risk_drivers:
                    st.markdown("**Lifecycle Risk Drivers**")
                    for d in lc_comp.risk_drivers:
                        st.markdown(f"› {d}")
                else:
                    st.caption("No lifecycle risk drivers.")
            else:
                st.caption("No lifecycle data available for this component.")


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
    report, G, lifecycle_report, composite_report = _load_from_bytes(uploaded.read(), uploaded.name)
elif _SAMPLE_BOM.exists():
    report, G, lifecycle_report, composite_report = _load_sample()
else:
    st.warning(
        "No BOM file loaded. Upload a Propel BOM Excel export using the sidebar.",
        icon="⚠️",
    )
    st.stop()

# Fast lookup maps available across all tabs
_struct_lookup: dict = {c.item_number: c for c in report.component_risks}
_lc_lookup: dict = {c.item_number: c for c in lifecycle_report.component_risks}


# ── Header ────────────────────────────────────────────────────────────────────
comp_emoji = _RISK_EMOJI.get(composite_report.composite_risk_level, "⚪")
st.markdown(f"## {comp_emoji} BOM Risk Report — `{report.sku_id}`")
st.caption(report.description)

# ── Composite + agent gauges ──────────────────────────────────────────────────
col_comp, col_struct, col_lc = st.columns(3, gap="large")

with col_comp:
    st.plotly_chart(_gauge(composite_report.composite_risk_score, composite_report.composite_risk_level), use_container_width=True)
    c_colour = _RISK_COLOURS[composite_report.composite_risk_level]
    st.markdown(
        f"<div style='text-align:center;margin-top:-16px'>"
        f"<span style='font-size:14px;font-weight:700;color:{c_colour}'>"
        f"COMPOSITE — {composite_report.composite_risk_level}</span><br>"
        f"<span style='font-size:11px;color:#64748b'>Phase 1 · 2 agents active</span></div>",
        unsafe_allow_html=True,
    )

with col_struct:
    st.plotly_chart(_gauge(report.risk_score, report.risk_level), use_container_width=True)
    s_colour = _RISK_COLOURS[report.risk_level]
    st.markdown(
        f"<div style='text-align:center;margin-top:-16px'>"
        f"<span style='font-size:14px;font-weight:700;color:{s_colour}'>"
        f"STRUCTURAL — {report.risk_level}</span><br>"
        f"<span style='font-size:11px;color:#64748b'>BOM Intelligence Agent</span></div>",
        unsafe_allow_html=True,
    )

with col_lc:
    st.plotly_chart(_gauge(lifecycle_report.lifecycle_risk_score, lifecycle_report.lifecycle_risk_level), use_container_width=True)
    lc_colour = _RISK_COLOURS[lifecycle_report.lifecycle_risk_level]
    st.markdown(
        f"<div style='text-align:center;margin-top:-16px'>"
        f"<span style='font-size:14px;font-weight:700;color:{lc_colour}'>"
        f"LIFECYCLE — {lifecycle_report.lifecycle_risk_level}</span><br>"
        f"<span style='font-size:11px;color:#64748b'>Lifecycle & Obsolescence Agent</span></div>",
        unsafe_allow_html=True,
    )

# Correlation signals (if any)
if composite_report.correlation_signals:
    st.markdown("**⚠ Compound Risk Signals**")
    for sig in composite_report.correlation_signals:
        st.warning(sig, icon="⚠️")

st.divider()

# ── Tabbed views: BOM Risk | Lifecycle Risk ───────────────────────────────────
tab_bom, tab_lc = st.tabs(["BOM Risk (Structural)", "Lifecycle & Obsolescence"])

with tab_bom:
    # ── Metric cards ──────────────────────────────────────────────────────────
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

    # ── Category drill-down ───────────────────────────────────────────────────
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

    # ── Top risk drivers ──────────────────────────────────────────────────────
    st.subheader("Top Risk Drivers", divider="red")
    for risk_msg in report.top_risks:
        st.markdown(f"› {risk_msg}")

    # ── Component table ───────────────────────────────────────────────────────
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
        comp_lookup = _build_comp_lookup(report)

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
                "Score":         st.column_config.NumberColumn("Score", format="%.1f"),
                "Description":   st.column_config.TextColumn("Description", width="large"),
                "Criticality":   st.column_config.TextColumn("Criticality", width="small"),
                "Origin":        st.column_config.TextColumn("Country of Origin", width="small"),
                "Lead Time":     st.column_config.TextColumn("Lead Time (Days)", width="small"),
                "MOQ":           st.column_config.TextColumn("MOQ", width="small"),
                "Multi Source":  st.column_config.TextColumn("Multi Source Status", width="small"),
                "Unique":        st.column_config.TextColumn("Unique to Samsara", width="small"),
                "Sub Item #":    st.column_config.TextColumn("Sub Item #", width="medium"),
                "Sub Mfr":       st.column_config.TextColumn("Sub Manufacturer", width="medium"),
                "Sub MPN":       st.column_config.TextColumn("Sub MPN", width="medium"),
                "Sub Lifecycle": st.column_config.TextColumn("Sub Lifecycle ⚠", width="medium"),
                "Drivers":       st.column_config.TextColumn("Risk Drivers", width="large"),
            },
        )
        st.caption(f"{len(data)} components shown")

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
                    _show_component_detail(
                        comp, G, key_suffix,
                        lc_comp=_lc_lookup.get(comp.item_number),
                        corr_signals=composite_report.correlation_signals,
                    )

    with tab_all:    _show_table(df,                             "all")
    with tab_high:   _show_table(df[df.Risk == "HIGH"].copy(),   "high")
    with tab_medium: _show_table(df[df.Risk == "MEDIUM"].copy(), "medium")
    with tab_low:    _show_table(df[df.Risk == "LOW"].copy(),    "low")


# ── Lifecycle & Obsolescence tab ──────────────────────────────────────────────
with tab_lc:
    lc = lifecycle_report
    lc_total = lc.total_components

    # Metric cards
    lc_c1, lc_c2, lc_c3 = st.columns(3)
    lc_c4, lc_c5, lc_c6 = st.columns(3)
    lc_c1.metric("Total Components", lc_total)
    lc_c2.metric("Obsolete / EOL",   lc.obsolete_count,
                 help="SE lifecycle_stage = Obsolete or EOL")
    lc_c3.metric("LTB",              lc.ltb_count,
                 help="Last Time Buy — end of production ordered")
    lc_c4.metric("NRND",             lc.nrnd_count,
                 help="Not Recommended for New Designs")
    lc_c5.metric("Near EOL (< 2yr)", lc.near_eol_count,
                 help="Estimated years to EOL < 2")
    lc_c6.metric("Low Distributors", lc.low_distributor_count,
                 help="Fewer than 2 distributors available")

    # Lifecycle category drill-downs
    _LC_CATS = [
        ("Obsolete / EOL",    lc.obsolete_count,         lambda c: (c.lifecycle_stage or "").lower() in ("obsolete", "eol")),
        ("LTB",               lc.ltb_count,              lambda c: (c.lifecycle_stage or "").lower() == "ltb"),
        ("NRND",              lc.nrnd_count,             lambda c: (c.lifecycle_stage or "").lower() == "nrnd"),
        ("Near EOL (< 2yr)",  lc.near_eol_count,         lambda c: c.estimated_years_to_eol is not None and c.estimated_years_to_eol < 2),
        ("Low Distributors",  lc.low_distributor_count,  lambda c: c.number_of_distributors is not None and c.number_of_distributors < 2),
        ("High Counterfeit",  lc.high_counterfeit_count, lambda c: (c.counterfeit_risk or "").lower() == "high"),
    ]

    for _lbl, _cnt, _flt in _LC_CATS:
        if _cnt == 0:
            continue
        with st.expander(f"{_lbl} — {_cnt} component{'s' if _cnt != 1 else ''}"):
            _lc_rows = [
                {
                    "LC Level":      c.lifecycle_risk_level,
                    "LC Score":      c.lifecycle_risk_score,
                    "Item #":        c.item_number,
                    "Description":   (c.description or "")[:55],
                    "Manufacturer":  c.manufacturer or "—",
                    "MPN":           c.mpn or "—",
                    "Stage":         c.lifecycle_stage or "—",
                    "Yrs to EOL":    f"{c.estimated_years_to_eol:.1f}" if c.estimated_years_to_eol is not None else "—",
                    "Distributors":  str(c.number_of_distributors) if c.number_of_distributors is not None else "—",
                    "Counterfeit":   c.counterfeit_risk or "—",
                }
                for c in lc.component_risks if _flt(c)
            ]
            _lc_styled = (
                pd.DataFrame(_lc_rows).style
                .map(_colour_risk, subset=["LC Level"])
                .background_gradient(subset=["LC Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
                .format({"LC Score": "{:.1f}"})
            )
            st.dataframe(_lc_styled, hide_index=True, use_container_width=True)

    # Top lifecycle risk drivers
    st.subheader("Lifecycle Risk Drivers", divider="orange")
    for msg in lc.top_lifecycle_risks:
        st.markdown(f"› {msg}")

    # Full lifecycle component table
    st.subheader("All Components — Lifecycle View", divider="gray")
    lc_rows_all = [
        {
            "LC Level":      c.lifecycle_risk_level,
            "LC Score":      c.lifecycle_risk_score,
            "Item #":        c.item_number,
            "Description":   (c.description or "")[:55],
            "Manufacturer":  c.manufacturer or "—",
            "MPN":           c.mpn or "—",
            "Stage":         c.lifecycle_stage or "—",
            "EOL Date":      c.estimated_eol_date or "—",
            "Yrs to EOL":    f"{c.estimated_years_to_eol:.1f}" if c.estimated_years_to_eol is not None else "—",
            "Distributors":  str(c.number_of_distributors) if c.number_of_distributors is not None else "—",
            "Counterfeit":   c.counterfeit_risk or "—",
            "Drivers":       "; ".join(c.risk_drivers[:2]),
        }
        for c in lc.component_risks
    ]
    lc_df = pd.DataFrame(lc_rows_all)

    st.download_button(
        label="Export Lifecycle CSV",
        data=lc_df.to_csv(index=False).encode("utf-8"),
        file_name=f"lifecycle-risk-{lc.sku_id}.csv",
        mime="text/csv",
        key="csv_lifecycle",
    )

    lc_styled_all = (
        lc_df.style
        .map(_colour_risk, subset=["LC Level"])
        .background_gradient(subset=["LC Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
        .format({"LC Score": "{:.1f}"})
    )
    st.dataframe(lc_styled_all, hide_index=True, use_container_width=True)

    # ── Component Inspector (Lifecycle tab) ───────────────────────────────────
    st.subheader("Component Inspector", divider="gray")
    st.caption("Select a manufacturer and MPN to see the full combined risk report for that component.")

    lc_mfrs = sorted(m for m in set(c.manufacturer or "—" for c in lc.component_risks) if m != "—")
    lc_mfr_opts = ["— Select manufacturer —"] + lc_mfrs
    sel_lc_mfr = st.selectbox(
        "Manufacturer:", options=lc_mfr_opts,
        key="lc_insp_mfr", label_visibility="collapsed",
    )
    if sel_lc_mfr != lc_mfr_opts[0]:
        lc_mfr_comps = [c for c in lc.component_risks if c.manufacturer == sel_lc_mfr]
        lc_mpn_display = [f"{c.mpn or '—'}  ({c.item_number})" for c in lc_mfr_comps]
        lc_mpn_to_item = {f"{c.mpn or '—'}  ({c.item_number})": c.item_number for c in lc_mfr_comps}
        lc_mpn_opts = ["— Select MPN —"] + lc_mpn_display
        sel_lc_mpn = st.selectbox(
            "MPN:", options=lc_mpn_opts,
            key="lc_insp_mpn", label_visibility="collapsed",
        )
        if sel_lc_mpn != lc_mpn_opts[0]:
            insp_item_id = lc_mpn_to_item[sel_lc_mpn]
            struct_comp = _struct_lookup.get(insp_item_id)
            lc_comp_data = _lc_lookup.get(insp_item_id)
            if struct_comp:
                _show_component_detail(
                    struct_comp, G, "lc_insp",
                    lc_comp=lc_comp_data,
                    corr_signals=composite_report.correlation_signals,
                )
            elif lc_comp_data:
                st.info("Structural risk data not available for this component.", icon="ℹ️")
