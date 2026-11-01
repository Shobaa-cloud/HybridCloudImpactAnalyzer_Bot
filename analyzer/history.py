"""
MySQL/SQLAlchemy-backed history.

Powers the "Similar Past Changes" panel: real past analyses instead of
a static table.

Note on the score computed here (stored as `confidence_score` in the
DB, shown in the UI as "Data Completeness"): an earlier version of this
also boosted the score based on how many similar past analyses existed
-- i.e. "we've seen this pattern before, so we're more confident."
That was removed deliberately: seeing a pattern before says nothing
about whether it's actually safe, and conflating "familiar" with
"confident it's low-risk" is misleading. The score now measures exactly
one thing -- how much of the Terraform plan's data is fully known
before apply, versus how much Terraform itself marks as "unknown until
you actually apply it." That's a real, defensible signal about how
much there is to analyze; "similar past changes" stays purely an
informational lookup (see find_similar_past_changes), never a number.
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


def compute_confidence_score(after_unknown: dict, changed_field_count: int) -> float:
    """
    Measures data completeness only: how much of this change's before/
    after state is actually known pre-apply, versus how much Terraform
    marks "unknown until apply" (e.g. a generated ID). Deliberately does
    NOT factor in how many similar past changes exist -- see the module
    docstring for why that was removed.
    """
    score = Config.BASE_CONFIDENCE_SCORE

    unknown_count = sum(1 for v in after_unknown.values() if v is True)
    total_fields = max(1, changed_field_count + unknown_count)
    known_ratio = 1 - (unknown_count / total_fields)
    score += round(known_ratio * (Config.MAX_CONFIDENCE_SCORE - Config.BASE_CONFIDENCE_SCORE))

    return min(Config.MAX_CONFIDENCE_SCORE, score)


def save_analysis(session, *, plan_source: str, resource_address: str, resource_type: str,
                   change_action: str, changed_fields: dict, affected_count: int,
                   affected_resources: list[str], impact_level: str, risk_level: str,
                   confidence_score: float, dependency_chain: list[str],
                   recommendations: list[str]) -> Analysis:
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
        affected_resources=json.dumps(affected_resources),
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
