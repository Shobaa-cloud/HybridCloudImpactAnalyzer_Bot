"""
Live "current state" snapshot from a real AWS account -- read-only,
on-demand, and nothing else.

Safety design (read this before changing anything in this file):

1. Every AWS call in this file is a Describe/List call. Those are
   control-plane read operations AWS does not bill for -- the same
   category of call the AWS Console itself uses just to display your
   resources to you. This file must never call anything that creates,
   modifies, or deletes a resource (Create*, Put*, Delete*, Modify*,
   Run*, etc.) -- if you're adding a new resource type, only add
   Describe*/List*/Get* calls.

2. This is NOT a background watcher. Nothing here runs on a schedule
   or continuously. It only runs when a human explicitly calls
   fetch_live_snapshot() -- via `python sync_current_state.py` or the
   dashboard's "Sync Now" button -- so AWS is only ever contacted at a
   moment the user chose.

3. The real safety net is IAM, not this code: the credentials used
   here should belong to an IAM user/role scoped to a read-only policy
   (see iam-readonly-policy.json) so that even a bug in this file
   *cannot* create a billable resource -- AWS itself would reject the
   call with AccessDenied. Never attach broader permissions to the
   credentials used for this feature.

The snapshot this produces is deliberately simple: what security
groups, EC2 instances, and RDS databases currently exist, their tags,
and which security groups each instance/database uses. That's enough
to answer "what does my account currently look like" without needing
to re-describe it by hand every time.
"""

import datetime
import json
import os

from config import Config

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:
    boto3 = None

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "..", "current_state_snapshot.json")


def _fetch_security_groups(ec2_client) -> dict:
    resources = {}
    paginator = ec2_client.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page["SecurityGroups"]:
            address = f"aws_security_group.{sg['GroupId']}"
            is_public = any(
                str(r.get("CidrIp")) == "0.0.0.0/0"
                for rule in sg.get("IpPermissions", [])
                for r in rule.get("IpRanges", [])
            )
            resources[address] = {
                "resource_type": "aws_security_group",
                "id": sg["GroupId"],
                "name": sg.get("GroupName"),
                "tags": {t["Key"]: t["Value"] for t in sg.get("Tags", [])},
                "is_public": is_public,
            }
    return resources


def _fetch_ec2_instances(ec2_client) -> dict:
    resources = {}
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if instance.get("State", {}).get("Name") == "terminated":
                    continue
                address = f"aws_instance.{instance['InstanceId']}"
                resources[address] = {
                    "resource_type": "aws_instance",
                    "id": instance["InstanceId"],
                    "tags": {t["Key"]: t["Value"] for t in instance.get("Tags", [])},
                    "security_group_ids": [sg["GroupId"] for sg in instance.get("SecurityGroups", [])],
                    "has_public_ip": bool(instance.get("PublicIpAddress")),
                }
    return resources


def _fetch_rds_instances(rds_client) -> dict:
    resources = {}
    paginator = rds_client.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page["DBInstances"]:
            address = f"aws_db_instance.{db['DBInstanceIdentifier']}"
            resources[address] = {
                "resource_type": "aws_db_instance",
                "id": db["DBInstanceIdentifier"],
                "tags": {t["Key"]: t["Value"] for t in db.get("TagList", [])},
                "security_group_ids": [
                    sg["VpcSecurityGroupId"] for sg in db.get("VpcSecurityGroups", [])
                ],
                "publicly_accessible": db.get("PubliclyAccessible", False),
            }
    return resources


def fetch_live_snapshot(region: str | None = None) -> dict:
    """
    Makes exactly three read-only AWS API calls (security groups, EC2
    instances, RDS instances). Each is wrapped independently so a
    partially-scoped IAM policy still returns whatever it's allowed to
    see instead of failing the whole sync.
    """

    if boto3 is None:
        raise RuntimeError("boto3 is not installed.")

    region = region or Config.AWS_DEFAULT_REGION
    resources = {}
    errors = []

    try:
        ec2 = boto3.client("ec2", region_name=region)
        resources.update(_fetch_security_groups(ec2))
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        errors.append(f"security groups: {e}")

    try:
        ec2 = boto3.client("ec2", region_name=region)
        resources.update(_fetch_ec2_instances(ec2))
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        errors.append(f"ec2 instances: {e}")

    try:
        rds = boto3.client("rds", region_name=region)
        resources.update(_fetch_rds_instances(rds))
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        errors.append(f"rds instances: {e}")

    return {
        "synced_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "region": region,
        "resources": resources,
        "errors": errors,
    }


def save_snapshot(snapshot: dict, path: str = SNAPSHOT_PATH) -> None:
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)


def load_snapshot(path: str = SNAPSHOT_PATH) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
