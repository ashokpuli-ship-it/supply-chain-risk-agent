"""
Lifecycle & Obsolescence Agent — Phase 1

Scores each component's lifecycle risk using SiliconExpert fields (populated by
bom_fetcher from the Propel Excel export). For exports without SE columns, the
fetcher derives conservative defaults from lifecycle_phase, so this agent always
receives fully populated SiliconExpertData.

Component lifecycle score (0–100):
  Base score by stage:
    Obsolete / EOL → 80
    LTB            → 65
    NRND           → 50
    ACTIVE         →  0

  Additive modifiers:
    years_to_eol < 1         → +20
    1 ≤ years_to_eol < 2     → +15
    2 ≤ years_to_eol < 3     → +10
    3 ≤ years_to_eol < 5     → +5
    distributors < 2         → +15
    counterfeit_risk = High  → +10
    PCN in last 6 months     → +5
    (score capped at 100)

SKU lifecycle score:
  (obsolete / total)  × 40
  (nrnd / total)      × 25
  (ltb / total)       × 20
  (near_eol / total)  × 10   where near_eol = years_to_eol < 2
  (low_dist / total)  × 5    where low_dist = distributors < 2

Risk level thresholds: CRITICAL ≥ 80 | HIGH ≥ 55 | MEDIUM ≥ 30 | LOW < 30
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from models import (
    BOMComponent,
    BOMData,
    LifecycleComponentRisk,
    LifecycleRiskReport,
    SiliconExpertData,
)

# Lifecycle stages recognised as at-risk (using SE naming)
_OBSOLETE_STAGES = {"Obsolete", "EOL"}
_LTB_STAGES = {"LTB"}
_NRND_STAGES = {"NRND"}

# Base score by SE lifecycle stage (case-insensitive lookup via normalisation below)
_STAGE_BASE: dict[str, float] = {
    "obsolete": 80.0,
    "eol":      80.0,
    "ltb":      65.0,
    "nrnd":     50.0,
    "active":    0.0,
}

_RISK_THRESHOLDS = [
    (80, "CRITICAL"),
    (55, "HIGH"),
    (30, "MEDIUM"),
    ( 0, "LOW"),
]

_PCN_RECENCY_MONTHS = 6


def _risk_level(score: float) -> str:
    for threshold, label in _RISK_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


def _months_since(date_str: Optional[str]) -> Optional[float]:
    """Return number of months since date_str (YYYY-MM-DD). None if unparseable."""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        today = date.today()
        return (today.year - d.year) * 12 + (today.month - d.month)
    except (ValueError, AttributeError):
        return None


def _score_component(
    comp: BOMComponent,
    se: SiliconExpertData,
) -> tuple[float, list[str]]:
    """Return (component_lifecycle_score, risk_drivers) for a primary component."""
    drivers: list[str] = []
    stage_raw = (se.lifecycle_stage or "ACTIVE").strip()
    stage_key = stage_raw.lower()

    # Base score
    score = _STAGE_BASE.get(stage_key, 0.0)
    if score > 0:
        drivers.append(f"Lifecycle stage: {stage_raw}")

    # EOL proximity modifier
    yrs = se.estimated_years_to_eol
    if yrs is not None:
        if yrs < 1:
            score += 20
            drivers.append(f"EOL in < 1 year ({yrs:.1f} yr)")
        elif yrs < 2:
            score += 15
            drivers.append(f"EOL in < 2 years ({yrs:.1f} yr)")
        elif yrs < 3:
            score += 10
            drivers.append(f"EOL in < 3 years ({yrs:.1f} yr)")
        elif yrs < 5:
            score += 5
            drivers.append(f"EOL in < 5 years ({yrs:.1f} yr)")

    # Low distributor availability
    dist = se.number_of_distributors
    if dist is not None and dist < 2:
        score += 15
        drivers.append(f"Only {dist} distributor{'s' if dist != 1 else ''} available")

    # High counterfeit risk
    if (se.counterfeit_overall_risk or "").strip().lower() == "high":
        score += 10
        drivers.append("High counterfeit risk")

    # Recent PCN (within last N months)
    months_ago = _months_since(se.last_pcn_date)
    if months_ago is not None and 0 <= months_ago <= _PCN_RECENCY_MONTHS:
        score += 5
        drivers.append(f"Recent PCN ({se.last_pcn_date})")

    score = min(score, 100.0)
    return score, drivers


def compute_lifecycle_report(bom: BOMData) -> LifecycleRiskReport:
    """
    Compute lifecycle risk for every primary component in the BOM.
    SE fields are read directly from each BOMComponent.se_data (populated by bom_fetcher).
    """
    primary = bom.primary_components
    total = len(primary)

    if total == 0:
        return LifecycleRiskReport(
            sku_id=bom.sku_id,
            description=bom.description,
            total_components=0,
            obsolete_count=0,
            nrnd_count=0,
            ltb_count=0,
            near_eol_count=0,
            low_distributor_count=0,
            high_counterfeit_count=0,
            lifecycle_risk_score=0.0,
            lifecycle_risk_level="LOW",
            component_risks=[],
            top_lifecycle_risks=[],
        )

    obsolete_count = 0
    nrnd_count = 0
    ltb_count = 0
    near_eol_count = 0
    low_dist_count = 0
    high_counterfeit_count = 0
    comp_risks: list[LifecycleComponentRisk] = []

    for comp in primary:
        se = comp.se_data or SiliconExpertData()
        score, drivers = _score_component(comp, se)

        stage = (se.lifecycle_stage or "ACTIVE").strip()
        stage_lower = stage.lower()

        if stage_lower in ("obsolete", "eol"):
            obsolete_count += 1
        elif stage_lower == "nrnd":
            nrnd_count += 1
        elif stage_lower == "ltb":
            ltb_count += 1

        yrs = se.estimated_years_to_eol
        if yrs is not None and yrs < 2:
            near_eol_count += 1

        dist = se.number_of_distributors
        if dist is not None and dist < 2:
            low_dist_count += 1

        if (se.counterfeit_overall_risk or "").strip().lower() == "high":
            high_counterfeit_count += 1

        comp_risks.append(
            LifecycleComponentRisk(
                item_number=comp.item_number,
                description=comp.description,
                manufacturer=comp.manufacturer,
                mpn=comp.mpn,
                lifecycle_stage=stage,
                estimated_years_to_eol=yrs,
                estimated_eol_date=se.estimated_eol_date,
                number_of_distributors=dist,
                counterfeit_risk=se.counterfeit_overall_risk,
                lifecycle_risk_score=score,
                lifecycle_risk_level=_risk_level(score),
                risk_drivers=drivers,
            )
        )

    # Sort highest lifecycle risk first
    comp_risks.sort(key=lambda c: c.lifecycle_risk_score, reverse=True)

    # SKU-level weighted score
    sku_score = (
        (obsolete_count / total) * 40
        + (nrnd_count / total) * 25
        + (ltb_count / total) * 20
        + (near_eol_count / total) * 10
        + (low_dist_count / total) * 5
    )
    sku_score = min(sku_score, 100.0)

    # Build narrative top risks
    top: list[str] = []
    if obsolete_count:
        top.append(f"{obsolete_count}/{total} component{'s' if obsolete_count != 1 else ''} are Obsolete/EOL")
    if ltb_count:
        top.append(f"{ltb_count}/{total} component{'s' if ltb_count != 1 else ''} are Last Time Buy (LTB)")
    if nrnd_count:
        top.append(f"{nrnd_count}/{total} component{'s' if nrnd_count != 1 else ''} are NRND")
    if near_eol_count:
        top.append(f"{near_eol_count}/{total} component{'s' if near_eol_count != 1 else ''} reach EOL within 2 years")
    if low_dist_count:
        top.append(f"{low_dist_count}/{total} component{'s' if low_dist_count != 1 else ''} have fewer than 2 distributors")
    if high_counterfeit_count:
        top.append(f"{high_counterfeit_count}/{total} component{'s' if high_counterfeit_count != 1 else ''} carry high counterfeit risk")

    return LifecycleRiskReport(
        sku_id=bom.sku_id,
        description=bom.description,
        total_components=total,
        obsolete_count=obsolete_count,
        nrnd_count=nrnd_count,
        ltb_count=ltb_count,
        near_eol_count=near_eol_count,
        low_distributor_count=low_dist_count,
        high_counterfeit_count=high_counterfeit_count,
        lifecycle_risk_score=round(sku_score, 2),
        lifecycle_risk_level=_risk_level(sku_score),
        component_risks=comp_risks,
        top_lifecycle_risks=top,
    )
