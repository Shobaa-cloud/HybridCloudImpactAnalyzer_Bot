import json
import os

import pytest

from analyzer.plan_parser import parse_resource_changes, parse_dependency_references
from analyzer.graph_builder import build_dependency_graph
from analyzer.impact_engine import assess_impact
from analyzer.risk_engine import assess_risk
from analyzer.rollback_generator import generate_rollback_plan
from analyzer.summary_generator import generate_plain_summary

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_plan(filename):
    with open(os.path.join(SAMPLES_DIR, filename)) as f:
        return json.load(f)


def load_fixture(filename):
    with open(os.path.join(FIXTURES_DIR, filename)) as f:
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
    "iam_policy_widen.json", "log_retention_change.json", "multi_cloud_migration.json",
])
def test_all_sample_plans_parse_without_error(filename):
    plan = load_plan(filename)
    changes = parse_resource_changes(plan)
    assert len(changes) >= 1


def test_multi_cloud_blast_radius_crosses_providers():
    """
    An Azure network security rule change should cascade to an Azure VM
    and then to a GCP storage bucket -- proving the graph genuinely
    works across providers in one plan, not just within AWS.
    """
    plan = load_plan("multi_cloud_migration.json")
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)
    impact = assess_impact(graph, "azurerm_network_security_rule.dr_rdp_rule")

    assert "azurerm_linux_virtual_machine.dr_app" in impact["affected_resources"]
    assert "google_storage_bucket.backup_archive" in impact["affected_resources"]
    # The unrelated AWS instance in the same plan must NOT be swept in.
    assert "aws_instance.primary_app" not in impact["affected_resources"]


def test_multi_cloud_open_rdp_rule_is_critical():
    changes = parse_resource_changes(load_plan("multi_cloud_migration.json"))
    rule_change = next(c for c in changes if c.address == "azurerm_network_security_rule.dr_rdp_rule")
    assert rule_change.changed_fields["source_address_prefix"]["new"] == "*"

    risk = assess_risk(
        resource_type=rule_change.resource_type,
        action=rule_change.action,
        changed_fields=rule_change.changed_fields,
        impact_level="MEDIUM",
    )
    assert risk["risk_level"] == "CRITICAL"
    assert risk["touches_sensitive_field"] is True


def test_rollback_plan_for_update_reverses_each_changed_field():
    steps = generate_rollback_plan(
        "aws_security_group.web_sg", "update",
        {"cidr_blocks": {"old": ["10.0.0.0/8"], "new": ["0.0.0.0/0"]}},
    )
    assert any("10.0.0.0/8" in step for step in steps)


def test_rollback_plan_for_delete_has_no_partial_undo():
    steps = generate_rollback_plan("aws_db_instance.app_db", "delete", {})
    assert any("no longer exists" in step or "recreate" in step for step in steps)


def test_plain_summary_mentions_affected_resources():
    summary = generate_plain_summary(
        resource_address="aws_security_group.web_sg",
        resource_type="aws_security_group",
        action="update",
        affected_count=2,
        affected_resources=["aws_instance.web", "aws_db_instance.app_db"],
        risk_level="CRITICAL",
    )
    assert "2 other connected resource" in summary
    assert "instance" in summary.lower()


def test_module_nested_resources_are_addressed_correctly():
    """
    Real fixture: generated by actually running `terraform plan` (with
    the real AWS provider, against a moto-mocked endpoint) on a config
    where a security group and an EC2 instance live inside a module
    call, not the root module. Verifies our parser correctly picks up
    module-nested resources by their real Terraform address.
    """
    plan = load_fixture("real_terraform_module_plan.json")
    changes = parse_resource_changes(plan)
    addresses = {c.address for c in changes}
    assert addresses == {"module.app.aws_security_group.web_sg", "module.app.aws_instance.web"}


def test_module_nested_dependency_is_traced():
    """
    The real regression test: before the module-traversal fix, this
    exact real plan reported 0 affected resources for the security
    group, even though the EC2 instance genuinely uses it via
    vpc_security_group_ids. Confirmed by actually running the old code
    against this exact fixture before fixing plan_parser.py.
    """
    plan = load_fixture("real_terraform_module_plan.json")
    references = parse_dependency_references(plan)
    graph = build_dependency_graph(plan, references)

    impact = assess_impact(graph, "module.app.aws_security_group.web_sg")
    assert impact["affected_count"] == 1
    assert "module.app.aws_instance.web" in impact["affected_resources"]


def test_resource_type_from_module_address_is_correct():
    from analyzer.summary_generator import _resource_type_from_address
    assert _resource_type_from_address("module.app.aws_instance.web") == "aws_instance"
    assert _resource_type_from_address("aws_instance.web") == "aws_instance"


def test_dependency_graph_keeps_every_branch():
    # dependency_chain only follows the deepest path; the graph for the PR
    # comment must keep both branches out of web_sg (db and instance).
    plan = load_plan("sg_open_ssh.json")
    graph = build_dependency_graph(plan, parse_dependency_references(plan))
    impact = assess_impact(graph, "aws_security_group.web_sg")

    edges = impact["dependency_graph"]["edges"]
    assert ["aws_security_group.web_sg", "aws_db_instance.app_db"] in edges
    assert ["aws_security_group.web_sg", "aws_instance.web"] in edges
    assert ["aws_instance.web", "aws_lb_target_group_attachment.web_attach"] in edges
    assert impact["dependency_graph"]["nodes"]["aws_lb_target_group_attachment.web_attach"]["depth"] == 2


def test_pr_comment_mermaid_graph_marks_cloud_boundary():
    from ci.pr_commenter import build_mermaid_graph

    plan = load_plan("multi_cloud_migration.json")
    graph = build_dependency_graph(plan, parse_dependency_references(plan))
    changed = "azurerm_network_security_rule.dr_rdp_rule"
    impact = assess_impact(graph, changed)

    mermaid = build_mermaid_graph({
        "resource_address": changed,
        "action": "update",
        "dependency_graph": impact["dependency_graph"],
    })
    assert mermaid.startswith("```mermaid\nflowchart LR")
    assert "|Azure → GCP|" in mermaid
    assert ":::changed" in mermaid
    assert "primary_app" not in mermaid  # unrelated AWS instance stays out
