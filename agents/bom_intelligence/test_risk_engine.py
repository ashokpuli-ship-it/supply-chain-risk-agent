"""
Tests for the BOM Intelligence Agent risk scoring engine.

Scenarios are derived from the extended sample BOM spec in CLAUDE.md.
Each test constructs a minimal BOM with the relevant attributes and
verifies the resulting component-level and SKU-level scores.
"""
from __future__ import annotations

import pytest

from bom_graph_builder import build_graph
from models import BOMComponent, BOMData
from risk_engine import compute_risk_report


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_bom(
    sku_id: str,
    primaries: list[BOMComponent],
    substitutes: list[BOMComponent] | None = None,
) -> BOMData:
    """Build a minimal BOMData from primary + substitute component lists."""
    components = list(primaries)
    if substitutes:
        components.extend(substitutes)
    return BOMData(sku_id=sku_id, description=f"Test SKU {sku_id}", components=components)


def _primary(
    item: str,
    manufacturer: str = "MFR-A",
    country: str | None = "USA",
    lifecycle: str = "ACTIVE",
    criticality: str | None = None,
    unique: bool | None = None,
    mss: str | None = None,
) -> BOMComponent:
    return BOMComponent(
        level=1,
        item_number=item,
        manufacturer=manufacturer,
        country_of_origin=country,
        lifecycle_phase=lifecycle,
        criticality_type=criticality,
        unique_to_samsara=unique,
        multiple_source_status=mss,
    )


def _substitute(
    item: str,
    substitute_for: str,
    manufacturer: str = "MFR-B",
    country: str | None = "Japan",
    lifecycle: str = "ACTIVE",
) -> BOMComponent:
    return BOMComponent(
        level=1,
        item_number=item,
        substitute_for=substitute_for,
        is_substitute=True,
        manufacturer=manufacturer,
        country_of_origin=country,
        lifecycle_phase=lifecycle,
    )


def _score_single_component(
    primary: BOMComponent,
    substitutes: list[BOMComponent] | None = None,
) -> float:
    """Score a single-component BOM and return the component's risk score."""
    bom = _make_bom("SKU-TEST", [primary], substitutes)
    G = build_graph(bom)
    report = compute_risk_report(bom, G)
    assert len(report.component_risks) == 1
    return report.component_risks[0].risk_score


# ── Component-level scoring tests ─────────────────────────────────────────────

class TestComponentScoring:
    """Validate component-level risk scores against the CLAUDE.md spec table."""

    def test_single_source_no_modifiers(self):
        """Single source, no criticality/lifecycle/unique modifiers → base 70."""
        score = _score_single_component(_primary("ITEM-1"))
        assert score == 70.0

    def test_single_source_safety_unique(self):
        """Single source + Safety + Unique to Samsara → 70 + 15 + 10 = 95."""
        score = _score_single_component(
            _primary("ITEM-1", criticality="Safety", unique=True)
        )
        assert score == 95.0

    def test_single_source_field_and_safety_unique(self):
        """Single source + Field & Safety + Unique → 70 + 15 + 10 = 95."""
        score = _score_single_component(
            _primary("ITEM-1", criticality="Field & Safety", unique=True)
        )
        assert score == 95.0

    def test_single_source_field_nrnd(self):
        """Single source + Field + NRND lifecycle → 70 + 15 + 15 = 100 (clamped)."""
        score = _score_single_component(
            _primary("ITEM-1", criticality="Field", lifecycle="NRND")
        )
        assert score == 100.0

    def test_single_source_field_eol(self):
        """Single source + Field + EOL lifecycle → 70 + 15 + 15 = 100 (clamped)."""
        score = _score_single_component(
            _primary("ITEM-1", criticality="Field", lifecycle="EOL")
        )
        assert score == 100.0

    def test_weak_sub_same_region(self):
        """Substitute exists, same region (both Korea) → MEDIUM base 40."""
        p = _primary("ITEM-1", manufacturer="Samsung", country="Korea")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="SK Hynix", country="Korea")
        score = _score_single_component(p, [s])
        assert score == 40.0

    def test_weak_sub_same_region_plus_field(self):
        """Weak sub (same region) + Field criticality → 40 + 15 = 55."""
        p = _primary("ITEM-1", manufacturer="Samsung", country="Korea", criticality="Field")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="SK Hynix", country="Korea")
        score = _score_single_component(p, [s])
        assert score == 55.0

    def test_weak_sub_same_manufacturer(self):
        """Substitute exists, same manufacturer (TI → TI) → MEDIUM base 40."""
        p = _primary("ITEM-1", manufacturer="TI", country="USA")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="TI", country="Japan")
        score = _score_single_component(p, [s])
        assert score == 40.0

    def test_strong_sub_diff_mfr_and_region(self):
        """Strong substitute (diff manufacturer + diff region) → LOW base 10."""
        p = _primary("ITEM-1", manufacturer="Bosch", country="Germany")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="TDK", country="Japan")
        score = _score_single_component(p, [s])
        assert score == 10.0

    def test_strong_sub_plus_safety(self):
        """Strong sub + Safety criticality → 10 + 15 = 25."""
        p = _primary("ITEM-1", manufacturer="Bosch", country="Germany", criticality="Safety")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="TDK", country="Japan")
        score = _score_single_component(p, [s])
        assert score == 25.0

    def test_all_subs_eol_is_medium(self):
        """All substitutes at EOL → effectively no coverage → MEDIUM base 40."""
        p = _primary("ITEM-1", manufacturer="MFR-A", country="USA")
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="MFR-B", country="Japan", lifecycle="EOL")
        score = _score_single_component(p, [s])
        assert score == 40.0

    def test_lifecycle_ltb_modifier(self):
        """Primary at LTB lifecycle → +15 modifier on top of base."""
        score = _score_single_component(
            _primary("ITEM-1", lifecycle="LTB")
        )
        # Single source (70) + LTB lifecycle (+15) = 85
        assert score == 85.0

    def test_unique_to_samsara_modifier(self):
        """Unique to Samsara → +10 modifier."""
        score = _score_single_component(
            _primary("ITEM-1", unique=True)
        )
        # Single source (70) + unique (+10) = 80
        assert score == 80.0

    def test_score_clamped_at_100(self):
        """Score cannot exceed 100 even with all modifiers stacked."""
        # 70 (single) + 15 (EOL) + 15 (Safety) + 10 (unique) = 110 → clamped to 100
        score = _score_single_component(
            _primary("ITEM-1", lifecycle="EOL", criticality="Safety", unique=True)
        )
        assert score == 100.0


# ── SKU-level scoring tests ───────────────────────────────────────────────────

class TestSKUScoring:
    """Validate SKU-level risk score aggregation and risk level classification."""

    def test_all_single_source(self):
        """100% single source → SKU score = 60 (the single_source weight)."""
        bom = _make_bom("SKU-1", [_primary("A"), _primary("B")])
        G = build_graph(bom)
        report = compute_risk_report(bom, G)
        # Both are single source: (2/2)*60 = 60
        assert report.risk_score == 60.0
        assert report.risk_level == "HIGH"

    def test_all_strong_subs(self):
        """All components have strong substitutes → low SKU score."""
        p1 = _primary("A", manufacturer="MFR-A", country="USA")
        p2 = _primary("B", manufacturer="MFR-C", country="Germany")
        s1 = _substitute("A-sub", "A", manufacturer="MFR-B", country="Japan")
        s2 = _substitute("B-sub", "B", manufacturer="MFR-D", country="Taiwan")
        bom = _make_bom("SKU-1", [p1, p2], [s1, s2])
        G = build_graph(bom)
        report = compute_risk_report(bom, G)
        # No single source, no weak subs, no lifecycle/criticality/unique
        assert report.risk_score == 0.0
        assert report.risk_level == "LOW"

    def test_risk_level_thresholds(self):
        """Verify CRITICAL >= 80, HIGH >= 55, MEDIUM >= 30, LOW < 30."""
        from risk_engine import _RISK_THRESHOLDS

        assert _RISK_THRESHOLDS == [(80, "CRITICAL"), (55, "HIGH"), (30, "MEDIUM"), (0, "LOW")]

    def test_mixed_bom_counts(self):
        """Verify counts are correctly tallied in a mixed BOM."""
        p1 = _primary("A", criticality="Safety", unique=True, lifecycle="EOL")
        p2 = _primary("B", manufacturer="MFR-A", country="USA")
        s2 = _substitute("B-sub", "B", manufacturer="MFR-B", country="Japan")
        bom = _make_bom("SKU-1", [p1, p2], [s2])
        G = build_graph(bom)
        report = compute_risk_report(bom, G)

        assert report.total_components == 2
        assert report.single_source_count == 1        # A has no sub
        assert report.components_with_substitutes == 1  # B has sub
        assert report.at_risk_lifecycle_count == 1     # A is EOL
        assert report.critical_parts_count == 1        # A is Safety
        assert report.unique_to_samsara_count == 1     # A is unique


# ── Substitute analyzer edge cases ────────────────────────────────────────────

class TestSubstituteEdgeCases:
    """Edge cases for substitute classification."""

    def test_unknown_origin_not_penalized(self):
        """When origin is unknown for either party, region check is skipped.
        Different manufacturer alone should yield LOW."""
        p = _primary("ITEM-1", manufacturer="MFR-A", country=None)
        s = _substitute("ITEM-2", "ITEM-1", manufacturer="MFR-B", country=None)
        score = _score_single_component(p, [s])
        assert score == 10.0  # LOW base

    def test_multiple_subs_one_strong(self):
        """If at least one substitute is strong, risk is LOW regardless of others."""
        p = _primary("ITEM-1", manufacturer="MFR-A", country="USA")
        s_weak = _substitute("S1", "ITEM-1", manufacturer="MFR-A", country="USA")  # same mfr+region
        s_strong = _substitute("S2", "ITEM-1", manufacturer="MFR-B", country="Japan")  # diff both
        score = _score_single_component(p, [s_weak, s_strong])
        assert score == 10.0  # LOW base


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
