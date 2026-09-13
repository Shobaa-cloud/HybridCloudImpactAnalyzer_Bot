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

    for resource in root_module.get("resources", []):
        address = resource.get("address")
        refs = set()

        for expr in resource.get("expressions", {}).values():
            if isinstance(expr, dict) and "references" in expr:
                for ref in expr["references"]:
                    # Terraform includes attribute-level refs like
                    # "aws_security_group.web.id" -- normalize to the
                    # resource address.
                    resource_ref = ".".join(ref.split(".")[:2])
                    if resource_ref != address:
                        refs.add(resource_ref)

        explicit_depends_on = resource.get("depends_on", [])
        refs.update(explicit_depends_on)

        if address:
            references[address] = refs

    return references
