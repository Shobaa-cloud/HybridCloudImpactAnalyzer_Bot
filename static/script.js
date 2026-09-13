// ===============================
// CLOUDGUARD DASHBOARD
// Renders real analysis results from the Flask API. Nothing here is
// hardcoded -- every value comes from /api/analyze or the initial
// server-rendered analysis.
// ===============================

let currentAnalysisId = null;
let currentAllResults = [];

const RESOURCE_ICON_BY_TYPE = {
    aws_security_group: "♢",
    aws_instance: "▣",
    aws_db_instance: "▤",
    aws_lambda_function: "▥",
    aws_route_table: "◈",
    aws_iam_role_policy: "◎",
};

function badgeClass(level) {
    return { LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical" }[level] || "low";
}

function setBadge(elementId, level) {
    const el = document.getElementById(elementId);
    el.textContent = level;
    el.className = badgeClass(level);
}

function renderDependencyChain(chain) {
    const container = document.getElementById("dependency-chain");
    container.innerHTML = "";

    if (!chain || chain.length === 0) {
        container.innerHTML = '<div class="dependency-note">No dependency chain.</div>';
        return;
    }

    chain.forEach((address, index) => {
        const [resourceType, name] = address.includes(".") ? address.split(/\.(.+)/) : [address, ""];
        const icon = RESOURCE_ICON_BY_TYPE[resourceType] || "▣";

        const node = document.createElement("div");
        node.className = "resource" + (index === 0 ? " security" : index === chain.length - 1 ? " end" : " ec2");
        node.innerHTML = `
            <div class="resource-icon">${icon}</div>
            <strong>${resourceType.replace("aws_", "")}</strong>
            <span>${name}</span>
        `;
        container.appendChild(node);

        if (index < chain.length - 1) {
            const arrow = document.createElement("div");
            arrow.className = "arrow";
            arrow.textContent = "→";
            container.appendChild(arrow);
        }
    });
}

function renderHistory(similarChanges) {
    const body = document.getElementById("history-body");
    body.innerHTML = "";

    if (!similarChanges || similarChanges.length === 0) {
        body.innerHTML = '<tr><td colspan="4">No similar past changes yet -- this looks like the first time this resource type/action combination was analyzed.</td></tr>';
        return;
    }

    similarChanges.forEach(change => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${change.resource_address}</td>
            <td>${change.change_action}</td>
            <td><b class="${badgeClass(change.risk_level)}">${change.risk_level}</b></td>
            <td>${change.outcome}</td>
        `;
        body.appendChild(row);
    });
}

function renderResult(result) {
    if (!result) return;

    currentAnalysisId = result.id;

    const action = result.change_action || result.action;
    const affectedResources = result.affected_resources || [];

    document.getElementById("status-title").textContent = "Analysis completed successfully";
    document.getElementById("status-subtitle").textContent =
        `Resource: ${result.resource_address} (${result.plan_source || "uploaded plan"})`;

    document.getElementById("metric-risk").textContent = result.risk_level;
    document.getElementById("metric-confidence").textContent = `${result.confidence_score}%`;
    document.getElementById("metric-affected").textContent = result.affected_count;
    document.getElementById("metric-affected-sub").textContent =
        `Reachable in the dependency graph.`;
    document.getElementById("metric-similar").textContent =
        (result.similar_past_changes || []).length;

    document.getElementById("detail-action").textContent = action;
    document.getElementById("detail-resource").textContent = result.resource_address;
    document.getElementById("detail-type").textContent = result.resource_type || result.resource_address.split(".")[0];
    document.getElementById("detail-fields").textContent =
        Object.keys(result.changed_fields || {}).join(", ") || "(none)";
    document.getElementById("detail-source").textContent = result.plan_source || "--";

    renderDependencyChain(result.dependency_chain);

    setBadge("impact-level-badge", result.impact_level);
    setBadge("impact-risk-badge", result.risk_level);
    const sensitiveBadge = document.getElementById("impact-sensitive-badge");
    const touchesSensitive = (result.recommendations || []).some(r => r.toLowerCase().includes("restrict") || r.toLowerCase().includes("public"));
    sensitiveBadge.textContent = touchesSensitive ? "YES" : "NO";
    sensitiveBadge.className = touchesSensitive ? "high" : "low";

    document.getElementById("impact-score").textContent = `${result.impact_score ?? "--"}`;

    renderHistory(result.similar_past_changes);

    const list = document.getElementById("recommendations-list");
    list.innerHTML = "";
    (result.recommendations || []).forEach(rec => {
        const li = document.createElement("li");
        li.textContent = rec;
        list.appendChild(li);
    });

    document.getElementById("warning-headline").textContent =
        result.risk_level === "CRITICAL" || result.risk_level === "HIGH"
            ? "REVIEW BEFORE DEPLOYMENT"
            : "SAFE TO PROCEED WITH STANDARD REVIEW";
}


// ===============================
// INITIAL LOAD
// ===============================

const initialDataEl = document.getElementById("initial-analysis");
if (initialDataEl) {
    try {
        const initial = JSON.parse(initialDataEl.textContent);
        if (initial) renderResult(initial);
    } catch (e) {
        console.warn("No initial analysis to render.");
    }
}


// ===============================
// ANALYZE FORM
// ===============================

const analyzeForm = document.getElementById("analyze-form");
const analyzeStatus = document.getElementById("analyze-status");

analyzeForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const fileInput = document.getElementById("plan-file");
    const sampleSelect = document.getElementById("sample-select");

    const formData = new FormData();
    if (fileInput.files.length > 0) {
        formData.append("plan_file", fileInput.files[0]);
    } else {
        formData.append("sample_name", sampleSelect.value);
    }

    analyzeStatus.textContent = "Analyzing...";

    try {
        const response = await fetch("/api/analyze", { method: "POST", body: formData });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || "Analysis failed");
        }

        const results = await response.json();
        currentAllResults = results;

        if (results.length === 0) {
            analyzeStatus.textContent = "No effective changes found in this plan.";
            return;
        }

        renderResult(results[0]);
        analyzeStatus.textContent = results.length > 1
            ? `Showing highest-risk change. ${results.length - 1} other change(s) also analyzed in this plan.`
            : "Analysis complete.";

    } catch (error) {
        analyzeStatus.textContent = `Error: ${error.message}`;
    }
});


// ===============================
// DOWNLOAD REPORT
// ===============================

document.getElementById("download-btn").addEventListener("click", function () {
    if (!currentAnalysisId) {
        alert("Run an analysis first.");
        return;
    }
    window.location.href = `/api/analyses/${currentAnalysisId}/report`;
});


// ===============================
// SHARE REPORT
// ===============================

document.getElementById("share-btn").addEventListener("click", async function () {
    if (!currentAnalysisId || currentAllResults.length === 0) {
        const resourceEl = document.getElementById("detail-resource");
        alert("Run an analysis first.");
        return;
    }

    const result = currentAllResults.find(r => r.id === currentAnalysisId) || currentAllResults[0];
    const summary = `CloudGuard Impact Report - Resource: ${result.resource_address}, ` +
        `Risk Level: ${result.risk_level}, Confidence: ${result.confidence_score}%, ` +
        `Affected Resources: ${result.affected_count}`;

    try {
        await navigator.clipboard.writeText(summary);
        alert("Report information copied!");
    } catch (error) {
        alert("Unable to copy report information.");
    }
});
