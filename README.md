# CloudGuard — Hybrid Cloud Configuration Change Impact Analyzer

Predicts the blast radius and risk of an infrastructure change **before** it's
applied, instead of detecting problems after the fact.

## The problem this solves

AWS Config and CloudTrail (and their Azure/GCP equivalents) tell you *what*
changed, after it already happened. They don't tell you *what else breaks*.
Most config-drift tools work the same way: react to a change that already
landed. This project instead sits **in front of the deploy**: point it at a
Terraform plan, and it tells you the blast radius before anyone clicks
"Apply" — as a local dashboard, a CLI report, or an automatic comment on a
GitHub pull request.

## What makes this different from existing tools

- **Pre-deployment, not post-hoc.** `driftctl`, AWS Config, and CloudTrail-based
  tools all detect changes that have already been applied. This analyzes a
  `terraform plan` before it's applied.
- **Real dependency graph, not a resource count.** Impact is computed with
  NetworkX over the actual reference graph Terraform itself uses to order
  applies (`configuration.root_module.resources[].expressions[].references`),
  weighted by how many hops away a resource is and whether it's tagged
  production or internet-facing — not just "how many resources point at this
  one."
- **Provider-agnostic ("hybrid cloud" for real).** Terraform plan JSON is the
  same format for AWS, Azure, and GCP resources, so the core pipeline isn't
  AWS-only, unlike a CloudTrail/Config-based design.
- **Learns from history.** Every analysis is persisted; risk assessments for a
  resource type + action get more confident as more real outcomes are
  recorded (`/api/analyses/<id>/outcome`), instead of a fixed confidence
  number.
- **Ships as a CI/CD gate.** `.github/workflows/blast-radius-check.yml` +
  `ci/pr_commenter.py` post the blast-radius report as a PR comment
  automatically — closer to what companies actually build in-house for this
  problem than a dashboard you have to remember to check.

## Architecture

```
Terraform plan JSON
        │
        ▼
analyzer/plan_parser.py       -- Module 1: Configuration Change Detection
        │  (resource_changes, before/after diff, reference graph)
        ▼
analyzer/graph_builder.py     -- Module 2: Resource Dependency Analysis
        │  (NetworkX DiGraph + optional analyzer/aws_enrichment.py via boto3)
        ▼
analyzer/impact_engine.py     -- Module 3: Impact Assessment
        │  (blast radius: reachability + depth decay + criticality weight)
        ▼
analyzer/risk_engine.py       -- Module 4: Risk Assessment
        │  (resource-type severity x action x sensitive-field detection)
        ▼
analyzer/recommendation_engine.py + analyzer/history.py   -- Module 5
        │  (rule-based recommendations, MySQL-backed similar-past-changes)
        ▼
Flask API (app.py) + dashboard (templates/, static/) ── or ── CLI (cli.py) ── or ── GitHub PR comment (ci/)
```

Each module above maps directly to the five modules in the project report.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # defaults to a local SQLite file, zero setup
python seed_history.py        # seeds a few historical incidents for the demo
python app.py                 # http://127.0.0.1:5000
```

To use the MySQL setup described in the project report instead of the
zero-config SQLite default:

```bash
mysql -u root -p < schema.sql
# then in .env:
# DATABASE_URL=mysql+mysqlconnector://root:password@localhost:3306/hybrid_cloud_analyzer
```

### CLI (no web server needed)

```bash
python cli.py analyze samples/sg_open_ssh.json
```

### Sample plans

`samples/` has five realistic `terraform show -json` fixtures spanning the
risk spectrum, so the tool is fully demoable without a live cloud account or
Terraform installed:

| File | Scenario | Typical risk |
|---|---|---|
| `sg_open_ssh.json` | Security group SSH opened to 0.0.0.0/0, fans out to an EC2 instance and RDS database | CRITICAL |
| `rds_delete.json` | Production RDS instance replaced, made publicly accessible | CRITICAL |
| `iam_policy_widen.json` | IAM policy widened to `Action: "*"` | CRITICAL |
| `route_table_change.json` | Production route table repointed to a different NAT gateway | HIGH |
| `log_retention_change.json` | CloudWatch log retention changed, no dependents | LOW |

To analyze a real plan instead: `terraform show -json tfplan > my_plan.json`,
then feed `my_plan.json` to the CLI, the dashboard's upload box, or the CI
workflow.

### CI: blast-radius PR bot (the actual gate, not just a dashboard)

Push this repo to GitHub (already configured — see `.github/workflows/`) and
open a PR that edits a file under `samples/`. The workflow:

1. Analyzes every changed plan file and posts **one** comment on the PR with
   a risk table and recommendations — re-pushing to the same PR updates that
   comment in place instead of spamming new ones (same UX as Infracost/
   Dependabot bots).
2. **Fails the check** (red X on the PR) if any change reaches CRITICAL risk,
   controlled by `CI_FAIL_ON_RISK` in the workflow file. With a branch
   protection rule requiring this check, that actually blocks the merge
   button, not just an FYI comment. Loosen or tighten the threshold there
   (e.g. `"HIGH,CRITICAL"`, or `""` to never block).

Try it locally first, no GitHub needed:
```bash
python ci/pr_commenter.py samples/sg_open_ssh.json      # exits 1 (CRITICAL)
python ci/pr_commenter.py samples/log_retention_change.json   # exits 0 (LOW)
```

## Optional: live AWS enrichment

`analyzer/aws_enrichment.py` uses boto3 to pull real security group / EC2 tag
data for resources referenced in a plan, when `ENABLE_AWS_ENRICHMENT=true`
and AWS credentials are configured. It's off by default so the tool works
fully offline; this is the natural extension point for the CloudTrail /
AWS Config / EventBridge / Lambda / SNS live-monitoring pipeline described in
the original project proposal, if you get access to an AWS account for a
later phase. (Not exercised against a live account in this build.)

## Tests

```bash
python -m pytest tests/ -q
```

## What changed from the original prototype

The original version compared two hand-written JSON files against a
hardcoded 4-resource dependency chain, and rendered a dashboard with
hardcoded numbers (`91%`, `7 affected resources`) that the backend never
actually computed. This rebuild replaces that with a real Terraform-plan
parser, an actual NetworkX dependency graph, a weighted blast-radius model, a
general risk matrix (the old version had exactly one rule, for
`allowed_ip`), and a dashboard wired end-to-end to a real API and database.
