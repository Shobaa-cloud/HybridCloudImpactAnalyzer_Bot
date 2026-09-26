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

# Windows terminals default to a codepage that can't encode characters
# such as the arrows used in the report; GitHub Actions runners are UTF-8
# already, so this only matters for local testing on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from db import init_db, SessionLocal
from analyzer.pipeline import analyze_plan

RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
COMMENT_MARKER = "<!-- cloudguard-blast-radius-bot -->"

# Past ~25 boxes a Mermaid graph in a PR comment becomes unreadable; the
# nearest dependents are kept and the rest are summarized in one node.
MAX_GRAPH_NODES = 25

PROVIDERS = {"aws": "AWS", "azurerm": "Azure", "google": "GCP"}


def _provider(resource_type: str) -> str:
    return PROVIDERS.get(resource_type.split("_")[0], "")


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
    text = f"<b>{name}</b><br/>{short_type}<br/><small>{' · '.join(tags)}</small>"
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
        lines.append(f'  more["and {hidden_count} more affected resources"]:::more')

    lines += [
        "  classDef changed fill:#b42318,stroke:#7a271a,color:#ffffff",
        "  classDef sensitive fill:#fff4ed,stroke:#c4320a,color:#1d2939",
        "  classDef affected fill:#f2f4f7,stroke:#475467,color:#1d2939",
        "  classDef more fill:#ffffff,stroke:#98a2b3,color:#475467,stroke-dasharray:4 3",
        "```",
    ]
    return "\n".join(lines)


def _status_callout(worst: str, gate_failed: bool, fail_levels: set[str]) -> list[str]:
    """A GitHub alert block: a coloured box with GitHub's own icon, no emoji needed."""
    gate = ", ".join(sorted(fail_levels, key=RISK_ORDER.index)) or "none"
    if gate_failed:
        return [
            "> [!CAUTION]",
            f"> **Merge blocked.** The highest risk in this pull request is **{worst}**, "
            f"which meets the merge gate ({gate}). Review the change details below, or have an "
            "approver override branch protection if this is intentional.",
        ]
    kind = "TIP" if worst == "LOW" else "WARNING" if worst == "HIGH" else "NOTE"
    return [
        f"> [!{kind}]",
        f"> **Passed.** The highest risk in this pull request is **{worst}** (merge gate: {gate}).",
    ]


def _change_details(plan_file: str, r: dict, expanded: bool) -> list[str]:
    reach = r["affected_count"]
    reach_text = f"reaches {reach} resource{'s' if reach != 1 else ''}" if reach else "no dependents"
    lines = [
        f"<details{' open' if expanded else ''}>",
        f"<summary><b>{r['risk_level']}</b> &nbsp;·&nbsp; <code>{r['resource_address']}</code>"
        f" &nbsp;·&nbsp; {r['action']} &nbsp;·&nbsp; {reach_text}</summary>",
        "",
        f"**Summary.** {r['plain_summary']}",
        "",
        f"Plan file `{plan_file}` · Impact {r['impact_level'].capitalize()} "
        f"(score {r['impact_score']}/100) · Data completeness {r['confidence_score']}%",
        "",
    ]
    if reach:
        lines += [
            "**Dependency graph**",
            "",
            build_mermaid_graph(r),
            "",
            "<sub>Red: changed resource. Orange: production or internet-facing. "
            "Grey: other affected resources. Arrows point in the direction the change spreads.</sub>",
            "",
        ]
    else:
        lines += ["No other resources depend on this resource, so the change stays contained.", ""]

    lines += ["**Recommendations**", ""]
    lines += [f"- {rec}" for rec in r["recommendations"]]
    lines += ["", "**Rollback plan**", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(r["rollback_plan"], start=1)]
    lines += ["", "</details>", ""]
    return lines


def build_comment_body(all_results: dict[str, list[dict]], fail_levels: set[str]) -> tuple[str, str]:
    """Returns (comment_body, worst_risk_level)."""

    flat = [(plan_file, r) for plan_file, results in all_results.items() for r in results]

    if not flat:
        body = "\n".join([
            COMMENT_MARKER,
            "## CloudGuard Blast Radius Check",
            "",
            "> [!TIP]",
            "> **Passed.** No effective infrastructure changes were found in this pull request.",
        ])
        return body, "LOW"

    worst = max((r["risk_level"] for _, r in flat), key=RISK_ORDER.index)
    gate_failed = worst in fail_levels
    flat.sort(key=lambda item: RISK_ORDER.index(item[1]["risk_level"]), reverse=True)

    counts = [
        f"{sum(1 for _, r in flat if r['risk_level'] == level)} {level.lower()}"
        for level in reversed(RISK_ORDER)
        if any(r["risk_level"] == level for _, r in flat)
    ]
    files = len(all_results)

    lines = [
        COMMENT_MARKER,
        "## CloudGuard Blast Radius Check",
        "",
        *_status_callout(worst, gate_failed, fail_levels),
        "",
        f"**{len(flat)} change{'s' if len(flat) != 1 else ''}** in {files} plan file{'s' if files != 1 else ''}: "
        + ", ".join(counts) + ".",
        "",
        "| Risk | Resource | Action | Impact | Reaches |",
        "|:--|:--|:--|:--|--:|",
    ]
    for _, r in flat:
        lines.append(
            f"| **{r['risk_level']}** | `{r['resource_address']}` | {r['action']} "
            f"| {r['impact_level'].capitalize()} | {r['affected_count']} |"
        )

    lines += [
        "",
        "### Change details",
        "",
        "<sub>Highest risk first. Expand a change for its graph, recommendations and rollback plan.</sub>",
        "",
    ]
    for i, (plan_file, r) in enumerate(flat):
        lines += _change_details(plan_file, r, expanded=(i == 0))

    lines += [
        "---",
        "<sub>CloudGuard · pre-deployment blast-radius analysis of the Terraform plan · "
        "no cloud credentials used · this comment updates on every push</sub>",
    ]
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
