"""
Pulls a read-only snapshot of your current AWS account (security
groups, EC2 instances, RDS instances) and saves it locally, so the
dashboard already knows what your account looks like instead of
requiring you to describe it from scratch every time.

This makes exactly 3 AWS API calls, all Describe/List (never Create,
Put, Delete, or Modify), and does not run in the background or on a
schedule -- it only touches AWS when you run this command.

Setup (one-time):
  1. In the AWS Console, create an IAM user with NO console access,
     "Access key - Programmatic access" only.
  2. Attach the policy in iam-readonly-policy.json to that user
     (IAM -> Users -> your user -> Add permissions -> Create inline
     policy -> JSON tab -> paste the file's contents). This policy
     grants only the 3 read actions this script uses -- nothing else,
     so even a bug here cannot create or change anything billable.
  3. Set the credentials as environment variables (do not commit them
     to .env if that file is tracked in git -- .gitignore already
     excludes .env):
       AWS_ACCESS_KEY_ID=...
       AWS_SECRET_ACCESS_KEY=...
       AWS_DEFAULT_REGION=us-east-1   (or your region)
  4. (Recommended, also free) In AWS Billing -> Budgets, create a
     zero-spend budget alert so you get emailed the instant any charge
     appears, regardless of this tool.

Usage:
    python sync_current_state.py
"""

import sys

from analyzer.live_state import fetch_live_snapshot, save_snapshot


def main():
    print("Syncing current AWS state (read-only calls only: "
          "DescribeSecurityGroups, DescribeInstances, DescribeDBInstances)...")

    try:
        snapshot = fetch_live_snapshot()
    except RuntimeError as e:
        print(f"Could not sync: {e}", file=sys.stderr)
        sys.exit(1)

    if not snapshot["resources"] and snapshot["errors"]:
        print("No resources fetched. Errors:", file=sys.stderr)
        for error in snapshot["errors"]:
            print(f"  - {error}", file=sys.stderr)
        print("\nCheck that AWS credentials are set and the IAM policy in "
              "iam-readonly-policy.json is attached.", file=sys.stderr)
        sys.exit(1)

    save_snapshot(snapshot)

    by_type = {}
    for resource in snapshot["resources"].values():
        by_type[resource["resource_type"]] = by_type.get(resource["resource_type"], 0) + 1

    print(f"\nSynced at {snapshot['synced_at']} (region: {snapshot['region']})")
    for resource_type, count in by_type.items():
        print(f"  {resource_type}: {count}")

    if snapshot["errors"]:
        print("\nSome resource types were skipped (likely missing IAM permission -- harmless):")
        for error in snapshot["errors"]:
            print(f"  - {error}")

    print(f"\nSaved to current_state_snapshot.json")


if __name__ == "__main__":
    main()
