from __future__ import annotations

import networkx as nx

from bom_graph_builder import get_substitutes
from models import BOMComponent, BOMData, SubstituteInfo, SubstituteRisk

# Defined here to avoid circular import with risk_engine
_AT_RISK_LIFECYCLE = {"EOL", "LTB", "NRND"}


def analyze_substitutes(
    bom: BOMData, G: nx.DiGraph
) -> dict[str, tuple[SubstituteRisk, list[SubstituteInfo]]]:
    """
    Classify substitute risk for every primary component in the BOM.

    Risk levels (from CLAUDE.md spec):
        HIGH   — no substitutes exist (single source)
        MEDIUM — substitutes exist, but all share the same manufacturer as primary
        LOW    — at least one substitute from a different manufacturer

    Returns:
        dict mapping item_number -> (SubstituteRisk, list[SubstituteInfo])
    """
    item_map: dict[str, BOMComponent] = {c.item_number: c for c in bom.components}
    result: dict[str, tuple[SubstituteRisk, list[SubstituteInfo]]] = {}

    for comp in bom.primary_components:
        sub_ids = get_substitutes(G, comp.item_number)

        subs: list[SubstituteInfo] = []
        for sid in sub_ids:
            sub_comp = item_map.get(sid)
            subs.append(
                SubstituteInfo(
                    item_number=sid,
                    manufacturer=sub_comp.manufacturer if sub_comp else None,
                    mpn=sub_comp.mpn if sub_comp else None,
                    lifecycle_phase=sub_comp.lifecycle_phase if sub_comp else None,
                    country_of_origin=sub_comp.country_of_origin if sub_comp else None,
                )
            )

        result[comp.item_number] = (_classify(comp, subs), subs)

    return result


def _classify(primary: BOMComponent, subs: list[SubstituteInfo]) -> SubstituteRisk:
    """
    Determine risk level for a single primary component.

    LOW    — at least one VIABLE substitute has a DIFFERENT manufacturer AND a
             DIFFERENT country of origin (strong supply-chain diversification).
    MEDIUM — substitutes exist but all viable ones share the same manufacturer
             or region, OR all substitutes are at-risk lifecycle (EOL/LTB/NRND).
    HIGH   — no substitutes at all (single source).

    Viable substitute: lifecycle phase is not EOL / LTB / NRND (i.e. ACTIVE or unknown).
    An EOL/NRND substitute provides no real coverage and is excluded from LOW classification.

    Region check: only applied when BOTH the primary and substitute have a known
    country_of_origin. When origin data is absent, the check is skipped and only
    manufacturer diversity is evaluated (backward-compatible with legacy data).

    Substitute chain note: the sample BOM shows flat (non-chained) substitutes —
    each substitute row points directly to a primary, not to another substitute.
    Revisit bom_graph_builder.get_substitutes() if chained substitutes appear.
    """
    if not subs:
        return SubstituteRisk.HIGH

    # Only count substitutes with a viable (non-at-risk) lifecycle as true coverage
    # None lifecycle = unknown = assume viable (don't penalise missing data)
    viable_subs = [s for s in subs if s.lifecycle_phase not in _AT_RISK_LIFECYCLE]

    if not viable_subs:
        # Substitutes exist but all are EOL/LTB/NRND — effectively no real coverage
        return SubstituteRisk.MEDIUM

    primary_mfr = (primary.manufacturer or "").strip().lower()
    primary_coo = (primary.country_of_origin or "").strip().lower()

    for sub in viable_subs:
        sub_mfr = (sub.manufacturer or "").strip().lower()
        sub_coo = (sub.country_of_origin or "").strip().lower()

        different_mfr = bool(sub_mfr) and sub_mfr != primary_mfr

        # Region check: skip if either party has unknown origin (don't penalise missing data)
        if primary_coo and sub_coo:
            different_region = sub_coo != primary_coo
        else:
            different_region = True  # origin unknown — don't treat as same-region risk

        if different_mfr and different_region:
            return SubstituteRisk.LOW

    return SubstituteRisk.MEDIUM
