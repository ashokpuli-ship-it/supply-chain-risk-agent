from __future__ import annotations

import networkx as nx

from models import BOMData, ComponentRisk, SKURiskReport, SubstituteRisk
from substitute_analyzer import analyze_substitutes

# ── Scoring weights ───────────────────────────────────────────────────────────
# SKU-level score: weighted sum of per-ratio contributions (result is 0–100)
# Lifecycle phases that carry elevated risk (from Propel PLM data)
_AT_RISK_LIFECYCLE = {"EOL", "LTB", "NRND"}

_SKU_WEIGHTS = {
    "single_source":       75,   # Dominant factor: no substitute at all
    "same_mfr_substitute": 15,   # Substitute exists but same manufacturer
    "at_risk_lifecycle":   10,   # EOL / LTB / NRND components
}

# Component-level base scores by risk tier
_COMP_BASE = {
    SubstituteRisk.HIGH:   70,
    SubstituteRisk.MEDIUM: 40,
    SubstituteRisk.LOW:    10,
}

# Component-level modifier scores
_COMP_MODIFIERS = {
    "at_risk_lifecycle": 15,
}

# SKU risk level thresholds (score → label)
_RISK_THRESHOLDS = [
    (80, "CRITICAL"),
    (55, "HIGH"),
    (30, "MEDIUM"),
    ( 0, "LOW"),
]


def compute_risk_report(bom: BOMData, G: nx.DiGraph) -> SKURiskReport:
    """
    Run the full risk analysis pipeline for a BOM and return a SKURiskReport.

    Pipeline:
        1. Analyze substitutes for every primary component
        2. Score each component individually
        3. Aggregate into SKU-level score using weighted ratios
        4. Classify risk level and generate top-risk narratives
    """
    sub_map = analyze_substitutes(bom, G)

    component_risks: list[ComponentRisk] = []
    single_source_count = 0
    same_mfr_sub_count = 0
    at_risk_lifecycle_count = 0

    for comp in bom.primary_components:
        sub_risk, subs = sub_map.get(comp.item_number, (SubstituteRisk.HIGH, []))
        drivers: list[str] = []
        score = float(_COMP_BASE[sub_risk])

        # Substitute tier
        if sub_risk == SubstituteRisk.HIGH:
            drivers.append("No substitute — single source")
            single_source_count += 1
        elif sub_risk == SubstituteRisk.MEDIUM:
            drivers.append(f"Substitute exists but same manufacturer ({comp.manufacturer})")
            same_mfr_sub_count += 1
        else:
            drivers.append("Substitute available from different manufacturer")

        # Lifecycle modifier
        if comp.lifecycle_phase in _AT_RISK_LIFECYCLE:
            score += _COMP_MODIFIERS["at_risk_lifecycle"]
            drivers.append(f"Lifecycle: {comp.lifecycle_phase}")
            at_risk_lifecycle_count += 1

        component_risks.append(
            ComponentRisk(
                item_number=comp.item_number,
                description=comp.description,
                manufacturer=comp.manufacturer,
                mpn=comp.mpn,
                lifecycle_phase=comp.lifecycle_phase,
                criticality_type=comp.criticality_type,
                substitute_risk=sub_risk,
                substitutes=subs,
                risk_score=min(round(score, 1), 100.0),
                risk_drivers=drivers,
            )
        )

    # Sort highest risk first
    component_risks.sort(key=lambda c: c.risk_score, reverse=True)

    total = len(bom.primary_components)

    # SKU-level risk score (0–100) using weighted ratios
    sku_score = 0.0
    if total > 0:
        sku_score = round(
            (single_source_count / total) * _SKU_WEIGHTS["single_source"]
            + (same_mfr_sub_count / total) * _SKU_WEIGHTS["same_mfr_substitute"]
            + (at_risk_lifecycle_count / total) * _SKU_WEIGHTS["at_risk_lifecycle"],
            1,
        )

    risk_level = next(lvl for threshold, lvl in _RISK_THRESHOLDS if sku_score >= threshold)
    top_risks = _build_top_risks(component_risks, single_source_count, same_mfr_sub_count, at_risk_lifecycle_count, total)

    return SKURiskReport(
        sku_id=bom.sku_id,
        description=bom.description,
        total_components=total,
        single_source_count=single_source_count,
        components_with_substitutes=total - single_source_count,
        same_manufacturer_substitute_count=same_mfr_sub_count,
        at_risk_lifecycle_count=at_risk_lifecycle_count,
        risk_score=sku_score,
        risk_level=risk_level,
        component_risks=component_risks,
        top_risks=top_risks,
    )


def _build_top_risks(
    risks: list[ComponentRisk],
    single_source: int,
    same_mfr: int,
    at_risk_lifecycle: int,
    total: int,
) -> list[str]:
    messages: list[str] = []

    if total > 0:
        pct = round(single_source / total * 100)
        messages.append(f"{single_source}/{total} components are single source ({pct}% of BOM)")

    if same_mfr:
        messages.append(
            f"{same_mfr} components have substitutes from the same manufacturer — "
            "limited risk reduction"
        )

    if at_risk_lifecycle:
        messages.append(
            f"{at_risk_lifecycle} components have at-risk lifecycle (EOL / LTB / NRND)"
        )

    # Top 3 highest-risk individual components
    for comp in risks[:3]:
        short_desc = (comp.description or "")[:50]
        primary_driver = comp.risk_drivers[0] if comp.risk_drivers else ""
        messages.append(
            f"{comp.item_number} ({short_desc}): {primary_driver}"
        )

    return messages
