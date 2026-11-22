(function () {
  "use strict";

  const list = document.getElementById("source-list");
  const tableList = document.getElementById("table-list");
  const hint = document.getElementById("source-hint");
  const form = document.getElementById("source-form");

  async function loadTables(source) {
    hint.textContent = source.name;
    RF.clear(tableList);
    try {
      const tables = await RF.get("/data-sources/" + source.id + "/tables");
      if (!tables.length) {
        tableList.appendChild(RF.el("li", "尚未同步结构。", "list-item meta"));
        return;
      }
      tables.forEach(function (table) {
        const item = RF.el("li", undefined, "list-item");
        item.appendChild(RF.el("span", table.schema_name + "." + table.table_name));
        item.appendChild(RF.el("span", (table.columns || []).length + " 列", "meta"));
        tableList.appendChild(item);
      });
    } catch (error) {
      RF.toast("加载表失败：" + error.message, "error");
    }
  }

  async function sync(source) {
    try {
      const result = await RF.post("/data-sources/" + source.id + "/sync");
      RF.toast(
        "同步完成：+" + result.tables_added + " 表 / +" + result.columns_added + " 列"
      );
      loadTables(source);
    } catch (error) {
      RF.toast("同步失败：" + error.message, "error");
    }
  }

  async function test(source) {
    try {
      const result = await RF.post("/data-sources/" + source.id + "/test");
      RF.toast(result.ok ? "连接正常" : "连接失败：" + (result.detail || ""), result.ok ? undefined : "error");
    } catch (error) {
      RF.toast("测试失败：" + error.message, "error");
    }
  }

  function renderSource(source) {
    const item = RF.el("li", undefined, "list-item");
    const label = RF.el("span");
    label.appendChild(RF.el("strong", source.name));
    label.appendChild(document.createTextNode(" "));
    label.appendChild(RF.badge(source.status, source.status === "active" ? undefined : "muted"));
    item.appendChild(label);

    const actions = RF.el("span");
    const testBtn = RF.el("button", "测试", "btn");
    testBtn.addEventListener("click", function () {
      test(source);
    });
    const syncBtn = RF.el("button", "同步", "btn");
    syncBtn.addEventListener("click", function () {
      sync(source);
    });
    const viewBtn = RF.el("button", "查看表", "btn");
    viewBtn.addEventListener("click", function () {
      loadTables(source);
    });
    actions.appendChild(testBtn);
    actions.appendChild(syncBtn);
    actions.appendChild(viewBtn);
    item.appendChild(actions);
    return item;
  }

  async function load() {
    try {
      const sources = await RF.get("/data-sources");
      RF.clear(list);
      if (!sources.length) {
        list.appendChild(RF.el("li", "还没有数据源。", "list-item meta"));
        return;
      }
      sources.forEach(function (source) {
        list.appendChild(renderSource(source));
      });
    } catch (error) {
      RF.toast("加载数据源失败：" + error.message, "error");
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const data = new FormData(form);
    const payload = {
      name: String(data.get("name") || ""),
      type: "postgresql",
      host: String(data.get("host") || ""),
      port: Number(data.get("port") || 5432),
      database: String(data.get("database") || ""),
      username: String(data.get("username") || ""),
      password: String(data.get("password") || ""),
      options: { schema_allowlist: [String(data.get("schema") || "public")] }
    };
    try {
      await RF.post("/data-sources", payload);
      form.reset();
      RF.toast("数据源已保存");
      load();
    } catch (error) {
      RF.toast("保存失败：" + error.message, "error");
    }
  });

  document.getElementById("refresh").addEventListener("click", load);
  load();
})();
