"""
Risk Orchestrator — Phase 1

Aggregates the BOM Intelligence Agent (structural risk) and the Lifecycle &
Obsolescence Agent (lifecycle risk) into a composite risk score, and detects
compound risks where both dimensions intersect on the same component.

Phase 1 composite formula (2 of 3 agents active):
    Per spec: Total Risk = 0.45 × Structural + 0.35 × Lifecycle + 0.20 × Supply
    With Supply Agent not yet built, weights are normalised to sum to 1.0:
        composite = (0.45 / 0.80) × structural + (0.35 / 0.80) × lifecycle
                  = 0.5625 × structural + 0.4375 × lifecycle

    When the Supply Agent is added: revert to spec weights exactly.

Risk level thresholds: CRITICAL ≥ 80 | HIGH ≥ 55 | MEDIUM ≥ 30 | LOW < 30
"""
from __future__ import annotations

from models import (
    BOMData,
    CompositeRiskReport,
    LifecycleRiskReport,
    SKURiskReport,
)

_STRUCTURAL_WEIGHT = 0.5625   # 0.45 / 0.80
_LIFECYCLE_WEIGHT  = 0.4375   # 0.35 / 0.80

_ACTIVE_AGENTS = ["bom_intelligence", "lifecycle"]

_RISK_THRESHOLDS = [
    (80, "CRITICAL"),
    (55, "HIGH"),
    (30, "MEDIUM"),
    ( 0, "LOW"),
]


def _risk_level(score: float) -> str:
    for threshold, label in _RISK_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


def compute_composite_report(
    bom: BOMData,
    structural: SKURiskReport,
    lifecycle: LifecycleRiskReport,
) -> CompositeRiskReport:
    """
    Aggregate structural and lifecycle risk reports into a composite score.
    Cross-references component-level risks to detect compound signals.
    """
    composite_score = round(
        _STRUCTURAL_WEIGHT * structural.risk_score
        + _LIFECYCLE_WEIGHT * lifecycle.lifecycle_risk_score,
        2,
    )
    composite_level = _risk_level(composite_score)

    # Build lookup maps for cross-agent correlation
    struct_map = {c.item_number: c for c in structural.component_risks}
    lc_map     = {c.item_number: c for c in lifecycle.component_risks}

    _high_levels = {"HIGH", "CRITICAL"}
    correlation_signals: list[str] = []

    for item_id, lc_comp in lc_map.items():
        sc_comp = struct_map.get(item_id)
        if sc_comp is None:
            continue

        name = sc_comp.description or item_id
        lc_stage = (lc_comp.lifecycle_stage or "").strip().lower()
        yrs = lc_comp.estimated_years_to_eol
        dist = lc_comp.number_of_distributors

        # Obsolete + no substitute
        if lc_stage in ("obsolete", "eol") and sc_comp.substitute_risk.value == "HIGH":
            correlation_signals.append(
                f"Critical: '{name}' is Obsolete with no substitute"
            )
        # Near-EOL (< 2yr) + no substitute
        elif yrs is not None and yrs < 2 and sc_comp.substitute_risk.value == "HIGH":
            correlation_signals.append(
                f"Urgent: '{name}' EOL in {yrs:.1f} yr with no substitute"
            )
        # Both structural and lifecycle are HIGH/CRITICAL
        elif (
            sc_comp.substitute_risk.value == "HIGH"
            and lc_comp.lifecycle_risk_level in _high_levels
            and sc_comp.risk_score >= 55
        ):
            correlation_signals.append(
                f"Compound: '{name}' is single-source and approaching EOL "
                f"(structural {sc_comp.risk_score:.0f}, lifecycle {lc_comp.lifecycle_risk_score:.0f})"
            )

        # Single distributor + unique to Samsara
        if (
            dist is not None
            and dist < 2
            and sc_comp.unique_to_samsara is True
        ):
            correlation_signals.append(
                f"Severe: '{name}' has only {dist} distributor(s) and is unique to the portfolio"
            )

    # Merge top risks from both agents (structural first, then lifecycle)
    top_risks = list(structural.top_risks) + list(lifecycle.top_lifecycle_risks)

    return CompositeRiskReport(
        sku_id=bom.sku_id,
        description=bom.description,
        structural_risk_score=structural.risk_score,
        structural_risk_level=structural.risk_level,
        lifecycle_risk_score=lifecycle.lifecycle_risk_score,
        lifecycle_risk_level=lifecycle.lifecycle_risk_level,
        composite_risk_score=composite_score,
        composite_risk_level=composite_level,
        active_agents=_ACTIVE_AGENTS,
        correlation_signals=correlation_signals,
        top_risks=top_risks,
    )
