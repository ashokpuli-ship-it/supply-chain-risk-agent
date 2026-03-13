"""
Tests for the Lifecycle & Obsolescence Agent and Risk Orchestrator.

Constructs minimal BOMData fixtures directly (no Excel needed), mirroring
the approach used in test_risk_engine.py.
"""
from __future__ import annotations

import pytest

from bom_fetcher import _SE_FALLBACK
from bom_graph_builder import build_graph
from lifecycle_agent import compute_lifecycle_report
from models import (
    BOMComponent,
    BOMData,
    SiliconExpertData,
    SubstituteRisk,
)
from orchestrator import compute_composite_report
from risk_engine import compute_risk_report


# ── Helpers ────────────────────────────────────────────────────────────────────

def _se(
    stage: str = "ACTIVE",
    years_to_eol: float | None = None,
    distributors: int | None = None,
    counterfeit: str | None = None,
    last_pcn: str | None = None,
    eol_date: str | None = None,
) -> SiliconExpertData:
    return SiliconExpertData(
        lifecycle_stage=stage,
        estimated_years_to_eol=years_to_eol,
        estimated_eol_date=eol_date,
        number_of_distributors=distributors,
        counterfeit_overall_risk=counterfeit,
        last_pcn_date=last_pcn,
    )


def _primary(
    item: str,
    *,
    lifecycle_phase: str | None = "ACTIVE",
    criticality: str | None = None,
    mss: str = "Single",
    unique: bool = False,
    se: SiliconExpertData | None = None,
    manufacturer: str = "Mfr A",
    coo: str = "USA",
) -> BOMComponent:
    return BOMComponent(
        level=1,
        item_number=item,
        is_substitute=False,
        lifecycle_phase=lifecycle_phase,
        criticality_type=criticality,
        multiple_source_status=mss,
        unique_to_samsara=unique,
        manufacturer=manufacturer,
        country_of_origin=coo,
        se_data=se,
    )


def _sub(item: str, sub_for: str, manufacturer: str = "Mfr B", coo: str = "Japan") -> BOMComponent:
    return BOMComponent(
        level=1,
        item_number=item,
        is_substitute=True,
        substitute_for=sub_for,
        manufacturer=manufacturer,
        country_of_origin=coo,
        se_data=_se(),
    )


def _bom(*components: BOMComponent) -> BOMData:
    return BOMData(sku_id="TEST-SKU", description="Test SKU", components=list(components))


# ── Component-level lifecycle scoring ─────────────────────────────────────────

class TestComponentLifecycleScoring:

    def test_active_no_modifiers_scores_zero(self):
        """ACTIVE stage with healthy SE data → 0 (LOW)."""
        bom = _bom(_primary("A", se=_se("ACTIVE", years_to_eol=8.0, distributors=15)))
        r = compute_lifecycle_report(bom)
        c = r.component_risks[0]
        assert c.lifecycle_risk_score == 0.0
        assert c.lifecycle_risk_level == "LOW"

    def test_obsolete_base_score_80(self):
        """Obsolete stage with no proximity/distributor modifiers → base score 80 (CRITICAL)."""
        # years_to_eol=None avoids the EOL proximity modifier; tests pure stage base score
        bom = _bom(_primary("A", lifecycle_phase="EOL", se=_se("Obsolete", years_to_eol=None, distributors=5)))
        r = compute_lifecycle_report(bom)
        c = r.component_risks[0]
        assert c.lifecycle_risk_score == 80.0
        assert c.lifecycle_risk_level == "CRITICAL"

    def test_ltb_base_score_65(self):
        """LTB stage with no modifiers → base score 65 (HIGH)."""
        bom = _bom(_primary("A", lifecycle_phase="LTB", se=_se("LTB", years_to_eol=5.0, distributors=10)))
        r = compute_lifecycle_report(bom)
        c = r.component_risks[0]
        assert c.lifecycle_risk_score == 65.0
        assert c.lifecycle_risk_level == "HIGH"

    def test_nrnd_base_score_50(self):
        """NRND stage with no modifiers → base score 50 (MEDIUM/HIGH)."""
        bom = _bom(_primary("A", lifecycle_phase="NRND", se=_se("NRND", years_to_eol=5.0, distributors=10)))
        r = compute_lifecycle_report(bom)
        c = r.component_risks[0]
        assert c.lifecycle_risk_score == 50.0
        assert c.lifecycle_risk_level == "MEDIUM"

    def test_years_to_eol_lt1_adds_20(self):
        """LTB + years_to_eol < 1 → 65 + 20 = 85."""
        bom = _bom(_primary("A", se=_se("LTB", years_to_eol=0.8, distributors=10)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 85.0

    def test_years_to_eol_1_to_2_adds_15(self):
        """LTB + years_to_eol in [1, 2) → 65 + 15 = 80."""
        bom = _bom(_primary("A", se=_se("LTB", years_to_eol=1.5, distributors=10)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 80.0

    def test_years_to_eol_2_to_3_adds_10(self):
        """NRND + years_to_eol in [2, 3) → 50 + 10 = 60."""
        bom = _bom(_primary("A", se=_se("NRND", years_to_eol=2.4, distributors=10)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 60.0

    def test_years_to_eol_3_to_5_adds_5(self):
        """NRND + years_to_eol in [3, 5) → 50 + 5 = 55."""
        bom = _bom(_primary("A", se=_se("NRND", years_to_eol=3.1, distributors=10)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 55.0

    def test_low_distributor_adds_15(self):
        """ACTIVE + only 1 distributor → 0 + 15 = 15."""
        bom = _bom(_primary("A", se=_se("ACTIVE", years_to_eol=8.0, distributors=1)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 15.0

    def test_high_counterfeit_adds_10(self):
        """NRND + high counterfeit → 50 + 10 = 60."""
        bom = _bom(_primary("A", se=_se("NRND", years_to_eol=5.0, distributors=10, counterfeit="High")))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 60.0

    def test_score_clamped_at_100(self):
        """Obsolete + <1yr + 1 dist + high counterfeit = 80+20+15+10 = 125 → clamped to 100."""
        bom = _bom(_primary("A", se=_se(
            "Obsolete", years_to_eol=0.0, distributors=1, counterfeit="High"
        )))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 100.0

    def test_recent_pcn_adds_5(self):
        """NRND + PCN within last 6 months → 50 + 5 = 55 (at minimum, without year proximity)."""
        from datetime import date, timedelta
        recent = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        bom = _bom(_primary("A", se=_se("NRND", years_to_eol=5.0, distributors=10, last_pcn=recent)))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 55.0

    def test_old_pcn_does_not_add(self):
        """PCN older than 6 months → no modifier."""
        bom = _bom(_primary("A", se=_se("NRND", years_to_eol=5.0, distributors=10, last_pcn="2020-01-01")))
        r = compute_lifecycle_report(bom)
        assert r.component_risks[0].lifecycle_risk_score == 50.0


# ── SKU-level lifecycle scoring ────────────────────────────────────────────────

class TestSKULifecycleScoring:

    def test_all_active_score_zero(self):
        """All ACTIVE components → SKU lifecycle score = 0, level = LOW."""
        comps = [_primary(f"A{i}", se=_se("ACTIVE", years_to_eol=8.0, distributors=10)) for i in range(4)]
        bom = _bom(*comps)
        r = compute_lifecycle_report(bom)
        assert r.lifecycle_risk_score == 0.0
        assert r.lifecycle_risk_level == "LOW"
        assert r.obsolete_count == 0

    def test_all_obsolete_score(self):
        """All Obsolete (no years_to_eol) → SKU score = (4/4)×40 = 40."""
        # years_to_eol=None so near_eol_count stays 0
        comps = [_primary(f"A{i}", lifecycle_phase="EOL", se=_se("Obsolete", years_to_eol=None, distributors=5)) for i in range(4)]
        bom = _bom(*comps)
        r = compute_lifecycle_report(bom)
        assert r.lifecycle_risk_score == 40.0
        assert r.obsolete_count == 4
        assert r.near_eol_count == 0

    def test_counts_correct(self):
        """Mixed BOM — verify every counter is incremented correctly."""
        comps = [
            _primary("obs", lifecycle_phase="EOL", se=_se("Obsolete", years_to_eol=0.0, distributors=5)),
            _primary("ltb", lifecycle_phase="LTB", se=_se("LTB", years_to_eol=0.5, distributors=3)),
            _primary("nrnd", lifecycle_phase="NRND", se=_se("NRND", years_to_eol=2.0, distributors=8)),
            _primary("act", se=_se("ACTIVE", years_to_eol=7.0, distributors=12)),
        ]
        bom = _bom(*comps)
        r = compute_lifecycle_report(bom)
        assert r.total_components == 4
        assert r.obsolete_count == 1
        assert r.ltb_count == 1
        assert r.nrnd_count == 1
        # near_eol = years < 2: obs (0.0) + ltb (0.5) = 2
        assert r.near_eol_count == 2

    def test_near_eol_threshold(self):
        """near_eol counts components with years_to_eol < 2 regardless of stage."""
        comps = [
            _primary("A", se=_se("ACTIVE", years_to_eol=1.8, distributors=10)),  # < 2 → counted
            _primary("B", se=_se("ACTIVE", years_to_eol=2.0, distributors=10)),  # = 2 → NOT counted
            _primary("C", se=_se("ACTIVE", years_to_eol=2.1, distributors=10)),  # > 2 → NOT counted
        ]
        bom = _bom(*comps)
        r = compute_lifecycle_report(bom)
        assert r.near_eol_count == 1

    def test_low_distributor_count(self):
        """Components with < 2 distributors are counted in low_distributor_count."""
        comps = [
            _primary("A", se=_se("ACTIVE", years_to_eol=8.0, distributors=1)),   # counted
            _primary("B", se=_se("ACTIVE", years_to_eol=8.0, distributors=2)),   # NOT counted (= 2)
            _primary("C", se=_se("ACTIVE", years_to_eol=8.0, distributors=10)),  # NOT counted
        ]
        bom = _bom(*comps)
        r = compute_lifecycle_report(bom)
        assert r.low_distributor_count == 1

    def test_risk_level_thresholds(self):
        """Verify CRITICAL ≥ 80, HIGH ≥ 55, MEDIUM ≥ 30, LOW < 30 for lifecycle level."""
        from lifecycle_agent import _risk_level
        assert _risk_level(80.0) == "CRITICAL"
        assert _risk_level(79.9) == "HIGH"
        assert _risk_level(55.0) == "HIGH"
        assert _risk_level(54.9) == "MEDIUM"
        assert _risk_level(30.0) == "MEDIUM"
        assert _risk_level(29.9) == "LOW"
        assert _risk_level(0.0) == "LOW"


# ── SE fallback derivation ─────────────────────────────────────────────────────

class TestSEFallback:

    def test_fallback_active(self):
        """ACTIVE lifecycle_phase → SE fallback stage = ACTIVE, years = 7.0."""
        defaults = _SE_FALLBACK["ACTIVE"]
        assert defaults["lifecycle_stage"] == "ACTIVE"
        assert defaults["estimated_years_to_eol"] == 7.0
        assert defaults["number_of_distributors"] == 10

    def test_fallback_eol(self):
        """EOL lifecycle_phase → SE fallback stage = Obsolete, years = 0.0, 1 distributor."""
        defaults = _SE_FALLBACK["EOL"]
        assert defaults["lifecycle_stage"] == "Obsolete"
        assert defaults["estimated_years_to_eol"] == 0.0
        assert defaults["number_of_distributors"] == 1

    def test_fallback_ltb(self):
        """LTB lifecycle_phase → SE fallback years = 1.0."""
        assert _SE_FALLBACK["LTB"]["estimated_years_to_eol"] == 1.0

    def test_fallback_nrnd(self):
        """NRND lifecycle_phase → SE fallback years = 3.0."""
        assert _SE_FALLBACK["NRND"]["estimated_years_to_eol"] == 3.0


# ── Orchestrator correlation signals ──────────────────────────────────────────

class TestOrchestratorCorrelation:

    def _run(self, primary_comp: BOMComponent, substitute: BOMComponent | None = None):
        comps = [primary_comp]
        if substitute:
            comps.append(substitute)
        bom = _bom(*comps)
        G = build_graph(bom)
        structural = compute_risk_report(bom, G)
        lifecycle = compute_lifecycle_report(bom)
        return compute_composite_report(bom, structural, lifecycle)

    def test_obsolete_no_substitute_fires_critical_signal(self):
        """Obsolete + single source → 'Critical: obsolete with no substitute'."""
        comp = _primary("A", lifecycle_phase="EOL", mss="Single",
                        se=_se("Obsolete", years_to_eol=0.0, distributors=2))
        r = self._run(comp)
        signals_lower = [s.lower() for s in r.correlation_signals]
        assert any("obsolete" in s and "no substitute" in s for s in signals_lower)

    def test_near_eol_no_substitute_fires_urgent_signal(self):
        """years_to_eol < 2 + single source → 'Urgent: EOL in X yr with no substitute'."""
        comp = _primary("A", lifecycle_phase="LTB", mss="Single",
                        se=_se("LTB", years_to_eol=0.8, distributors=3))
        r = self._run(comp)
        signals_lower = [s.lower() for s in r.correlation_signals]
        assert any("urgent" in s for s in signals_lower)

    def test_strong_sub_no_correlation_signal(self):
        """Strong substitute (diff mfr + diff region) → no compound signal."""
        primary = _primary("A", lifecycle_phase="LTB", mss="Multi",
                           manufacturer="Mfr X", coo="USA",
                           se=_se("LTB", years_to_eol=0.8, distributors=3))
        sub = _sub("B", "A", manufacturer="Mfr Y", coo="Germany")
        r = self._run(primary, sub)
        assert all("urgent" not in s.lower() and "critical" not in s.lower()
                   for s in r.correlation_signals)

    def test_composite_score_formula(self):
        """Composite = 0.5625 × structural + 0.4375 × lifecycle (Phase 1 weights)."""
        comp = _primary("A", se=_se("ACTIVE", years_to_eol=8.0, distributors=10))
        bom = _bom(comp)
        G = build_graph(bom)
        structural = compute_risk_report(bom, G)
        lifecycle = compute_lifecycle_report(bom)
        composite = compute_composite_report(bom, structural, lifecycle)

        expected = round(
            0.5625 * structural.risk_score + 0.4375 * lifecycle.lifecycle_risk_score, 2
        )
        assert composite.composite_risk_score == expected

    def test_active_agents_list(self):
        """active_agents always contains both Phase 1 agents."""
        comp = _primary("A", se=_se())
        bom = _bom(comp)
        G = build_graph(bom)
        r = compute_composite_report(bom, compute_risk_report(bom, G), compute_lifecycle_report(bom))
        assert "bom_intelligence" in r.active_agents
        assert "lifecycle" in r.active_agents

    def test_top_risks_merges_both_agents(self):
        """top_risks contains narratives from both structural and lifecycle agents."""
        comp = _primary("A", lifecycle_phase="EOL", mss="Single",
                        se=_se("Obsolete", years_to_eol=0.0, distributors=1, counterfeit="High"))
        bom = _bom(comp)
        G = build_graph(bom)
        structural = compute_risk_report(bom, G)
        lifecycle = compute_lifecycle_report(bom)
        composite = compute_composite_report(bom, structural, lifecycle)
        # structural produces at least one top risk (single source)
        assert len(structural.top_risks) > 0
        # lifecycle produces at least one top risk (obsolete)
        assert len(lifecycle.top_lifecycle_risks) > 0
        # composite merges both
        assert len(composite.top_risks) == len(structural.top_risks) + len(lifecycle.top_lifecycle_risks)
