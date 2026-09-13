"""Builds the resource dependency graph with NetworkX."""

import networkx as nx


def _extract_node_metadata(plan: dict) -> dict[str, dict]:
    """
    Pull best-effort criticality signals for each resource address from
    the plan's resource_changes ("after" state), so the graph can weight
    blast radius by how sensitive a downstream resource is, not just by
    how many resources are downstream.
    """

    metadata = {}

    for entry in plan.get("resource_changes", []):
        address = entry.get("address")
        state = (entry.get("change", {}).get("after")
                 or entry.get("change", {}).get("before") or {})

        tags = state.get("tags") or {}
        environment = str(tags.get("Environment") or tags.get("environment") or "").lower()

        is_public = False
        cidr_blocks = state.get("cidr_blocks") or []
        if any(str(c).strip() == "0.0.0.0/0" for c in cidr_blocks):
            is_public = True
        if state.get("publicly_accessible") is True:
            is_public = True
        if state.get("map_public_ip_on_launch") is True:
            is_public = True
        if state.get("acl") in ("public-read", "public-read-write"):
            is_public = True

        metadata[address] = {
            "resource_type": entry.get("type", "unknown"),
            "resource_id": state.get("id"),
            "is_production": environment in ("prod", "production"),
            "is_public": is_public,
        }

    return metadata


def build_dependency_graph(plan: dict, references: dict[str, set[str]]) -> nx.DiGraph:
    """
    `references[A] = {B, C}` means A depends on B and C. We store the
    edge as B -> A (and C -> A): "a change to B can propagate to A".
    """

    graph = nx.DiGraph()
    metadata = _extract_node_metadata(plan)

    all_addresses = set(references.keys())
    for deps in references.values():
        all_addresses.update(deps)

    for address in all_addresses:
        node_meta = metadata.get(address, {
            "resource_type": address.split(".")[0] if "." in address else "unknown",
            "resource_id": None,
            "is_production": False,
            "is_public": False,
        })
        graph.add_node(address, **node_meta)

    for dependent, deps in references.items():
        for upstream in deps:
            graph.add_edge(upstream, dependent)

    return graph
