(function () {
  "use strict";

  const rows = document.getElementById("report-rows");
  const lineage = document.getElementById("report-lineage");
  const revisionPanel = document.getElementById("report-diff");

  async function showLineage(report) {
    lineage.textContent = JSON.stringify(report.lineage, null, 2);
  }

  function revisionLines(report, revisions) {
    const lines = revisions.map(function (item) {
      const marker = item.id === report.id ? "  ← 当前" : "";
      return "v" + item.version + " · " + item.title + " · " +
        RF.formatTime(item.created_at) + marker;
    });
    return ["版本链：", ...lines].join("\n");
  }

  function diffLines(diff) {
    if (diff.identical) {
      return ["", "与上一版无差异。"];
    }
    const lines = ["", "与 v" + diff.base_version + " 对比："];
    if (diff.title_before !== null) {
      lines.push("标题：" + diff.title_before + " → " + diff.title_after);
    }
    if (diff.summary_before !== null) {
      lines.push("摘要已修改。");
    }
    diff.sections_added.forEach(function (id) { lines.push("新增章节：" + id); });
    diff.sections_removed.forEach(function (id) { lines.push("删除章节：" + id); });
    diff.kpis.forEach(function (item) {
      lines.push("KPI " + item.label + "：" + item.before + " → " + item.after);
    });
    diff.charts.forEach(function (item) {
      lines.push("图表 " + item.title + "：series " + item.series_before + "→" +
        item.series_after + "，点数 " + item.points_before + "→" + item.points_after);
    });
    diff.tables.forEach(function (item) {
      lines.push("表格 " + item.title + "：行数 " + item.rows_before + "→" + item.rows_after);
    });
    diff.texts.forEach(function (item) {
      lines.push("文本（" + item.section + "）已修改。");
    });
    return lines;
  }

  async function showRevisions(report) {
    revisionPanel.textContent = "加载版本链…";
    try {
      const revisions = await RF.get("/reports/" + report.id + "/revisions");
      const lines = revisionLines(report, revisions);
      if (report.parent_report_id) {
        const diff = await RF.get("/reports/" + report.id + "/diff");
        lines.push(...diffLines(diff));
      } else {
        lines.push("", "首个版本，没有可对比的上一版。");
      }
      revisionPanel.textContent = lines.join("\n");
    } catch (error) {
      revisionPanel.textContent = "读取版本失败：" + error.message;
    }
  }

  function renderRow(report) {
    const row = document.createElement("tr");
    row.appendChild(RF.el("td", report.title));
    row.appendChild(RF.el("td", "v" + (report.version || 1)));
    row.appendChild(RF.el("td", report.status));
    row.appendChild(RF.el("td", report.renderer || "—"));
    const snapshots = (report.lineage && report.lineage.snapshot_ids) || [];
    row.appendChild(RF.el("td", String(snapshots.length)));
    row.appendChild(RF.el("td", RF.formatTime(report.created_at)));

    const actions = document.createElement("td");
    const versions = RF.el("button", "版本", "btn");
    versions.addEventListener("click", function () {
      showRevisions(report);
    });
    const view = RF.el("button", "Lineage", "btn");
    view.addEventListener("click", function () {
      showLineage(report);
    });
    const open = RF.el("a", "打开", "btn");
    open.href = "/api/v1/reports/" + report.id + "/download";
    open.target = "_blank";
    open.rel = "noopener";
    actions.appendChild(versions);
    actions.appendChild(document.createTextNode(" "));
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
        cell.colSpan = 7;
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
