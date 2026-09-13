import json
import os

import pytest

from analyzer.plan_parser import parse_resource_changes, parse_dependency_references
from analyzer.graph_builder import build_dependency_graph
from analyzer.impact_engine import assess_impact
from analyzer.risk_engine import assess_risk

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")


def load_plan(filename):
    with open(os.path.join(SAMPLES_DIR, filename)) as f:
        return json.load(f)


def test_parse_resource_changes_skips_no_op():
    plan = load_plan("sg_open_ssh.json")
    changes = parse_resource_changes(plan)
    addresses = {c.address for c in changes}
    assert addresses == {"aws_security_group.web_sg"}


def test_diff_detects_cidr_change():
    plan = load_plan("sg_open_ssh.json")
    changes = parse_resource_changes(plan)
    sg_change = changes[0]
    assert "cidr_blocks" in sg_change.changed_fields
    assert sg_change.changed_fields["cidr_blocks"]["new"] == ["0.0.0.0/0"]


def test_graph_has_edges_from_references():
    plan = load_plan("sg_open_ssh.json")
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)
    assert graph.has_edge("aws_security_group.web_sg", "aws_instance.web")
    assert graph.has_edge("aws_security_group.web_sg", "aws_db_instance.app_db")


def test_blast_radius_reaches_transitive_dependents():
    plan = load_plan("sg_open_ssh.json")
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)
    impact = assess_impact(graph, "aws_security_group.web_sg")
    # web_sg -> web -> lb_attachment is two hops; both should be affected.
    assert "aws_lb_target_group_attachment.web_attach" in impact["affected_resources"]
    assert impact["affected_count"] == 3


def test_impact_is_low_with_no_dependents():
    plan = load_plan("log_retention_change.json")
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)
    impact = assess_impact(graph, "aws_cloudwatch_log_group.app_logs")
    assert impact["affected_count"] == 0
    assert impact["impact_level"] == "LOW"


def test_delete_action_bumps_risk_above_update():
    update_risk = assess_risk("aws_db_instance", "update", {}, "LOW")
    delete_risk = assess_risk("aws_db_instance", "delete", {}, "LOW")
    levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert levels.index(delete_risk["risk_level"]) >= levels.index(update_risk["risk_level"])


def test_open_cidr_is_flagged_as_sensitive_field():
    risk = assess_risk(
        "aws_security_group", "update",
        {"cidr_blocks": {"old": ["10.0.0.0/8"], "new": ["0.0.0.0/0"]}},
        "LOW",
    )
    assert risk["touches_sensitive_field"] is True


@pytest.mark.parametrize("filename", [
    "sg_open_ssh.json", "rds_delete.json", "route_table_change.json",
    "iam_policy_widen.json", "log_retention_change.json",
])
def test_all_sample_plans_parse_without_error(filename):
    plan = load_plan(filename)
    changes = parse_resource_changes(plan)
    assert len(changes) >= 1
