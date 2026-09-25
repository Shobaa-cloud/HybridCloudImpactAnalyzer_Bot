"""
Optional live-AWS enrichment via boto3.

The core pipeline works entirely offline from a Terraform plan JSON --
this module is an add-on for teams who *do* have an AWS account: when
enabled, it looks up real tags for resources referenced in the plan, so
the "is production" / "is public" criticality signals reflect the
account's actual current tagging rather than only what's declared in
the Terraform diff.

Disabled by default (Config.ENABLE_AWS_ENRICHMENT). Every AWS call is
wrapped defensively -- a missing credential, a throttled API, or an
unmapped resource type should degrade to "no enrichment", never crash
the analysis.
"""

import networkx as nx

from config import Config

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # boto3 not installed in this environment
    boto3 = None


def _tags_indicate_production(tags: list[dict]) -> bool:
    for tag in tags or []:
        key = str(tag.get("Key", "")).lower()
        value = str(tag.get("Value", "")).lower()
        if key == "environment" and value in ("prod", "production"):
            return True
    return False


def _enrich_security_group(ec2_client, node_id: str) -> dict | None:
    response = ec2_client.describe_security_groups(GroupIds=[node_id])
    group = response["SecurityGroups"][0]
    is_public = any(
        str(rule_range.get("CidrIp")) == "0.0.0.0/0"
        for rule in group.get("IpPermissions", [])
        for rule_range in rule.get("IpRanges", [])
    )
    return {
        "is_production": _tags_indicate_production(group.get("Tags", [])),
        "is_public": is_public,
    }


def _enrich_ec2_instance(ec2_client, node_id: str) -> dict | None:
    response = ec2_client.describe_instances(InstanceIds=[node_id])
    instance = response["Reservations"][0]["Instances"][0]
    return {
        "is_production": _tags_indicate_production(instance.get("Tags", [])),
        "is_public": bool(instance.get("PublicIpAddress")),
    }


ENRICHERS = {
    "aws_security_group": ("ec2", _enrich_security_group),
    "aws_instance": ("ec2", _enrich_ec2_instance),
}


def enrich_graph_with_aws(graph: nx.DiGraph) -> int:
    """Mutates matching nodes in place. Returns how many nodes were enriched."""

    if not Config.ENABLE_AWS_ENRICHMENT or boto3 is None:
        return 0

    clients = {}
    enriched = 0

    for node, attrs in graph.nodes(data=True):
        resource_type = attrs.get("resource_type")
        resource_id = attrs.get("resource_id")
        if resource_type not in ENRICHERS or not resource_id:
            continue

        client_name, enrich_fn = ENRICHERS[resource_type]
        if client_name not in clients:
            clients[client_name] = boto3.client(client_name, region_name=Config.AWS_DEFAULT_REGION)

        try:
            live_data = enrich_fn(clients[client_name], resource_id)
        except (BotoCoreError, ClientError, KeyError, IndexError):
            continue

        if live_data:
            graph.nodes[node].update(live_data)
            enriched += 1

    return enriched
