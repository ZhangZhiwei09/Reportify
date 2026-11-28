(function () {
  "use strict";
  /* Cron schedules: list, create, pause, run once, delete (07 §6). */

  const rows = document.getElementById("schedule-rows");
  const form = document.getElementById("schedule-form");
  if (!rows || !form) {
    return;
  }

  const STATUS = {
    dispatched: ["已派发", "badge"],
    skipped: ["已跳过", "badge muted"],
    failed: ["失败", "badge danger"]
  };

  function statusCell(item) {
    const cell = RF.el("td");
    cell.appendChild(RF.badge(item.enabled ? "启用" : "暂停", item.enabled ? "badge" : "badge muted"));
    if (item.last_status && STATUS[item.last_status]) {
      const entry = STATUS[item.last_status];
      cell.appendChild(document.createTextNode(" "));
      cell.appendChild(RF.badge(entry[0], entry[1]));
    }
    if (item.last_error && item.last_error.code) {
      cell.appendChild(document.createTextNode(" "));
      const note = RF.el("span", item.last_error.code, "meta");
      cell.appendChild(note);
    }
    return cell;
  }

  function actionCell(item) {
    const cell = RF.el("td");
    const toggle = RF.el("button", item.enabled ? "暂停" : "启用", "btn");
    toggle.type = "button";
    toggle.addEventListener("click", function () {
      mutate(item, { enabled: !item.enabled });
    });
    const run = RF.el("button", "立即运行", "btn");
    run.type = "button";
    run.addEventListener("click", function () {
      run.disabled = true;
      RF.post("/schedules/" + item.id + "/run")
        .then(function (payload) {
          RF.toast("已启动运行 " + RF.shortId(payload.id));
          return load();
        })
        .catch(function (error) {
          run.disabled = false;
          RF.toast(error.message, "error");
        });
    });
    const remove = RF.el("button", "删除", "btn danger");
    remove.type = "button";
    remove.addEventListener("click", function () {
      if (!window.confirm("删除定时任务 " + item.name + "？已产生的运行会保留。")) {
        return;
      }
      RF.del("/schedules/" + item.id)
        .then(load)
        .catch(function (error) {
          RF.toast(error.message, "error");
        });
    });
    cell.appendChild(toggle);
    cell.appendChild(document.createTextNode(" "));
    cell.appendChild(run);
    cell.appendChild(document.createTextNode(" "));
    cell.appendChild(remove);
    return cell;
  }

  function render(items) {
    RF.clear(rows);
    if (!items.length) {
      const row = RF.el("tr");
      const cell = RF.el("td", "还没有定时任务。", "meta");
      cell.colSpan = 8;
      row.appendChild(cell);
      rows.appendChild(row);
      return;
    }
    items.forEach(function (item) {
      const row = RF.el("tr");
      row.appendChild(RF.el("td", item.name));
      row.appendChild(RF.el("td", item.cron));
      row.appendChild(RF.el("td", item.timezone));
      row.appendChild(statusCell(item));
      row.appendChild(RF.el("td", RF.formatTime(item.last_run_at)));
      row.appendChild(RF.el("td", RF.formatTime(item.next_run_at)));
      row.appendChild(RF.el("td", String(item.run_count)));
      row.appendChild(actionCell(item));
      rows.appendChild(row);
    });
  }

  function mutate(item, patch) {
    RF.patch("/schedules/" + item.id, patch)
      .then(function () {
        RF.toast(patch.enabled === true ? "已启用" : "已暂停");
        return load();
      })
      .catch(function (error) {
        RF.toast(error.message, "error");
      });
  }

  function load() {
    RF.setStatus("加载定时任务…");
    return RF.get("/schedules")
      .then(function (items) {
        render(items);
        RF.setStatus(items.length + " 个定时任务");
      })
      .catch(function (error) {
        RF.setStatus("");
        RF.toast(error.message, "error");
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const payload = {
      task_id: document.getElementById("schedule-task").value.trim(),
      cron: document.getElementById("schedule-cron").value.trim(),
      timezone: document.getElementById("schedule-tz").value.trim() || "UTC"
    };
    RF.post("/schedules", payload)
      .then(function () {
        RF.toast("已创建");
        return load();
      })
      .catch(function (error) {
        RF.toast(error.message, "error");
      });
  });

  load();
})();
