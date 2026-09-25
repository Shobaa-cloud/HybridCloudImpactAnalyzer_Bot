"""Rule-based recommendations, replacing the original static bullet list."""


def _resource_specific_recommendations(resource_type: str, changed_fields: dict, action: str) -> list[str]:
    resource_type = resource_type.lower()
    recs = []

    after_cidrs = (changed_fields.get("cidr_blocks", {}) or {}).get("new") or []
    if "security_group" in resource_type and any(str(c) == "0.0.0.0/0" for c in after_cidrs):
        recs.append(
            "Ingress is being opened to 0.0.0.0/0. Restrict to known CIDR "
            "ranges, or route access through a bastion host / VPN instead."
        )

    if "iam" in resource_type and any("policy" in f.lower() for f in changed_fields):
        recs.append(
            "IAM policy is changing. Apply least-privilege: avoid wildcard "
            "Actions/Resources and review against existing role bindings."
        )

    if ("db_instance" in resource_type or "rds" in resource_type) and action in ("delete", "replace"):
        recs.append(
            "Database is being deleted or replaced. Confirm a recent backup "
            "exists and deletion protection is intentionally disabled."
        )

    if "s3_bucket" in resource_type and any("acl" in f.lower() for f in changed_fields):
        after_acl = (changed_fields.get("acl", {}) or {}).get("new")
        if after_acl in ("public-read", "public-read-write"):
            recs.append(
                "Bucket ACL is becoming public. Verify this is intended -- "
                "public buckets are a leading cause of cloud data exposure."
            )

    if action == "delete":
        recs.append(
            "This is a delete action. Confirm no dependent resource listed "
            "in the impact panel is still actively using this resource."
        )

    return recs


def _risk_level_recommendation(risk_level: str) -> str:
    return {
        "CRITICAL": "Do not deploy without manual review and a rollback plan. "
                    "Notify the on-call owner of every affected resource before proceeding.",
        "HIGH": "Test this change in a staging environment first and schedule "
                "a maintenance window before applying to production.",
        "MEDIUM": "Proceed with normal review, and monitor affected resources "
                  "closely for the first hour after deployment.",
        "LOW": "Standard change. Safe to proceed with normal peer review.",
    }[risk_level]


def generate_recommendations(resource_type: str, action: str, changed_fields: dict, risk_level: str) -> list[str]:
    recs = _resource_specific_recommendations(resource_type, changed_fields, action)
    recs.append(_risk_level_recommendation(risk_level))
    return recs
