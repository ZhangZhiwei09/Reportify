(function () {
  "use strict";

  const serverList = document.getElementById("server-list");
  const toolRows = document.getElementById("tool-rows");
  const toolsHint = document.getElementById("tools-hint");
  const auditList = document.getElementById("audit-list");
  const form = document.getElementById("server-form");

  async function grant(tool, allowed) {
    try {
      if (allowed) {
        await RF.put("/mcp/tools/" + tool.id + "/grant", {
          allowed: true,
          risk_level: tool.risk_level === "read" ? "read" : "write",
          risk_acknowledged: true
        });
        RF.toast("已授权 " + tool.model_name);
      } else {
        await RF.del("/mcp/tools/" + tool.id + "/grant");
        RF.toast("已撤销 " + tool.model_name);
      }
      loadTools(serverList.dataset.server);
    } catch (error) {
      RF.toast("授权失败：" + error.message, "error");
    }
  }

  function renderTool(tool) {
    const row = document.createElement("tr");
    row.appendChild(RF.el("td", tool.model_name));
    row.appendChild(RF.el("td", tool.risk_level));
    row.appendChild(RF.el("td", tool.granted ? "已授权" : "未授权"));
    row.appendChild(RF.el("td", tool.risk_acknowledged ? "已确认" : "未确认"));

    const actions = document.createElement("td");
    const button = RF.el("button", tool.granted ? "撤销" : "授权", tool.granted ? "btn danger" : "btn primary");
    button.addEventListener("click", function () {
      grant(tool, !tool.granted);
    });
    actions.appendChild(button);
    row.appendChild(actions);
    return row;
  }

  async function loadTools(serverId) {
    if (!serverId) {
      return;
    }
    serverList.dataset.server = serverId;
    toolsHint.textContent = serverId.slice(0, 8);
    try {
      const tools = await RF.get("/mcp/servers/" + serverId + "/tools");
      RF.clear(toolRows);
      if (!tools.length) {
        const row = document.createElement("tr");
        const cell = RF.el("td", "尚未发现工具。先执行 discover。", "meta");
        cell.colSpan = 5;
        row.appendChild(cell);
        toolRows.appendChild(row);
        return;
      }
      tools.forEach(function (tool) {
        toolRows.appendChild(renderTool(tool));
      });
    } catch (error) {
      RF.toast("加载工具失败：" + error.message, "error");
    }
  }

  async function action(server, kind) {
    const path = "/mcp/servers/" + server.id + "/" + kind;
    try {
      const result = await RF.post(path);
      if (kind === "test") {
        RF.toast(result.ok ? "连接正常，工具 " + result.tool_count + " 个" : "连接失败：" + (result.error || ""));
      } else {
        RF.toast("发现完成：新增 " + result.tools_added + " 个工具");
        loadTools(server.id);
      }
    } catch (error) {
      RF.toast("操作失败：" + error.message, "error");
    }
  }

  function renderServer(server) {
    const item = RF.el("li", undefined, "list-item selectable");
    const label = RF.el("span");
    label.appendChild(RF.el("strong", server.name));
    label.appendChild(document.createTextNode(" "));
    label.appendChild(RF.badge(server.status, server.status === "connected" ? undefined : "muted"));
    if (!server.enabled) {
      label.appendChild(document.createTextNode(" "));
      label.appendChild(RF.badge("已禁用", "muted"));
    }
    item.appendChild(label);

    const actions = RF.el("span");
    const test = RF.el("button", "测试", "btn");
    test.addEventListener("click", function (event) {
      event.stopPropagation();
      action(server, "test");
    });
    const discover = RF.el("button", "发现", "btn");
    discover.addEventListener("click", function (event) {
      event.stopPropagation();
      action(server, "discover");
    });
    actions.appendChild(test);
    actions.appendChild(discover);
    item.appendChild(actions);

    item.addEventListener("click", function () {
      loadTools(server.id);
    });
    return item;
  }

  async function loadServers() {
    try {
      const servers = await RF.get("/mcp/servers");
      RF.clear(serverList);
      if (!servers.length) {
        serverList.appendChild(RF.el("li", "还没有 MCP Server。", "list-item meta"));
        return;
      }
      servers.forEach(function (server) {
        serverList.appendChild(renderServer(server));
      });
    } catch (error) {
      RF.toast("加载 Server 失败：" + error.message, "error");
    }
  }

  async function loadAudits() {
    try {
      const audits = await RF.get("/mcp/audits?limit=20");
      RF.clear(auditList);
      if (!audits.length) {
        auditList.appendChild(RF.el("li", "没有 MCP 调用记录。", "list-item meta"));
        return;
      }
      audits.forEach(function (audit) {
        const item = RF.el("li", undefined, "list-item");
        item.appendChild(RF.el("span", audit.tool_name + " · " + audit.status));
        item.appendChild(RF.el("span", RF.formatTime(audit.created_at), "meta"));
        auditList.appendChild(item);
      });
    } catch (error) {
      RF.toast("加载审计失败：" + error.message, "error");
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const data = new FormData(form);
    const payload = {
      name: String(data.get("name") || ""),
      slug: String(data.get("slug") || ""),
      url: String(data.get("url") || ""),
      auth_type: String(data.get("auth_type") || "none")
    };
    const token = String(data.get("token") || "");
    if (token) {
      payload.token = token;
    }
    try {
      await RF.post("/mcp/servers", payload);
      form.reset();
      RF.toast("Server 已保存");
      loadServers();
    } catch (error) {
      RF.toast("保存失败：" + error.message, "error");
    }
  });

  document.getElementById("refresh").addEventListener("click", loadServers);
  document.getElementById("load-audits").addEventListener("click", loadAudits);
  loadServers();
})();
