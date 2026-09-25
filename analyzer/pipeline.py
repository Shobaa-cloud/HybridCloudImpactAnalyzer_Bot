"""
End-to-end orchestration: plan JSON in, persisted analyses out.

This is the module that replaces compare.py from the original
prototype -- but instead of two hand-written config files, it consumes
a standard Terraform plan and runs every effective resource change
through the full graph/impact/risk/recommendation pipeline.
"""

from analyzer.plan_parser import parse_resource_changes, parse_dependency_references
from analyzer.graph_builder import build_dependency_graph
from analyzer.aws_enrichment import enrich_graph_with_aws
from analyzer.impact_engine import assess_impact
from analyzer.risk_engine import assess_risk
from analyzer.recommendation_engine import generate_recommendations
from analyzer.rollback_generator import generate_rollback_plan
from analyzer.summary_generator import generate_plain_summary
from analyzer.history import (
    find_similar_past_changes, compute_confidence_score, save_analysis, serialize_similar_change,
)


def analyze_plan(plan: dict, plan_source: str, session) -> list[dict]:
    resource_changes = parse_resource_changes(plan)
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)
    enrich_graph_with_aws(graph)

    results = []

    for change in resource_changes:
        impact = assess_impact(graph, change.address)
        risk = assess_risk(
            resource_type=change.resource_type,
            action=change.action,
            changed_fields=change.changed_fields,
            impact_level=impact["impact_level"],
        )
        confidence_score = compute_confidence_score(
            after_unknown=change.after_unknown,
            changed_field_count=len(change.changed_fields),
        )
        recommendations = generate_recommendations(
            resource_type=change.resource_type,
            action=change.action,
            changed_fields=change.changed_fields,
            risk_level=risk["risk_level"],
        )
        rollback_plan = generate_rollback_plan(
            resource_address=change.address,
            action=change.action,
            changed_fields=change.changed_fields,
        )
        plain_summary = generate_plain_summary(
            resource_address=change.address,
            resource_type=change.resource_type,
            action=change.action,
            affected_count=impact["affected_count"],
            affected_resources=impact["affected_resources"],
            risk_level=risk["risk_level"],
        )

        saved = save_analysis(
            session,
            plan_source=plan_source,
            resource_address=change.address,
            resource_type=change.resource_type,
            change_action=change.action,
            changed_fields=change.changed_fields,
            affected_count=impact["affected_count"],
            affected_resources=impact["affected_resources"],
            impact_level=impact["impact_level"],
            risk_level=risk["risk_level"],
            confidence_score=confidence_score,
            dependency_chain=impact["dependency_chain"],
            recommendations=recommendations,
        )

        similar = find_similar_past_changes(
            session, change.resource_type, change.action, exclude_id=saved.id
        )

        results.append({
            "id": saved.id,
            "resource_address": change.address,
            "resource_type": change.resource_type,
            "action": change.action,
            "changed_fields": change.changed_fields,
            "affected_resources": impact["affected_resources"],
            "affected_count": impact["affected_count"],
            "impact_level": impact["impact_level"],
            "impact_score": impact["impact_score"],
            "risk_level": risk["risk_level"],
            "confidence_score": confidence_score,
            "dependency_chain": impact["dependency_chain"],
            "dependency_graph": impact["dependency_graph"],
            "recommendations": recommendations,
            "rollback_plan": rollback_plan,
            "plain_summary": plain_summary,
            "similar_past_changes": [serialize_similar_change(a) for a in similar],
        })

    # Highest risk first, so the dashboard headline is the thing that
    # actually matters most in this plan.
    results.sort(key=lambda r: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(r["risk_level"]), reverse=True)
    return results
