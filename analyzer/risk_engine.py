"""
Risk scoring.

The original prototype had exactly one rule ("if setting == allowed_ip").
This replaces it with a general model: every change gets a base severity
from its resource type, is bumped for destructive actions and for
touching security-sensitive fields, and is then combined with the
blast-radius impact level computed by impact_engine.

These keyword lists match by substring, not exact resource type, and
deliberately include AWS, Azure, and GCP equivalents side by side
(e.g. "security_group" for AWS/matches Azure's
"network_security_group" too; "firewall" for GCP's
"google_compute_firewall") -- this is what makes the tool genuinely
work across a multi-cloud Terraform plan rather than only AWS.
"""

LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

HIGH_SEVERITY_TYPES = (
    # Networking / access-control surfaces, across providers.
    "security_group", "security_rule", "network_acl", "route_table",
    "firewall", "nat_gateway", "internet_gateway", "vpn", "waf",
    # Identity/permissions, across providers.
    "iam", "role_assignment", "role_binding", "key_vault", "kms",
)
MEDIUM_SEVERITY_TYPES = (
    # Databases, across providers.
    "db_instance", "rds", "sql_database", "sql_server", "cosmosdb", "cloudsql",
    # Storage, across providers.
    "s3_bucket", "storage_bucket", "storage_account",
    # Compute, across providers.
    "instance", "virtual_machine", "compute_instance",
    "subnet", "vpc", "virtual_network",
    "load_balancer", "lambda_function", "cloud_function",
    "ecs_service", "eks_cluster", "kubernetes_cluster", "container_cluster",
)

SENSITIVE_FIELD_KEYWORDS = (
    # "Open to the world" signals, across providers: AWS uses
    # cidr_blocks/ingress, Azure uses source_address_prefix/access,
    # GCP uses source_ranges/allow.
    "cidr_blocks", "ingress", "egress", "source_address_prefix",
    "source_ranges", "policy", "acl",
    "publicly_accessible", "allowed_ip", "assume_role_policy",
    "map_public_ip_on_launch", "public_access", "public_network_access",
)


def _base_severity(resource_type: str) -> str:
    resource_type = resource_type.lower()
    if any(t in resource_type for t in HIGH_SEVERITY_TYPES):
        return "HIGH"
    if any(t in resource_type for t in MEDIUM_SEVERITY_TYPES):
        return "MEDIUM"
    return "LOW"


def _touches_sensitive_field(changed_fields: dict) -> bool:
    return any(
        keyword in field_name.lower()
        for field_name in changed_fields
        for keyword in SENSITIVE_FIELD_KEYWORDS
    )


def _bump(level: str, steps: int) -> str:
    index = min(len(LEVELS) - 1, LEVELS.index(level) + steps)
    return LEVELS[index]


def assess_risk(resource_type: str, action: str, changed_fields: dict, impact_level: str) -> dict:
    base_severity = _base_severity(resource_type)
    sensitive = _touches_sensitive_field(changed_fields)

    risk_level = LEVELS[max(LEVELS.index(base_severity), LEVELS.index(impact_level))]

    if sensitive:
        risk_level = _bump(risk_level, 1)
    if action in ("delete", "replace") and base_severity != "LOW":
        risk_level = _bump(risk_level, 1)

    return {
        "risk_level": risk_level,
        "base_severity": base_severity,
        "touches_sensitive_field": sensitive,
    }
