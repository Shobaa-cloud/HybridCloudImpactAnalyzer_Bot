import json
import os

from flask import Flask, render_template, request, jsonify, Response

from db import init_db, SessionLocal
from db.models import Analysis
from analyzer.pipeline import analyze_plan
from analyzer.history import record_outcome, find_similar_past_changes, serialize_similar_change
from analyzer.live_state import fetch_live_snapshot, save_snapshot, load_snapshot
from analyzer.rollback_generator import generate_rollback_plan
from analyzer.summary_generator import generate_plain_summary

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")

app = Flask(__name__)
init_db()


def _analysis_to_dict(analysis: Analysis, session=None) -> dict:
    similar = []
    if session is not None:
        similar_rows = find_similar_past_changes(
            session, analysis.resource_type, analysis.change_action, exclude_id=analysis.id
        )
        similar = [serialize_similar_change(a) for a in similar_rows]

    changed_fields = json.loads(analysis.changed_attributes or "{}")
    affected_resources = json.loads(analysis.affected_resources or "[]")

    return {
        "id": analysis.id,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "plan_source": analysis.plan_source,
        "resource_address": analysis.resource_address,
        "resource_type": analysis.resource_type,
        "change_action": analysis.change_action,
        "changed_fields": changed_fields,
        "affected_count": analysis.affected_count,
        "affected_resources": affected_resources,
        "impact_level": analysis.impact_level,
        "risk_level": analysis.risk_level,
        "confidence_score": analysis.confidence_score,
        "dependency_chain": json.loads(analysis.dependency_path or "[]"),
        "recommendations": json.loads(analysis.recommendations or "[]"),
        "rollback_plan": generate_rollback_plan(
            resource_address=analysis.resource_address,
            action=analysis.change_action,
            changed_fields=changed_fields,
        ),
        "plain_summary": generate_plain_summary(
            resource_address=analysis.resource_address,
            resource_type=analysis.resource_type,
            action=analysis.change_action,
            affected_count=analysis.affected_count,
            affected_resources=affected_resources,
            risk_level=analysis.risk_level,
        ),
        "similar_past_changes": similar,
    }


@app.route("/")
def dashboard():
    session = SessionLocal()
    latest = session.query(Analysis).order_by(Analysis.created_at.desc()).first()
    sample_files = sorted(os.listdir(SAMPLES_DIR)) if os.path.isdir(SAMPLES_DIR) else []
    return render_template(
        "dashboard.html",
        latest=_analysis_to_dict(latest, session) if latest else None,
        sample_files=sample_files,
    )


@app.route("/api/samples")
def list_samples():
    sample_files = sorted(os.listdir(SAMPLES_DIR)) if os.path.isdir(SAMPLES_DIR) else []
    return jsonify(sample_files)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    session = SessionLocal()

    if "plan_file" in request.files and request.files["plan_file"].filename:
        upload = request.files["plan_file"]
        plan = json.load(upload.stream)
        plan_source = upload.filename
    elif request.form.get("sample_name"):
        sample_name = request.form["sample_name"]
        sample_path = os.path.join(SAMPLES_DIR, sample_name)
        if not os.path.abspath(sample_path).startswith(os.path.abspath(SAMPLES_DIR)):
            return jsonify({"error": "invalid sample name"}), 400
        with open(sample_path) as f:
            plan = json.load(f)
        plan_source = sample_name
    else:
        return jsonify({"error": "provide plan_file or sample_name"}), 400

    results = analyze_plan(plan, plan_source=plan_source, session=session)
    return jsonify(results)


@app.route("/api/analyses")
def api_history():
    session = SessionLocal()
    analyses = session.query(Analysis).order_by(Analysis.created_at.desc()).limit(50).all()
    return jsonify([_analysis_to_dict(a) for a in analyses])


@app.route("/api/analyses/<int:analysis_id>")
def api_analysis_detail(analysis_id):
    session = SessionLocal()
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        return jsonify({"error": "not found"}), 404
    return jsonify(_analysis_to_dict(analysis, session))


@app.route("/api/analyses/<int:analysis_id>/outcome", methods=["POST"])
def api_record_outcome(analysis_id):
    session = SessionLocal()
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        return jsonify({"error": "not found"}), 404

    payload = request.get_json(force=True)
    outcome = record_outcome(
        session, analysis_id,
        outcome_text=payload.get("outcome_text", ""),
        was_incident=bool(payload.get("was_incident", False)),
    )
    return jsonify({"id": outcome.id, "outcome_text": outcome.outcome_text})


@app.route("/api/analyses/<int:analysis_id>/report")
def api_download_report(analysis_id):
    session = SessionLocal()
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        return jsonify({"error": "not found"}), 404

    data = _analysis_to_dict(analysis)
    lines = [
        "HYBRID CLOUD CONFIGURATION CHANGE IMPACT REPORT",
        "=" * 50,
        "",
        "Summary (plain English):",
        f"  {data['plain_summary']}",
        "",
        f"Resource:            {data['resource_address']}",
        f"Change Action:       {data['change_action']}",
        f"Changed Fields:      {', '.join(data['changed_fields']) or '(none)'}",
        f"Affected Resources:  {data['affected_count']}",
        f"Impact Level:        {data['impact_level']}",
        f"Risk Level:          {data['risk_level']}",
        f"Data Completeness:   {data['confidence_score']}%",
        f"Dependency Chain:    {' -> '.join(data['dependency_chain'])}",
        "",
        "Recommendations:",
    ] + [f"  - {r}" for r in data["recommendations"]] + [
        "",
        "Rollback Plan (if this change needs to be undone):",
    ] + [f"  {i+1}. {step}" for i, step in enumerate(data["rollback_plan"])]

    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=impact-report-{analysis_id}.txt"},
    )


@app.route("/api/current-state")
def api_current_state():
    snapshot = load_snapshot()
    if snapshot is None:
        return jsonify({"synced": False})
    counts = {}
    for resource in snapshot["resources"].values():
        counts[resource["resource_type"]] = counts.get(resource["resource_type"], 0) + 1
    return jsonify({
        "synced": True,
        "synced_at": snapshot["synced_at"],
        "region": snapshot["region"],
        "counts": counts,
        "errors": snapshot.get("errors", []),
    })


@app.route("/api/sync-aws-state", methods=["POST"])
def api_sync_aws_state():
    """
    Triggers the same 3 read-only AWS calls as sync_current_state.py.
    Only runs when a human clicks the button -- never on a schedule.
    """
    try:
        snapshot = fetch_live_snapshot()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    if not snapshot["resources"] and snapshot["errors"]:
        return jsonify({"error": "No resources fetched", "details": snapshot["errors"]}), 502

    save_snapshot(snapshot)
    counts = {}
    for resource in snapshot["resources"].values():
        counts[resource["resource_type"]] = counts.get(resource["resource_type"], 0) + 1

    return jsonify({
        "synced": True,
        "synced_at": snapshot["synced_at"],
        "region": snapshot["region"],
        "counts": counts,
        "errors": snapshot["errors"],
    })


if __name__ == "__main__":
    app.run(debug=True)
