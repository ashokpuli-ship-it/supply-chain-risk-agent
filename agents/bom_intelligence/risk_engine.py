from __future__ import annotations

import networkx as nx

from models import BOMData, ComponentRisk, SKURiskReport, SubstituteRisk
from substitute_analyzer import analyze_substitutes

# ── Scoring constants ──────────────────────────────────────────────────────────

# Lifecycle phases that carry elevated risk (from Propel PLM data)
_AT_RISK_LIFECYCLE = {"EOL", "LTB", "NRND"}

# Criticality types that amplify component risk severity
_CRITICAL_TYPES = {"Field", "Safety", "Field & Safety"}

# SKU-level score: weighted sum of per-ratio contributions (result is 0–100)
_SKU_WEIGHTS = {
    "single_source":       60,   # Dominant factor: no substitute at all
    "weak_substitute":     15,   # Substitute exists but same manufacturer or region
    "at_risk_lifecycle":   10,   # EOL / LTB / NRND components
    "criticality":         10,   # Field / Safety / Field & Safety components
    "unique_to_samsara":    5,   # No ecosystem alternatives
}

# Component-level base scores by substitute risk tier
_COMP_BASE = {
    SubstituteRisk.HIGH:   70,
    SubstituteRisk.MEDIUM: 40,
    SubstituteRisk.LOW:    10,
}

# Component-level additive modifiers
_COMP_MODIFIERS = {
    "at_risk_lifecycle":  15,
    "criticality":        15,
    "unique_to_samsara":  10,
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
    single_source_count      = 0
    weak_substitute_count    = 0
    at_risk_lifecycle_count  = 0
    critical_parts_count     = 0
    unique_to_samsara_count  = 0

    for comp in bom.primary_components:
        sub_risk, subs = sub_map.get(comp.item_number, (SubstituteRisk.HIGH, []))
        drivers: list[str] = []
        score = float(_COMP_BASE[sub_risk])

        # ── Substitute tier ────────────────────────────────────────────────────
        if sub_risk == SubstituteRisk.HIGH:
            mss = (comp.multiple_source_status or "").strip().lower()
            if mss == "multi":
                drivers.append(
                    "No BOM substitute listed (Multiple Source Status: Multi — verify with sourcing)"
                )
            elif mss == "single":
                drivers.append("No substitute — confirmed single source (Multiple Source Status: Single)")
            else:
                drivers.append("No substitute — single source")
            single_source_count += 1

        elif sub_risk == SubstituteRisk.MEDIUM:
            drivers.append("Weak substitute — same manufacturer or same region")
            weak_substitute_count += 1

        else:
            drivers.append("Substitute available — different manufacturer and region")

        # ── Lifecycle modifier ─────────────────────────────────────────────────
        if comp.lifecycle_phase in _AT_RISK_LIFECYCLE:
            score += _COMP_MODIFIERS["at_risk_lifecycle"]
            drivers.append(f"Lifecycle: {comp.lifecycle_phase}")
            at_risk_lifecycle_count += 1

        # ── Criticality amplification ──────────────────────────────────────────
        if comp.criticality_type in _CRITICAL_TYPES:
            score += _COMP_MODIFIERS["criticality"]
            drivers.append(f"Criticality: {comp.criticality_type}")
            critical_parts_count += 1

        # ── Samsara-unique parts ───────────────────────────────────────────────
        if comp.unique_to_samsara:
            score += _COMP_MODIFIERS["unique_to_samsara"]
            drivers.append("Unique to Samsara — limited ecosystem alternatives")
            unique_to_samsara_count += 1

        # ── Substitute lifecycle health (informational — no score impact) ──────
        at_risk_subs = [
            s for s in subs if s.lifecycle_phase in _AT_RISK_LIFECYCLE
        ]
        if at_risk_subs:
            sub_detail = "; ".join(
                f"{s.item_number} ({s.lifecycle_phase})" for s in at_risk_subs
            )
            drivers.append(f"Substitute(s) at-risk lifecycle: {sub_detail}")

        component_risks.append(
            ComponentRisk(
                item_number=comp.item_number,
                description=comp.description,
                manufacturer=comp.manufacturer,
                mpn=comp.mpn,
                lifecycle_phase=comp.lifecycle_phase,
                criticality_type=comp.criticality_type,
                country_of_origin=comp.country_of_origin,
                lead_time_days=comp.lead_time_days,
                moq=comp.moq,
                multiple_source_status=comp.multiple_source_status,
                unique_to_samsara=comp.unique_to_samsara,
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
            (single_source_count     / total) * _SKU_WEIGHTS["single_source"]
            + (weak_substitute_count / total) * _SKU_WEIGHTS["weak_substitute"]
            + (at_risk_lifecycle_count / total) * _SKU_WEIGHTS["at_risk_lifecycle"]
            + (critical_parts_count  / total) * _SKU_WEIGHTS["criticality"]
            + (unique_to_samsara_count / total) * _SKU_WEIGHTS["unique_to_samsara"],
            1,
        )

    risk_level = next(lvl for threshold, lvl in _RISK_THRESHOLDS if sku_score >= threshold)
    top_risks = _build_top_risks(
        single_source_count, weak_substitute_count, at_risk_lifecycle_count,
        critical_parts_count, unique_to_samsara_count, total,
    )

    return SKURiskReport(
        sku_id=bom.sku_id,
        description=bom.description,
        total_components=total,
        single_source_count=single_source_count,
        components_with_substitutes=total - single_source_count,
        weak_substitute_count=weak_substitute_count,
        at_risk_lifecycle_count=at_risk_lifecycle_count,
        critical_parts_count=critical_parts_count,
        unique_to_samsara_count=unique_to_samsara_count,
        risk_score=sku_score,
        risk_level=risk_level,
        component_risks=component_risks,
        top_risks=top_risks,
    )


def _build_top_risks(
    single_source: int,
    weak_substitute: int,
    at_risk_lifecycle: int,
    critical_parts: int,
    unique_to_samsara: int,
    total: int,
) -> list[str]:
    messages: list[str] = []

    if total > 0:
        pct = round(single_source / total * 100)
        messages.append(f"{single_source}/{total} components are single source ({pct}% of BOM)")

    if weak_substitute:
        messages.append(
            f"{weak_substitute} components have weak substitutes "
            "(same manufacturer or region — limited risk reduction)"
        )

    if at_risk_lifecycle:
        messages.append(
            f"{at_risk_lifecycle} components have at-risk lifecycle (EOL / LTB / NRND)"
        )

    if critical_parts:
        messages.append(
            f"{critical_parts} components are safety or field-critical "
            "(Field / Safety / Field & Safety)"
        )

    if unique_to_samsara:
        messages.append(
            f"{unique_to_samsara} components are unique to Samsara — "
            "no ecosystem alternatives if discontinued"
        )

    return messages
