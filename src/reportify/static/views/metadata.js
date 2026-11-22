(function () {
  "use strict";

  const sourceSelect = document.getElementById("source-select");
  const tableSelect = document.getElementById("table-select");
  const rows = document.getElementById("column-rows");
  let tables = [];

  async function saveColumn(column, displayName, unit) {
    const sourceId = sourceSelect.value;
    try {
      await RF.patch("/data-sources/" + sourceId + "/columns/" + column.id, {
        display_name: displayName || null,
        unit: unit || null
      });
      RF.toast("已保存 " + column.column_name);
    } catch (error) {
      RF.toast("保存失败：" + error.message, "error");
    }
  }

  function renderColumn(column) {
    const row = document.createElement("tr");
    row.appendChild(RF.el("td", column.column_name));

    const typeCell = document.createElement("td");
    typeCell.appendChild(RF.el("span", column.native_type));
    typeCell.appendChild(document.createTextNode(" "));
    typeCell.appendChild(RF.badge(column.normalized_type, "muted"));
    row.appendChild(typeCell);

    const nameInput = document.createElement("input");
    nameInput.value = column.display_name || "";
    nameInput.placeholder = "展示名";
    const nameCell = document.createElement("td");
    nameCell.appendChild(nameInput);
    row.appendChild(nameCell);

    const unitInput = document.createElement("input");
    unitInput.value = column.unit || "";
    unitInput.placeholder = "单位";
    const unitCell = document.createElement("td");
    unitCell.appendChild(unitInput);
    row.appendChild(unitCell);

    const tags = document.createElement("td");
    (column.user_tags || []).forEach(function (tag) {
      tags.appendChild(RF.badge(tag, "muted"));
      tags.appendChild(document.createTextNode(" "));
    });
    row.appendChild(tags);

    const actionCell = document.createElement("td");
    const save = RF.el("button", "保存", "btn");
    save.addEventListener("click", function () {
      saveColumn(column, nameInput.value.trim(), unitInput.value.trim());
    });
    actionCell.appendChild(save);
    row.appendChild(actionCell);
    return row;
  }

  async function loadColumns() {
    const sourceId = sourceSelect.value;
    const table = tableSelect.value;
    RF.clear(rows);
    if (!sourceId || !table) {
      return;
    }
    try {
      const detail = await RF.get(
        "/data-sources/" + sourceId + "/columns?table=" + encodeURIComponent(table)
      );
      (detail.columns || []).forEach(function (column) {
        rows.appendChild(renderColumn(column));
      });
    } catch (error) {
      RF.toast("加载字段失败：" + error.message, "error");
    }
  }

  async function loadTables() {
    const sourceId = sourceSelect.value;
    RF.clear(tableSelect);
    RF.clear(rows);
    if (!sourceId) {
      return;
    }
    try {
      tables = await RF.get("/data-sources/" + sourceId + "/tables");
      tables.forEach(function (table) {
        const value = table.schema_name + "." + table.table_name;
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        tableSelect.appendChild(option);
      });
      if (tables.length) {
        loadColumns();
      }
    } catch (error) {
      RF.toast("加载表失败：" + error.message, "error");
    }
  }

  async function loadSources() {
    try {
      const sources = await RF.get("/data-sources");
      sources.forEach(function (source) {
        const option = document.createElement("option");
        option.value = source.id;
        option.textContent = source.name;
        sourceSelect.appendChild(option);
      });
      if (sources.length) {
        loadTables();
      }
    } catch (error) {
      RF.toast("加载数据源失败：" + error.message, "error");
    }
  }

  sourceSelect.addEventListener("change", loadTables);
  tableSelect.addEventListener("change", loadColumns);
  loadSources();
})();
