"""
Generates a concrete rollback plan *before* the change is even applied.

Most tools stop at "this is risky" and leave the human to figure out
recovery under pressure, mid-incident. This computes the undo steps
up front, from the same before/after diff already being analyzed, so
they're sitting right next to the risk report -- not something you
have to improvise at 2am.
"""


def generate_rollback_plan(resource_address: str, action: str, changed_fields: dict) -> list[str]:
    steps = []

    if action == "create":
        steps.append(f"Run `terraform destroy -target={resource_address}` to remove it.")
    elif action == "delete":
        steps.append(
            f"Restore `{resource_address}` from your last known-good Terraform state/backup "
            "and re-apply -- it no longer exists once this change is applied, so there is no "
            "partial-undo, only a full recreate."
        )
    elif action == "replace":
        steps.append(
            f"`{resource_address}` will be destroyed and recreated with a new ID. To roll back, "
            "revert your Terraform configuration for this resource to its previous values and "
            "re-apply -- then update anything elsewhere that hardcodes the old resource ID."
        )
    else:  # update
        if not changed_fields:
            steps.append(f"No tracked attribute changes to roll back on `{resource_address}`.")
        for field, values in changed_fields.items():
            steps.append(f"Set `{field}` on `{resource_address}` back to `{values.get('old')!r}`.")

    steps.append(
        f"Run `terraform plan` afterward -- it should show no differences for "
        f"`{resource_address}` once the rollback is complete."
    )
    return steps
