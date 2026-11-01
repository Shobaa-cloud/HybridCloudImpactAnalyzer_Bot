"""
Plain-English summary.

Everything else in analyzer/ produces output aimed at someone who
already knows what a security group or a dependency graph is. This is
the one output aimed at everyone else -- a manager, a client, a
teammate from a different team -- who should be able to read three
sentences and understand what's changing and how worried to be,
without any cloud background.
"""

RISK_PLAIN = {
    "LOW": "This is a routine change and is considered safe to proceed.",
    "MEDIUM": "This change carries some risk and should be reviewed before proceeding.",
    "HIGH": "This change carries significant risk and should be tested and reviewed carefully before proceeding.",
    "CRITICAL": "This change carries serious risk and should not proceed without careful review and a rollback plan ready.",
}

ACTION_PLAIN = {
    "create": "adds a new",
    "update": "modifies an existing",
    "delete": "removes an existing",
    "replace": "replaces (destroys and recreates) an existing",
}


def _plain_resource_name(resource_type: str) -> str:
    for prefix in ("aws_", "azurerm_", "google_"):
        if resource_type.startswith(prefix):
            resource_type = resource_type[len(prefix):]
            break
    return resource_type.replace("_", " ")


def _resource_type_from_address(address: str) -> str:
    """
    A resource address always ends in "<type>.<name>", but may be
    prefixed by one or more "module.<name>." segments (confirmed
    against real `terraform show -json` output, e.g.
    "module.app.aws_instance.web") -- so the type is the *second-to-last*
    dot-separated segment, not the first.
    """
    parts = address.split(".")
    return parts[-2] if len(parts) >= 2 else address


def generate_plain_summary(resource_address: str, resource_type: str, action: str,
                            affected_count: int, affected_resources: list[str], risk_level: str) -> str:
    action_phrase = ACTION_PLAIN.get(action, "changes a")
    resource_name = _plain_resource_name(resource_type)

    sentence1 = f"This change {action_phrase} {resource_name} (`{resource_address}`)."

    if affected_count == 0:
        sentence2 = "Nothing else in the system depends on it, so the change should stay contained."
    elif not affected_resources:
        # affected_count is known but we don't have the actual list (e.g.
        # an older stored analysis) -- don't fabricate an "including: "
        # clause with nothing in it.
        sentence2 = f"{affected_count} other connected resource(s) may be affected."
    else:
        examples = ", ".join(_plain_resource_name(_resource_type_from_address(r)) for r in affected_resources[:3])
        remainder = affected_count - min(3, len(affected_resources))
        more = f" and {remainder} more" if remainder > 0 else ""
        sentence2 = f"{affected_count} other connected resource(s) may be affected, including: {examples}{more}."

    sentence3 = RISK_PLAIN.get(risk_level, "")

    return " ".join(part for part in [sentence1, sentence2, sentence3] if part)
