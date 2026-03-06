from __future__ import annotations

import networkx as nx

from models import BOMComponent, BOMData


def build_graph(bom: BOMData) -> nx.DiGraph:
    """
    Build a directed graph of the BOM for in-memory analysis (Phase 1).

    Node types:
        sku       — top-level product node
        component — individual BOM item (primary or substitute)

    Edge types:
        USES        — SKU → primary component
        SUBSTITUTE  — primary component → its substitute(s)

    Phase 2: swap NetworkX for Neo4j to support multi-level BOMs,
    cross-SKU where-used queries, and complex graph traversals at scale.
    """
    G: nx.DiGraph = nx.DiGraph()

    # Add SKU node
    G.add_node(bom.sku_id, type="sku", description=bom.description)

    # Add all component nodes
    for comp in bom.components:
        G.add_node(
            comp.item_number,
            type="component",
            description=comp.description,
            manufacturer=comp.manufacturer,
            mpn=comp.mpn,
            lifecycle_phase=comp.lifecycle_phase,
            criticality_type=comp.criticality_type,
            is_substitute=comp.is_substitute,
            flag_risk_review=comp.flag_risk_review,
        )

    # USES edges: SKU → each primary component
    for comp in bom.primary_components:
        G.add_edge(bom.sku_id, comp.item_number, relation="USES")

    # SUBSTITUTE edges: primary → substitute
    for comp in bom.substitute_components:
        if comp.substitute_for:
            primary = comp.substitute_for
            if primary not in G:
                # Data integrity gap: primary not in BOM — add placeholder node
                G.add_node(primary, type="component", description="[unknown]")
                G.add_edge(bom.sku_id, primary, relation="USES")
            G.add_edge(primary, comp.item_number, relation="SUBSTITUTE")

    return G


def get_substitutes(G: nx.DiGraph, item_number: str) -> list[str]:
    """Return item numbers of all direct substitutes for a primary component."""
    return [
        n for n in G.successors(item_number)
        if G.edges[item_number, n].get("relation") == "SUBSTITUTE"
    ]


def get_where_used(G: nx.DiGraph, item_number: str) -> list[str]:
    """
    Return SKU/assembly nodes that directly use this component via USES edges.

    In Phase 1 (single BOM), this returns at most one SKU.
    In Phase 2 (multi-SKU graph), this reveals cross-SKU impact for risk amplification.
    """
    return [
        n for n in G.predecessors(item_number)
        if G.edges[n, item_number].get("relation") == "USES"
    ]
