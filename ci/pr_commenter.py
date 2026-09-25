"""
Posts (and keeps updated) a blast-radius summary as a single PR comment,
and fails the CI job when the worst risk found is at or above a
configurable threshold -- so this is a gate, not just an FYI.

This is what turns the analyzer from a dashboard you check after the
fact into a pre-deployment check: run it in CI against every changed
Terraform plan for the PR, and it comments the risk (updating its own
prior comment on re-push, like Infracost/Dependabot do) before anyone
clicks "Apply" -- and blocks the merge if branch protection requires
this check to pass. Uses only the standard library + the repo's own
analyzer package, and the built-in GITHUB_TOKEN -- no extra secrets.

Usage (see .github/workflows/blast-radius-check.yml):
    python ci/pr_commenter.py <plan1.json> [plan2.json ...]

Env vars:
    GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH -- set automatically
    inside GitHub Actions.
    CI_FAIL_ON_RISK -- comma-separated risk levels that should fail the
    job. Default: "CRITICAL".
"""

import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Windows terminals default to a codepage that can't encode the emoji
# used in the report; GitHub Actions runners are UTF-8 already, so this
# only matters for local testing on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from db import init_db, SessionLocal
from analyzer.pipeline import analyze_plan

RISK_EMOJI = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
COMMENT_MARKER = "<!-- cloudguard-blast-radius-bot -->"

# Past ~25 boxes a Mermaid graph in a PR comment becomes unreadable; the
# nearest dependents are kept and the rest are summarized in one node.
MAX_GRAPH_NODES = 25

PROVIDERS = {"aws": "AWS", "azurerm": "Azure", "google": "GCP"}

# First matching keyword in the resource type wins.
TYPE_ICONS = [
    (("security_group", "firewall", "network_security"), "🛡️"),
    # Before "instance": aws_db_instance / google_sql_database_instance are databases.
    (("db", "sql", "database", "rds"), "🗄️"),
    (("instance", "virtual_machine", "vm"), "🖥️"),
    (("bucket", "storage", "s3"), "🪣"),
    (("iam", "role", "policy"), "🔑"),
    (("vpc", "subnet", "route", "network", "gateway", "nat"), "🌐"),
    (("log", "cloudwatch", "monitor"), "📜"),
]


def _provider(resource_type: str) -> str:
    return PROVIDERS.get(resource_type.split("_")[0], "")


def _type_icon(resource_type: str) -> str:
    for keywords, emoji in TYPE_ICONS:
        if any(k in resource_type for k in keywords):
            return emoji
    return "📦"


def _mermaid_label(address: str, info: dict, is_changed: bool, action: str) -> str:
    resource_type = info.get("resource_type") or address.split(".")[0]
    short_type = resource_type.split("_", 1)[1] if _provider(resource_type) else resource_type
    name = address.rsplit(".", 1)[-1]

    tags = [_provider(resource_type)] if _provider(resource_type) else []
    if is_changed:
        tags.append(action.upper())
    else:
        tags.append(f"{info['depth']} hop{'s' if info['depth'] > 1 else ''} away")
    if info.get("is_production"):
        tags.append("production")
    if info.get("is_public"):
        tags.append("internet-facing")

    # Mermaid labels are HTML-ish: quotes must be entity-escaped.
    text = f"{_type_icon(resource_type)} {short_type}<br/><b>{name}</b><br/>{' · '.join(tags)}"
    return text.replace('"', "#quot;")


def build_mermaid_graph(result: dict) -> str:
    graph = result["dependency_graph"]
    changed = result["resource_address"]

    ordered = sorted(graph["nodes"], key=lambda n: (graph["nodes"][n]["depth"], n))
    shown = ordered[:MAX_GRAPH_NODES]
    hidden_count = len(ordered) - len(shown)
    ids = {address: f"n{i}" for i, address in enumerate(shown)}

    lines = ["```mermaid", "flowchart LR"]
    for address in shown:
        info = graph["nodes"][address]
        label = _mermaid_label(address, info, address == changed, result["action"])
        if address == changed:
            css = "changed"
        elif info.get("is_production") or info.get("is_public"):
            css = "sensitive"
        else:
            css = "affected"
        lines.append(f'  {ids[address]}["{label}"]:::{css}')

    for upstream, dependent in graph["edges"]:
        if upstream in ids and dependent in ids:
            # Calling out cloud boundaries is the point of a hybrid-cloud graph.
            up_cloud = _provider(graph["nodes"][upstream].get("resource_type", ""))
            down_cloud = _provider(graph["nodes"][dependent].get("resource_type", ""))
            arrow = f" -->|{up_cloud} → {down_cloud}| " if up_cloud and down_cloud and up_cloud != down_cloud else " --> "
            lines.append(f"  {ids[upstream]}{arrow}{ids[dependent]}")

    if hidden_count:
        lines.append(f'  more["…and {hidden_count} more affected resources"]:::more')

    lines += [
        "  classDef changed fill:#d6336c,stroke:#8a2146,color:#fff",
        "  classDef sensitive fill:#fff1e6,stroke:#e8590c,color:#1d1a33",
        "  classDef affected fill:#eef1ff,stroke:#2f5bff,color:#1d1a33",
        "  classDef more fill:#f1f3f5,stroke:#868e96,color:#495057,stroke-dasharray:4 3",
        "```",
    ]
    return "\n".join(lines)


def build_comment_body(all_results: dict[str, list[dict]], fail_levels: set[str]) -> tuple[str, str]:
    """Returns (comment_body, worst_risk_level)."""

    flat = [(plan_file, r) for plan_file, results in all_results.items() for r in results]

    if not flat:
        body = f"{COMMENT_MARKER}\n### 🛡 CloudGuard Blast Radius Check\n\n✅ No effective infrastructure changes detected."
        return body, "LOW"

    worst = max((r["risk_level"] for _, r in flat), key=RISK_ORDER.index)
    gate_failed = worst in fail_levels

    header_icon = "❌" if gate_failed else "✅"
    header_text = f"Blocked: risk reached {worst}" if gate_failed else f"Passed (highest risk: {worst})"

    lines = [
        COMMENT_MARKER,
        f"### 🛡 CloudGuard Blast Radius Check -- {header_icon} {header_text}",
        "",
        f"Analyzed {len(all_results)} plan file(s), {len(flat)} effective change(s).",
        "",
        "| File | Resource | Action | Impact | Risk | Affected | Data Completeness |",
        "|---|---|---|---|---|---|---|",
    ]

    flat.sort(key=lambda item: RISK_ORDER.index(item[1]["risk_level"]), reverse=True)

    for plan_file, r in flat:
        emoji = RISK_EMOJI.get(r["risk_level"], "")
        lines.append(
            f"| `{plan_file}` | `{r['resource_address']}` | {r['action']} | {r['impact_level']} "
            f"| {emoji} {r['risk_level']} | {r['affected_count']} | {r['confidence_score']}% |"
        )

    top_plan_file, top_result = flat[0]
    lines.append("")
    lines.append(f"**In plain English:** {top_result['plain_summary']}")
    lines.append("")

    # One graph per change that reaches other resources, riskiest first and
    # expanded; the rest collapsed so a big PR stays scannable.
    with_dependents = [(f, r) for f, r in flat if r["affected_count"] > 0]
    for i, (plan_file, r) in enumerate(with_dependents):
        emoji = RISK_EMOJI.get(r["risk_level"], "")
        lines.append(
            f"<details{' open' if i == 0 else ''}><summary>🕸️ Dependency graph: <code>{r['resource_address']}</code> "
            f"reaches {r['affected_count']} resource(s) ({emoji} {r['risk_level']})</summary>"
        )
        lines.append("")
        lines.append(build_mermaid_graph(r))
        lines.append("")
        lines.append("🟥 changed · 🟧 production or internet-facing · 🟦 affected · arrows show where the change spreads")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    without = [r["resource_address"] for _, r in flat if r["affected_count"] == 0]
    if without:
        lines.append(f"No other resources depend on: {', '.join(f'`{a}`' for a in without)}")
        lines.append("")
    lines.append(f"<details><summary>Recommendations for the highest-risk change (`{top_result['resource_address']}`)</summary>")
    lines.append("")
    for rec in top_result["recommendations"]:
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append(f"<details><summary>Rollback plan for `{top_result['resource_address']}` (if this needs to be undone)</summary>")
    lines.append("")
    for i, step in enumerate(top_result["rollback_plan"]):
        lines.append(f"{i+1}. {step}")
    lines.append("")
    lines.append("</details>")

    if gate_failed:
        lines.append("")
        lines.append(
            f"🚫 **This check fails because a change reached {worst} risk** "
            f"(gate threshold: {', '.join(sorted(fail_levels, key=RISK_ORDER.index))}). "
            "Review the recommendations above, or have an approver override the branch protection rule if this is intentional."
        )

    return "\n".join(lines), worst


def _find_existing_comment(repo: str, pr_number: int, token: str) -> int | None:
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request) as response:
        comments = json.loads(response.read())

    for comment in comments:
        if COMMENT_MARKER in comment.get("body", ""):
            return comment["id"]
    return None


def post_or_update_comment(body: str):
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]

    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        event = json.load(f)
    pr_number = event["pull_request"]["number"]

    existing_id = _find_existing_comment(repo, pr_number, token)

    if existing_id:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        method = "PATCH"
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        method = "POST"

    payload = json.dumps({"body": body}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(request) as response:
            print(f"{method} comment, status {response.status}")
    except urllib.error.HTTPError as e:
        print(f"Failed to {method} comment: {e.code} {e.read().decode()}", file=sys.stderr)
        raise


def main():
    if len(sys.argv) < 2:
        print("Usage: python ci/pr_commenter.py <plan1.json> [plan2.json ...]", file=sys.stderr)
        sys.exit(1)

    fail_levels = set(
        level.strip().upper()
        for level in os.environ.get("CI_FAIL_ON_RISK", "CRITICAL").split(",")
        if level.strip()
    )

    init_db()
    session = SessionLocal()

    all_results = {}
    for plan_file in sys.argv[1:]:
        with open(plan_file) as f:
            plan = json.load(f)
        all_results[plan_file] = analyze_plan(plan, plan_source=plan_file, session=session)

    body, worst_risk = build_comment_body(all_results, fail_levels)
    print(body)

    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_EVENT_PATH"):
        post_or_update_comment(body)
    else:
        print("\n(GITHUB_TOKEN/GITHUB_EVENT_PATH not set -- printed only, did not post.)")

    if worst_risk in fail_levels:
        print(f"\nFailing CI: worst risk {worst_risk} is in fail-on set {fail_levels}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
