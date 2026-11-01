// ===============================
// CLOUDGUARD DASHBOARD
// Renders real analysis results from the Flask API. Nothing here is
// hardcoded -- every value comes from /api/analyze, /api/analyses or the
// initial server-rendered analysis.
//
// Resource addresses and names come from uploaded plans, so they are
// always inserted with textContent, never innerHTML.
// ===============================

let currentResult = null;

const RING_CIRCUMFERENCE = 2 * Math.PI * 50; // matches r="50" in the template

// Sprite icon per resource type, matched on keywords so all three clouds are covered.
const RESOURCE_ICON_RULES = [
    [/security_group|security_rule|firewall/, "i-shield"],
    [/db_instance|database|sql/, "i-database"],
    [/instance|virtual_machine/, "i-server"],
    [/lambda|function/, "i-zap"],
    [/route/, "i-route"],
    [/iam|role|policy/, "i-key"],
    [/bucket|storage/, "i-box"],
];

function iconFor(resourceType) {
    const rule = RESOURCE_ICON_RULES.find(([pattern]) => pattern.test(resourceType));
    return rule ? rule[1] : "i-box";
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function icon(id, className = "ic") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", className);
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#${id}`);
    svg.appendChild(use);
    return svg;
}

function levelClass(level) {
    return { LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical" }[level] || "";
}

function pill(level) {
    return el("b", `pill ${levelClass(level)}`, level || "--");
}

function setPill(elementId, text, cls) {
    const node = document.getElementById(elementId);
    node.textContent = text;
    node.className = `pill ${cls}`;
}

// Address is always "<type>.<name>", optionally prefixed by one or more
// "module.<name>." segments -- so type/name are the LAST two parts.
function splitAddress(address) {
    const parts = address.split(".");
    return parts.length >= 2
        ? { type: parts[parts.length - 2], name: parts[parts.length - 1] }
        : { type: address, name: "" };
}

function flashStatus(text) {
    const title = document.getElementById("status-title");
    const previous = title.textContent;
    title.textContent = text;
    setTimeout(() => (title.textContent = previous), 2200);
}


// ===============================
// RENDERING
// ===============================

function renderDependencyChain(chain) {
    const container = document.getElementById("dependency-chain");
    container.replaceChildren();

    if (!chain || chain.length === 0) {
        container.appendChild(el("p", "empty", "No dependency chain: nothing else depends on this resource."));
        return;
    }

    chain.forEach((address, index) => {
        const { type, name } = splitAddress(address);
        const role = index === 0 ? " is-source" : index === chain.length - 1 ? " is-end" : "";
        const node = el("div", "node" + role);
        node.title = address;
        const badge = el("span", "badge");
        badge.appendChild(icon(iconFor(type)));
        const text = el("div");
        text.append(el("strong", null, type.replace(/^(aws|azurerm|google)_/, "")), el("span", null, name));
        node.append(badge, text);
        container.appendChild(node);

        if (index < chain.length - 1) container.appendChild(icon("i-arrow", "ic chain-arrow"));
    });
}

function renderSimilar(similarChanges) {
    const body = document.getElementById("history-body");
    body.replaceChildren();

    if (!similarChanges || similarChanges.length === 0) {
        const row = el("tr");
        const cell = el("td", "empty", "None yet. This looks like the first time this resource type and action were analyzed.");
        cell.colSpan = 4;
        row.appendChild(cell);
        body.appendChild(row);
        return;
    }

    similarChanges.forEach(change => {
        const row = el("tr");
        const risk = el("td");
        risk.appendChild(pill(change.risk_level));
        row.append(
            el("td", "mono", change.resource_address),
            el("td", null, change.change_action),
            risk,
            el("td", null, change.outcome),
        );
        body.appendChild(row);
    });
}

function renderList(listId, items, emptyText) {
    const list = document.getElementById(listId);
    list.replaceChildren();
    (items && items.length ? items : [emptyText]).forEach(item => list.appendChild(el("li", null, item)));
}

function renderImpactScore(score) {
    const hasScore = typeof score === "number";
    document.getElementById("impact-score").textContent = hasScore ? score : "--";
    const ring = document.getElementById("impact-ring");
    const fraction = hasScore ? Math.max(0, Math.min(100, score)) / 100 : 0;
    ring.style.strokeDashoffset = RING_CIRCUMFERENCE * (1 - fraction);
    ring.style.opacity = fraction > 0 ? 1 : 0; // a round linecap would leave a dot at 0
}

function renderVerdict(riskLevel) {
    const banner = document.getElementById("verdict");
    const risky = riskLevel === "CRITICAL" || riskLevel === "HIGH";
    banner.classList.toggle("is-risky", risky);
    banner.classList.toggle("is-safe", !risky);
    document.getElementById("warning-headline").textContent =
        risky ? "Review before deployment" : "Safe to proceed with standard review";
    document.getElementById("warning-sub").textContent =
        risky ? "This change needs careful consideration and a second pair of eyes." : "No high-risk signals found in this change.";
}

function renderResult(result) {
    if (!result) return;
    currentResult = result;

    const action = result.change_action || result.action;
    const riskClass = levelClass(result.risk_level);

    document.getElementById("status-title").textContent = "Analysis complete";
    document.getElementById("status-subtitle").textContent =
        `Showing ${result.resource_address} from ${result.plan_source || "an uploaded plan"}.`;

    document.getElementById("plain-summary").textContent = result.plain_summary || "No summary available.";

    document.getElementById("risk-stat").className = `stat ${riskClass}`;
    document.getElementById("metric-risk").textContent = result.risk_level;
    document.getElementById("metric-confidence").textContent = `${result.confidence_score}%`;
    document.getElementById("metric-affected").textContent = result.affected_count;
    document.getElementById("metric-affected-sub").textContent = "Reachable in the dependency graph";
    document.getElementById("metric-similar").textContent = (result.similar_past_changes || []).length;

    document.getElementById("detail-action").textContent = action;
    document.getElementById("detail-resource").textContent = result.resource_address;
    document.getElementById("detail-type").textContent = result.resource_type || splitAddress(result.resource_address).type;
    document.getElementById("detail-fields").textContent = Object.keys(result.changed_fields || {}).join(", ") || "(none)";
    document.getElementById("detail-source").textContent = result.plan_source || "--";

    renderDependencyChain(result.dependency_chain);

    setPill("impact-level-badge", result.impact_level, levelClass(result.impact_level));
    setPill("impact-risk-badge", result.risk_level, riskClass);
    const touchesSensitive = (result.recommendations || []).some(r => /restrict|public/i.test(r));
    setPill("impact-sensitive-badge", touchesSensitive ? "YES" : "NO", touchesSensitive ? "high" : "low");
    renderImpactScore(result.impact_score);

    renderSimilar(result.similar_past_changes);
    renderList("recommendations-list", result.recommendations, "No recommendations for this change.");
    renderList("rollback-list", result.rollback_plan, "No rollback steps needed.");
    renderVerdict(result.risk_level);
}


// ===============================
// ROUTING: #run / #snapshot scroll the dashboard, #history swaps views
// ===============================

const routes = {
    "": { view: "view-dashboard" },
    run: { view: "view-dashboard", section: "sec-run" },
    snapshot: { view: "view-dashboard", section: "sec-snapshot" },
    history: { view: "view-history", onShow: loadAllHistory },
};

function showRoute() {
    const key = location.hash.replace("#", "");
    const route = routes[key] || routes[""];
    document.querySelectorAll(".view").forEach(view => view.classList.toggle("is-active", view.id === route.view));
    document.querySelectorAll(".tabs a").forEach(link =>
        link.classList.toggle("is-active", link.dataset.route === (routes[key] ? key : "")));

    const section = route.section && document.getElementById(route.section);
    if (section) requestAnimationFrame(() => section.scrollIntoView({ behavior: "smooth", block: "start" }));
    else window.scrollTo({ top: 0 });
    if (route.onShow) route.onShow();
}

window.addEventListener("hashchange", showRoute);


// ===============================
// CHANGE HISTORY VIEW
// ===============================

async function openAnalysis(id) {
    try {
        const response = await fetch(`/api/analyses/${id}`);
        if (!response.ok) throw new Error("not found");
        renderResult(await response.json());
        location.hash = "";
    } catch (e) {
        flashStatus("Couldn't open that analysis");
    }
}

async function loadAllHistory() {
    const body = document.getElementById("all-history-body");
    try {
        const response = await fetch("/api/analyses");
        const analyses = await response.json();
        body.replaceChildren();

        if (analyses.length === 0) {
            const row = el("tr");
            const cell = el("td", "empty", "No analyses yet. Run one from the dashboard.");
            cell.colSpan = 6;
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }

        analyses.forEach(a => {
            const row = el("tr");
            row.dataset.id = a.id;
            row.tabIndex = 0;
            const impact = el("td");
            impact.appendChild(pill(a.impact_level));
            const risk = el("td");
            risk.appendChild(pill(a.risk_level));
            row.append(
                el("td", null, a.created_at ? new Date(a.created_at).toLocaleString() : "--"),
                el("td", "mono", a.resource_address),
                el("td", null, a.change_action),
                impact,
                risk,
                el("td", null, a.affected_count),
            );
            row.addEventListener("click", () => openAnalysis(a.id));
            row.addEventListener("keydown", e => { if (e.key === "Enter") openAnalysis(a.id); });
            body.appendChild(row);
        });
    } catch (e) {
        body.replaceChildren();
        const row = el("tr");
        const cell = el("td", "empty", "Couldn't load history. Is the Flask app running?");
        cell.colSpan = 6;
        row.appendChild(cell);
        body.appendChild(row);
    }
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
showRoute();


// ===============================
// ANALYZE FORM
// ===============================

const analyzeForm = document.getElementById("analyze-form");
const analyzeStatus = document.getElementById("analyze-status");
const fileInput = document.getElementById("plan-file");

fileInput.addEventListener("change", () => {
    const hasFile = fileInput.files.length > 0;
    document.getElementById("plan-file-name").textContent = hasFile ? fileInput.files[0].name : "Or upload a plan JSON";
    fileInput.closest(".dropzone").classList.toggle("has-file", hasFile);
});

analyzeForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const formData = new FormData();
    let planSource;
    if (fileInput.files.length > 0) {
        planSource = fileInput.files[0].name;
        formData.append("plan_file", fileInput.files[0]);
    } else {
        planSource = document.getElementById("sample-select").value;
        formData.append("sample_name", planSource);
    }

    const submit = analyzeForm.querySelector("button[type=submit]");
    submit.disabled = true;
    analyzeStatus.classList.remove("is-error");
    analyzeStatus.textContent = "Analyzing…";

    try {
        const response = await fetch("/api/analyze", { method: "POST", body: formData });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || "Analysis failed");
        }

        const results = await response.json();
        if (results.length === 0) {
            analyzeStatus.textContent = "No effective changes found in this plan.";
            return;
        }

        // /api/analyze results don't carry plan_source; stored analyses do.
        renderResult({ plan_source: planSource, ...results[0] });
        analyzeStatus.textContent = results.length > 1
            ? `Showing the highest-risk change. ${results.length - 1} other change(s) in this plan were also analyzed; see Change history.`
            : "Analysis complete.";
    } catch (error) {
        analyzeStatus.classList.add("is-error");
        analyzeStatus.textContent = `Error: ${error.message}`;
    } finally {
        submit.disabled = false;
    }
});


// ===============================
// DOWNLOAD & SHARE REPORT
// ===============================

document.getElementById("download-btn").addEventListener("click", function () {
    if (!currentResult) {
        flashStatus("Run an analysis first");
        return;
    }
    window.location.href = `/api/analyses/${currentResult.id}/report`;
});

document.getElementById("share-btn").addEventListener("click", async function () {
    if (!currentResult) {
        flashStatus("Run an analysis first");
        return;
    }

    const summary = `CloudGuard Impact Report - Resource: ${currentResult.resource_address}, ` +
        `Risk Level: ${currentResult.risk_level}, Data completeness: ${currentResult.confidence_score}%, ` +
        `Affected Resources: ${currentResult.affected_count}`;

    try {
        await navigator.clipboard.writeText(summary);
        flashStatus("Summary copied to clipboard");
    } catch (error) {
        flashStatus("Couldn't copy the summary");
    }
});


// ===============================
// LIVE AWS SNAPSHOT
// Read-only, on-demand -- only calls AWS when the button is clicked.
// ===============================

function renderSnapshotStatus(data) {
    const statusEl = document.getElementById("snapshot-status");
    statusEl.classList.remove("is-error");

    if (!data.synced) {
        statusEl.textContent = "Not synced yet. Click “Sync now” to pull your current AWS state (read-only).";
        return;
    }

    const counts = Object.entries(data.counts || {})
        .map(([type, count]) => `${count} ${type.replace("aws_", "")}`)
        .join(", ") || "no resources found";

    statusEl.textContent = `Last synced ${new Date(data.synced_at).toLocaleString()} (region ${data.region}): ${counts}.`;

    if (data.errors && data.errors.length > 0) {
        statusEl.textContent += ` ${data.errors.length} resource type(s) skipped, likely a missing IAM permission.`;
    }
}

async function loadSnapshotStatus() {
    try {
        const response = await fetch("/api/current-state");
        renderSnapshotStatus(await response.json());
    } catch (e) {
        console.warn("Could not load snapshot status.");
    }
}

loadSnapshotStatus();

document.getElementById("sync-btn").addEventListener("click", async function () {
    const button = this;
    const statusEl = document.getElementById("snapshot-status");

    button.disabled = true;
    statusEl.classList.remove("is-error");
    statusEl.textContent = "Syncing (read-only calls to AWS)…";

    try {
        const response = await fetch("/api/sync-aws-state", { method: "POST" });
        const data = await response.json();

        if (!response.ok) {
            statusEl.classList.add("is-error");
            statusEl.textContent = `Sync failed: ${data.error || "unknown error"}. ` +
                "Check AWS credentials are configured (see README) and the read-only IAM policy is attached.";
        } else {
            renderSnapshotStatus(data);
        }
    } catch (error) {
        statusEl.classList.add("is-error");
        statusEl.textContent = `Sync failed: ${error.message}`;
    } finally {
        button.disabled = false;
    }
});
