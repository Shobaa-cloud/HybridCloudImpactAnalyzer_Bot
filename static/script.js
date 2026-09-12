// ===============================
// CLOUDGUARD DASHBOARD
// ===============================

// Sample dashboard data
const dashboardData = {
    affectedResources: 7,
    confidenceScore: 91,
    similarChanges: 4,
    riskLevel: "HIGH"
};


// Update dashboard values
document.getElementById("affected").textContent =
    dashboardData.affectedResources;


// ===============================
// SIDEBAR NAVIGATION
// ===============================

const navItems = document.querySelectorAll(".nav-item");

navItems.forEach(item => {

    item.addEventListener("click", function () {

        // Remove active from all
        navItems.forEach(nav => {
            nav.classList.remove("active");
        });

        // Add active to clicked item
        this.classList.add("active");

        const pageName = this.innerText.trim();

        console.log("Selected:", pageName);

    });

});


// ===============================
// DOWNLOAD REPORT
// ===============================

const downloadButton =
    document.querySelector(".header-buttons button:first-child");

downloadButton.addEventListener("click", function () {

    const report = `
CLOUDGUARD - IMPACT ANALYSIS REPORT

Risk Level: ${dashboardData.riskLevel}
Confidence Score: ${dashboardData.confidenceScore}%
Affected Resources: ${dashboardData.affectedResources}
Similar Past Changes: ${dashboardData.similarChanges}

Recommendation:
Review the configuration change before deployment.
    `;

    const file = new Blob([report], {
        type: "text/plain"
    });

    const link = document.createElement("a");

    link.href = URL.createObjectURL(file);
    link.download = "cloudguard-impact-report.txt";

    link.click();

    URL.revokeObjectURL(link.href);

});


// ===============================
// SHARE REPORT
// ===============================

const shareButton =
    document.querySelector(".header-buttons button.share");

shareButton.addEventListener("click", async function () {

    const reportText =
        "CloudGuard Impact Report - Risk Level: HIGH, " +
        "Confidence: 91%, Affected Resources: 7";

    try {

        await navigator.clipboard.writeText(reportText);

        alert("Report information copied!");

    } catch (error) {

        alert("Unable to copy report information.");

    }

});