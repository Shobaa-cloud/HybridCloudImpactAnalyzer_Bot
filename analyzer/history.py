"""
MySQL/SQLAlchemy-backed history.

Powers two things the original prototype faked with hardcoded numbers:
  - the "Similar Past Changes" panel (real past analyses instead of a
    static table)
  - the confidence score (grows as more historical data accumulates,
    instead of a fixed "91%")
"""

import json

from config import Config
from db.models import Analysis, IncidentOutcome


def serialize_similar_change(analysis: Analysis) -> dict:
    outcome = analysis.outcomes[0] if analysis.outcomes else None
    return {
        "id": analysis.id,
        "resource_address": analysis.resource_address,
        "change_action": analysis.change_action,
        "risk_level": analysis.risk_level,
        "outcome": outcome.outcome_text if outcome else "No recorded outcome yet",
        "was_incident": outcome.was_incident if outcome else False,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def find_similar_past_changes(session, resource_type: str, change_action: str,
                               exclude_id: int | None = None, limit: int = 5) -> list[Analysis]:
    query = (
        session.query(Analysis)
        .filter(Analysis.resource_type == resource_type)
        .filter(Analysis.change_action == change_action)
        .order_by(Analysis.created_at.desc())
    )
    if exclude_id is not None:
        query = query.filter(Analysis.id != exclude_id)

    return query.limit(limit).all()


def compute_confidence_score(session, resource_type: str, change_action: str,
                              after_unknown: dict, changed_field_count: int) -> float:
    score = Config.BASE_CONFIDENCE_SCORE

    # Terraform marks attributes it can't know until after apply (e.g.
    # generated IDs). Fewer unknowns pre-apply means a more reliable
    # before/after diff to analyze.
    unknown_count = sum(1 for v in after_unknown.values() if v is True)
    total_fields = max(1, changed_field_count + unknown_count)
    known_ratio = 1 - (unknown_count / total_fields)
    score += round(known_ratio * 20)

    similar_count = (
        session.query(Analysis)
        .filter(Analysis.resource_type == resource_type)
        .filter(Analysis.change_action == change_action)
        .count()
    )
    score += min(20, similar_count * 4)

    return min(Config.MAX_CONFIDENCE_SCORE, score)


def save_analysis(session, *, plan_source: str, resource_address: str, resource_type: str,
                   change_action: str, changed_fields: dict, affected_count: int,
                   impact_level: str, risk_level: str, confidence_score: float,
                   dependency_chain: list[str], recommendations: list[str]) -> Analysis:
    analysis = Analysis(
        plan_source=plan_source,
        resource_address=resource_address,
        resource_type=resource_type,
        change_action=change_action,
        changed_attributes=json.dumps(changed_fields, default=str),
        affected_count=affected_count,
        impact_level=impact_level,
        risk_level=risk_level,
        confidence_score=confidence_score,
        dependency_path=json.dumps(dependency_chain),
        recommendations=json.dumps(recommendations),
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def record_outcome(session, analysis_id: int, outcome_text: str, was_incident: bool) -> IncidentOutcome:
    outcome = IncidentOutcome(
        analysis_id=analysis_id,
        outcome_text=outcome_text,
        was_incident=was_incident,
    )
    session.add(outcome)
    session.commit()
    session.refresh(outcome)
    return outcome
