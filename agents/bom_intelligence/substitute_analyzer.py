from __future__ import annotations

import networkx as nx

from bom_graph_builder import get_substitutes
from models import BOMComponent, BOMData, SubstituteInfo, SubstituteRisk


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
                )
            )

        result[comp.item_number] = (_classify(comp, subs), subs)

    return result


def _classify(primary: BOMComponent, subs: list[SubstituteInfo]) -> SubstituteRisk:
    """
    Determine risk level for a single primary component.

    Substitute chain note: the sample BOM shows flat (non-chained) substitutes —
    each substitute row points directly to a primary, not to another substitute.
    This implementation treats all substitutes as direct alternates of the primary.
    If chained substitutes emerge in production data, revisit graph traversal in
    bom_graph_builder.get_substitutes().
    """
    if not subs:
        return SubstituteRisk.HIGH

    primary_mfr = (primary.manufacturer or "").strip().lower()
    has_different_mfr = any(
        (sub.manufacturer or "").strip().lower() != primary_mfr
        for sub in subs
        if sub.manufacturer
    )
    return SubstituteRisk.LOW if has_different_mfr else SubstituteRisk.MEDIUM
