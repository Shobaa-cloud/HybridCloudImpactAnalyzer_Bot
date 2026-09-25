"""
Parses `terraform show -json <planfile>` output.

This is Terraform's own stable, documented plan JSON schema (used by
Terraform Cloud, Atlantis, etc.), not a project-specific format -- so
this module works on real Terraform output for AWS, Azure, or GCP
resources alike, which is what makes the tool "hybrid cloud" rather
than AWS-only.
"""

from dataclasses import dataclass, field


ACTION_MAP = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
    ("no-op",): "no-op",
    ("read",): "read",
}


@dataclass
class ResourceChange:
    address: str
    resource_type: str
    action: str
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    changed_fields: dict = field(default_factory=dict)
    after_unknown: dict = field(default_factory=dict)

    def is_effective_change(self) -> bool:
        return self.action not in ("no-op", "read")


def _diff_fields(before: dict, after: dict) -> dict:
    before = before or {}
    after = after or {}
    changed = {}
    for key in set(before) | set(after):
        old_val = before.get(key)
        new_val = after.get(key)
        if old_val != new_val:
            changed[key] = {"old": old_val, "new": new_val}
    return changed


def parse_resource_changes(plan: dict) -> list[ResourceChange]:
    """Extract the effective resource changes from a plan JSON document."""

    results = []

    for entry in plan.get("resource_changes", []):
        change = entry.get("change", {})
        actions = tuple(change.get("actions", []))
        action = ACTION_MAP.get(actions, "/".join(actions) or "unknown")

        before = change.get("before") or {}
        after = change.get("after") or {}

        resource_change = ResourceChange(
            address=entry.get("address", "unknown"),
            resource_type=entry.get("type", "unknown"),
            action=action,
            before=before,
            after=after,
            changed_fields=_diff_fields(before, after),
            after_unknown=change.get("after_unknown") or {},
        )

        if resource_change.is_effective_change():
            results.append(resource_change)

    return results


def _normalize_reference(ref: str, module_path: str) -> str:
    """
    Turn a raw Terraform reference string into a fully-qualified address
    matching how `resource_changes` addresses things (e.g. Terraform
    itself addresses a resource inside a module call as
    "module.app.aws_instance.web", confirmed against real `terraform
    show -json` output, not assumed).

    A reference like "aws_security_group.web_sg.id" found *inside*
    module "app" means a sibling resource in that same module, so it
    needs "module.app." prefixed on. A reference already anchored at
    "module." points at a different module and is left as-is (best
    effort -- an output reference like "module.network.vpc_id" doesn't
    always resolve to one specific resource address).
    """
    if ref.startswith("module."):
        parts = ref.split(".")
        return ".".join(parts[:2])
    resource_ref = ".".join(ref.split(".")[:2])
    return module_path + resource_ref


def _walk_module(module_node: dict, module_path: str, references: dict[str, set[str]]) -> None:
    """
    Recursively walks `configuration.root_module` and every nested
    `module_calls[...].module`, so dependency references are captured
    for resources declared inside Terraform modules -- not just ones
    declared directly at the root. This matters because most real-world
    Terraform code is organized into modules; without this, the graph
    would silently miss most of a real project's dependencies.
    """

    for resource in module_node.get("resources", []):
        local_address = resource.get("address")
        if not local_address:
            continue

        full_address = module_path + local_address
        refs = set()

        for expr in resource.get("expressions", {}).values():
            if isinstance(expr, dict) and "references" in expr:
                for ref in expr["references"]:
                    normalized = _normalize_reference(ref, module_path)
                    if normalized != full_address:
                        refs.add(normalized)

        for dep in resource.get("depends_on", []):
            normalized = _normalize_reference(dep, module_path)
            if normalized != full_address:
                refs.add(normalized)

        references[full_address] = refs

    for call_name, call in module_node.get("module_calls", {}).items():
        nested_module = call.get("module", {})
        nested_path = f"{module_path}module.{call_name}."
        _walk_module(nested_module, nested_path, references)


def parse_dependency_references(plan: dict) -> dict[str, set[str]]:
    """
    Build {resource_address: {addresses it references}} from Terraform's
    own configuration block -- the same reference data Terraform uses
    internally to compute apply order. An edge here means "this resource
    depends on / uses the referenced resource", so if the referenced
    resource changes, this one may be affected.
    """

    references: dict[str, set[str]] = {}
    root_module = plan.get("configuration", {}).get("root_module", {})
    _walk_module(root_module, "", references)
    return references
