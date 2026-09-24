"""
Seeds a handful of historical analyses with recorded outcomes, so the
"Similar Past Changes" panel has real data to show the first time you
run the demo, instead of starting empty. Safe to run multiple times --
it skips seeding if history already exists.

Usage: python seed_history.py
"""

import datetime
import json

from db import init_db, SessionLocal
from db.models import Analysis, IncidentOutcome

SEED_ROWS = [
    {
        "days_ago": 120,
        "resource_address": "aws_security_group.legacy_sg",
        "resource_type": "aws_security_group",
        "change_action": "update",
        "impact_level": "HIGH",
        "risk_level": "HIGH",
        "confidence_score": 80,
        "outcome_text": "EC2 SSH access failed for on-call engineer",
        "was_incident": True,
    },
    {
        "days_ago": 90,
        "resource_address": "aws_security_group.deploy_sg",
        "resource_type": "aws_security_group",
        "change_action": "update",
        "impact_level": "HIGH",
        "risk_level": "CRITICAL",
        "confidence_score": 78,
        "outcome_text": "Deployment pipeline failed, rolled back within 20 minutes",
        "was_incident": True,
    },
    {
        "days_ago": 60,
        "resource_address": "aws_security_group.batch_sg",
        "resource_type": "aws_security_group",
        "change_action": "delete",
        "impact_level": "MEDIUM",
        "risk_level": "HIGH",
        "confidence_score": 75,
        "outcome_text": "EC2 instance became unreachable for 15 minutes",
        "was_incident": True,
    },
    {
        "days_ago": 30,
        "resource_address": "aws_security_group.staging_sg",
        "resource_type": "aws_security_group",
        "change_action": "update",
        "impact_level": "LOW",
        "risk_level": "MEDIUM",
        "confidence_score": 82,
        "outcome_text": "No service disruption, change applied cleanly",
        "was_incident": False,
    },
]


def seed():
    init_db()
    session = SessionLocal()

    if session.query(Analysis).count() > 0:
        print("History already has data -- skipping seed. "
              "Delete local.db (or truncate the tables) to reseed.")
        return

    for row in SEED_ROWS:
        analysis = Analysis(
            created_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=row["days_ago"]),
            plan_source="seed_history.py",
            resource_address=row["resource_address"],
            resource_type=row["resource_type"],
            change_action=row["change_action"],
            changed_attributes=json.dumps({}),
            affected_count=1,
            impact_level=row["impact_level"],
            risk_level=row["risk_level"],
            confidence_score=row["confidence_score"],
            dependency_path=json.dumps([row["resource_address"]]),
            affected_resources=json.dumps(["aws_instance.affected_by_" + row["resource_address"].split(".")[-1]]),
            recommendations=json.dumps([]),
        )
        session.add(analysis)
        session.flush()

        session.add(IncidentOutcome(
            analysis_id=analysis.id,
            outcome_text=row["outcome_text"],
            was_incident=row["was_incident"],
        ))

    session.commit()
    print(f"Seeded {len(SEED_ROWS)} historical analyses.")


if __name__ == "__main__":
    seed()
