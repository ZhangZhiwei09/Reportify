(function () {
  "use strict";

  const rows = document.getElementById("report-rows");
  const lineage = document.getElementById("report-lineage");

  async function showLineage(report) {
    lineage.textContent = JSON.stringify(report.lineage, null, 2);
  }

  function renderRow(report) {
    const row = document.createElement("tr");
    row.appendChild(RF.el("td", report.title));
    row.appendChild(RF.el("td", report.status));
    row.appendChild(RF.el("td", report.renderer || "—"));
    const snapshots = (report.lineage && report.lineage.snapshot_ids) || [];
    row.appendChild(RF.el("td", String(snapshots.length)));
    row.appendChild(RF.el("td", RF.formatTime(report.created_at)));

    const actions = document.createElement("td");
    const view = RF.el("button", "Lineage", "btn");
    view.addEventListener("click", function () {
      showLineage(report);
    });
    const open = RF.el("a", "打开", "btn");
    open.href = "/api/v1/reports/" + report.id + "/download";
    open.target = "_blank";
    open.rel = "noopener";
    actions.appendChild(view);
    actions.appendChild(document.createTextNode(" "));
    actions.appendChild(open);
    row.appendChild(actions);
    return row;
  }

  async function load() {
    try {
      const reports = await RF.get("/reports?limit=50");
      RF.clear(rows);
      if (!reports.length) {
        const row = document.createElement("tr");
        const cell = RF.el("td", "还没有报告。", "meta");
        cell.colSpan = 6;
        row.appendChild(cell);
        rows.appendChild(row);
        return;
      }
      reports.forEach(function (report) {
        rows.appendChild(renderRow(report));
      });
    } catch (error) {
      RF.toast("加载报告失败：" + error.message, "error");
    }
  }

  document.getElementById("refresh").addEventListener("click", load);
  load();
})();
