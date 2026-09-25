"""
Command-line entry point -- analyze a Terraform plan JSON without
starting the web dashboard. Also what the CI PR-bot (ci/pr_commenter.py)
calls under the hood.

Usage:
    python cli.py analyze samples/sg_open_ssh.json
    python cli.py analyze samples/sg_open_ssh.json --json
"""

import argparse
import json
import sys

from db import init_db, SessionLocal
from analyzer.pipeline import analyze_plan


def print_report(result: dict):
    print()
    print("=" * 60)
    print("PLAIN-ENGLISH SUMMARY:")
    print(f"  {result['plain_summary']}")
    print("-" * 60)
    print(f"Resource:        {result['resource_address']}")
    print(f"Change Action:   {result['action']}")
    print(f"Changed Fields:  {', '.join(result['changed_fields']) or '(none)'}")
    print("-" * 60)
    print(f"Affected Resources ({result['affected_count']}):")
    for resource in result["affected_resources"]:
        print(f"  -> {resource}")
    if not result["affected_resources"]:
        print("  (none)")
    print("-" * 60)
    print(f"Impact Level:       {result['impact_level']} (relative score {result['impact_score']}/100, not a probability)")
    print(f"Risk Level:         {result['risk_level']}")
    print(f"Data Completeness:  {result['confidence_score']}%")
    print("-" * 60)
    print("Dependency Chain:")
    print("  " + " -> ".join(result["dependency_chain"]))
    print("-" * 60)
    print("Recommendations:")
    for rec in result["recommendations"]:
        print(f"  - {rec}")
    print("-" * 60)
    print("Rollback Plan (if this needs to be undone):")
    for i, step in enumerate(result["rollback_plan"]):
        print(f"  {i+1}. {step}")
    if result["similar_past_changes"]:
        print("-" * 60)
        print("Similar Past Changes:")
        for past in result["similar_past_changes"]:
            print(f"  [{past['risk_level']}] {past['resource_address']} -> {past['outcome']}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Analyze a Terraform plan JSON for change impact/risk.")
    parser.add_argument("command", choices=["analyze"])
    parser.add_argument("plan_file", help="Path to a `terraform show -json <planfile>` output")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of a formatted report")
    args = parser.parse_args()

    init_db()
    session = SessionLocal()

    with open(args.plan_file, "r") as f:
        plan = json.load(f)

    results = analyze_plan(plan, plan_source=args.plan_file, session=session)

    if not results:
        print("No effective changes found in this plan.")
        return

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for result in results:
            print_report(result)


if __name__ == "__main__":
    sys.exit(main())
