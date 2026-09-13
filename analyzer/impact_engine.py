"""
Blast-radius scoring.

Unlike the original prototype (impact = LOW/MEDIUM/HIGH purely from a
count of direct dependents), this weighs *every* downstream resource
reachable in the dependency graph, discounted by how many hops away it
is, and boosted if that resource is tagged production or is
internet-facing. A change that reaches one production database should
outrank a change that reaches three untagged dev resources.
"""

import networkx as nx

PRODUCTION_WEIGHT = 1.5
PUBLIC_WEIGHT = 1.0
BASE_WEIGHT = 1.0


def _node_weight(graph: nx.DiGraph, node: str, depth: int) -> float:
    attrs = graph.nodes.get(node, {})
    weight = BASE_WEIGHT
    if attrs.get("is_production"):
        weight += PRODUCTION_WEIGHT
    if attrs.get("is_public"):
        weight += PUBLIC_WEIGHT
    return weight / (1 + depth)


def assess_impact(graph: nx.DiGraph, changed_address: str) -> dict:
    if changed_address not in graph:
        return {
            "affected_resources": [],
            "affected_count": 0,
            "impact_score": 0,
            "impact_level": "LOW",
            "dependency_chain": [changed_address],
        }

    depths = nx.single_source_shortest_path_length(graph, changed_address)
    affected = {node: d for node, d in depths.items() if node != changed_address}

    raw_score = sum(_node_weight(graph, node, depth) for node, depth in affected.items())
    impact_score = min(100, round(raw_score * 12))

    if not affected:
        impact_level = "LOW"
    elif raw_score < 2:
        impact_level = "MEDIUM"
    elif raw_score < 5:
        impact_level = "HIGH"
    else:
        impact_level = "CRITICAL"

    # Longest downstream path, for the "dependency chain" visualization --
    # the deepest cascade the change could travel through.
    if affected:
        deepest_node = max(affected, key=affected.get)
        dependency_chain = nx.shortest_path(graph, changed_address, deepest_node)
    else:
        dependency_chain = [changed_address]

    return {
        "affected_resources": sorted(affected, key=affected.get),
        "affected_count": len(affected),
        "impact_score": impact_score,
        "impact_level": impact_level,
        "dependency_chain": dependency_chain,
    }
