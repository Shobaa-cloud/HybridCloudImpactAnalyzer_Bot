# CloudGuard — Hybrid Cloud Configuration Change Impact Analyzer

Explains the impact of an infrastructure change **before** it's applied,
instead of detecting problems after the fact. Every proposed change goes
through one pipeline:

```
CHANGE -> DEPENDENCIES -> IMPACT -> RISK -> EXPLANATION -> SAFE ACTION / ROLLBACK
```

The blast radius (which other resources a change reaches) is one result of
that pipeline, not the whole product: the output is a risk verdict, a
plain-English explanation, recommendations, and a rollback plan, delivered as
a comment on the pull request that proposes the change.

**No credentials required.** Core impact analysis operates on Terraform plan
data and does not require AWS (or Azure/GCP) credentials. It runs inside the
user's own CI pipeline, so no third party ever holds access to their cloud
accounts. (The optional live AWS sync described below is the only feature
that uses credentials, and only read-only ones.)

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
- **Genuinely multi-cloud, not "hybrid" in name only.** The severity rules and
  public-exposure detection recognize AWS, Azure, *and* GCP resource shapes
  side by side (`analyzer/risk_engine.py`, `analyzer/graph_builder.py`) —
  `samples/multi_cloud_migration.json` proves a single blast-radius trace
  crossing all three providers in one plan (an Azure firewall rule change
  cascades to an Azure VM, which cascades to a GCP storage bucket). Static
  scanners such as Checkov and tfsec also cover all three clouds, but they
  check each resource against policy rules in isolation; they don't trace how
  a change cascades through dependent resources across providers.
- **Tells you how to undo it, before you apply it.** `analyzer/rollback_generator.py`
  computes the exact rollback steps for every change up front — not
  something you improvise mid-incident.
- **Speaks to non-engineers too.** `analyzer/summary_generator.py` produces a
  plain-English paragraph above all the technical detail, so a manager or a
  client can understand the risk without knowing what a security group is.
- **Honest about what "confidence" means.** The score shown is data
  completeness (how much of the plan is knowable before apply), not a vague
  "safety" number inflated by how often we've seen a pattern before — a
  deliberate fix after finding that conflation misleading during review.
- **Impact score is relative, not a probability.** The 0–100 impact score
  (`analyzer/impact_engine.py`) is a project-defined comparative measure:
  each affected resource contributes a weight (base + production tag +
  internet-facing), divided by (1 + how many hops away it is), and the sum is
  scaled by 12 and capped at 100. It ranks changes against each other; a
  score of 72 does **not** mean a 72% chance of failure.
- **Ships as a CI/CD gate, not a dashboard you have to remember to check.**
  `.github/workflows/blast-radius-check.yml` + `ci/pr_commenter.py` post the
  blast-radius report as a PR comment automatically, and **fail the check**
  (blocking merge under branch protection) when risk reaches CRITICAL —
  closer to what companies actually build in-house for this problem.

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
| `multi_cloud_migration.json` | Azure firewall rule opened, cascades to an Azure VM then a GCP bucket | CRITICAL |

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

## Optional: live AWS state sync (read-only, zero billable resources)

If you want the dashboard to already know what your AWS account currently
looks like — instead of only analyzing an uploaded Terraform plan — you can
connect a real (free-tier) AWS account in a way designed to create **zero
new billable resources**: no S3 bucket, no Lambda, no CloudTrail Trail, no
EventBridge rule. It only makes 3 read-only "describe" API calls (which AWS
does not charge for), and only when you explicitly trigger it — never on a
schedule.

**Setup:**
1. In the AWS Console, create an IAM user with **programmatic access only**
   (no console password).
2. Attach the policy in [`iam-readonly-policy.json`](iam-readonly-policy.json)
   to that user — it grants *exactly* `DescribeSecurityGroups`,
   `DescribeInstances`, and `DescribeDBInstances` and nothing else. This
   means even a bug in this code cannot create or change anything: AWS
   itself would reject any other API call with `AccessDenied`.
3. Add the resulting access key to your `.env`:
   ```
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_DEFAULT_REGION=us-east-1
   ```
4. **Strongly recommended regardless:** in AWS Billing → Budgets, create a
   $0 (zero-spend) budget alert. It's itself free and emails you the instant
   any charge appears — a safety net independent of anything in this repo.
5. Run `python sync_current_state.py` whenever you want to refresh the
   snapshot — it saves to `current_state_snapshot.json` (gitignored, since
   it contains your real resource IDs/tags) and never runs on its own.
   The dashboard's "Live AWS Snapshot" panel shows the same sync, with a
   "Sync Now" button, and displays how long ago it last ran.

This is separate from `analyzer/aws_enrichment.py`, which uses the same
read-only philosophy to enrich a *plan's* graph with live tag data when
`ENABLE_AWS_ENRICHMENT=true`. Neither of these builds the full CloudTrail /
AWS Config / EventBridge / Lambda / SNS pipeline from the original project
proposal — that architecture requires provisioning a CloudTrail Trail (which
needs an S3 bucket, only free for an account's first 12 months) and was
deliberately not built here, given a zero-billing-risk requirement for this
project.

## Tests

```bash
python -m pytest tests/ -q
```

`tests/fixtures/real_terraform_module_plan.json` is not hand-written like the
`samples/` files -- it's the actual, unedited output of a real `terraform
plan`, run against the real HashiCorp AWS provider, pointed at
[moto](https://github.com/getmoto/moto)'s local fake-AWS server (`moto[server]`,
zero cost, zero real AWS account involved). This exists specifically to prove
the parser handles genuine Terraform-generated JSON, not just JSON shaped to
fit our own assumptions.

That exercise caught a real bug: the config used to generate this fixture
puts its security group and EC2 instance inside a Terraform **module**
(`module "app" { ... }`) rather than the root module. Before fixing
`plan_parser.py`, running this exact real plan through the analyzer reported
**0 affected resources** for the security group change, despite the EC2
instance genuinely using it via `vpc_security_group_ids` — because the
parser only read `configuration.root_module.resources`, never recursing into
`module_calls`. `parse_dependency_references` now walks nested modules
recursively; `test_module_nested_dependency_is_traced` locks in the fix
against this same real fixture, not a synthetic one.

## What changed from the original prototype

The original version compared two hand-written JSON files against a
hardcoded 4-resource dependency chain, and rendered a dashboard with
hardcoded numbers (`91%`, `7 affected resources`) that the backend never
actually computed. This rebuild replaces that with a real Terraform-plan
parser, an actual NetworkX dependency graph, a weighted blast-radius model, a
general risk matrix (the old version had exactly one rule, for
`allowed_ip`), and a dashboard wired end-to-end to a real API and database.
