(function () {
  "use strict";

  const state = { conversationId: null, stream: null, taskId: null, runId: null };
  const conversationList = document.getElementById("conversation-list");
  const messageList = document.getElementById("message-list");
  const eventList = document.getElementById("event-list");
  const approvalCard = document.getElementById("approval-card");
  const approvalList = document.getElementById("approval-list");
  const form = document.getElementById("message-form");
  const input = document.getElementById("message-input");
  const runState = document.getElementById("run-state");

  function renderConversation(item) {
    const node = RF.el("li", undefined, "list-item selectable");
    node.appendChild(RF.el("span", item.title));
    node.appendChild(RF.el("span", item.status, "meta"));
    if (item.id === state.conversationId) {
      node.classList.add("selected");
    }
    node.addEventListener("click", function () {
      state.conversationId = item.id;
      state.taskId = null;
      loadConversations();
      loadMessages();
    });
    return node;
  }

  async function loadConversations() {
    try {
      const items = await RF.get("/conversations?limit=50");
      RF.clear(conversationList);
      if (!items.length) {
        conversationList.appendChild(RF.el("li", "还没有会话。", "list-item meta"));
        return;
      }
      items.forEach(function (item) {
        conversationList.appendChild(renderConversation(item));
      });
    } catch (error) {
      RF.toast("加载会话失败：" + error.message, "error");
    }
  }

  async function loadMessages() {
    if (!state.conversationId) {
      return;
    }
    try {
      const page = await RF.get(
        "/conversations/" + state.conversationId + "/messages?limit=100"
      );
      RF.clear(messageList);
      page.items.forEach(function (message) {
        const role = message.role === "user" ? "user" : message.role === "assistant" ? "assistant" : "system";
        messageList.appendChild(RF.el("div", message.content, "message " + role));
        if (message.task_id) {
          state.taskId = message.task_id;
        }
      });
      messageList.scrollTop = messageList.scrollHeight;
    } catch (error) {
      RF.toast("加载消息失败：" + error.message, "error");
    }
  }

  function appendEvent(name, payload) {
    const label = payload.tool_name
      ? name + " · " + payload.tool_name
      : name + (payload.status ? " · " + payload.status : "");
    eventList.appendChild(RF.el("li", label + "  " + RF.formatTime(new Date().toISOString())));
    eventList.scrollTop = eventList.scrollHeight;
  }

  function clearApprovals() {
    RF.clear(approvalList);
    approvalCard.hidden = true;
  }

  async function decide(approvalId, decision, node) {
    if (!state.runId) {
      return;
    }
    try {
      const result = await RF.post(
        "/runs/" + state.runId + "/approvals/" + encodeURIComponent(approvalId),
        { decision: decision }
      );
      node.remove();
      if (!approvalList.children.length) {
        approvalCard.hidden = true;
      }
      runState.textContent =
        result.status === "resuming" ? "已批准，继续执行…" : "等待其余审批…";
    } catch (error) {
      RF.toast("审批失败：" + error.message, "error");
    }
  }

  function renderApproval(payload) {
    approvalCard.hidden = false;
    const item = RF.el("li", undefined, "list-item");

    const label = RF.el("span");
    label.appendChild(RF.el("strong", payload.tool_name));
    label.appendChild(document.createTextNode(" "));
    label.appendChild(RF.badge(payload.risk || "write", "danger"));
    item.appendChild(label);

    const actions = RF.el("span");
    const approve = RF.el("button", "批准", "btn primary");
    approve.addEventListener("click", function () {
      decide(payload.approval_id, "approve", item);
    });
    const deny = RF.el("button", "拒绝", "btn danger");
    deny.addEventListener("click", function () {
      decide(payload.approval_id, "deny", item);
    });
    actions.appendChild(approve);
    actions.appendChild(deny);
    item.appendChild(actions);

    approvalList.appendChild(item);
    runState.textContent = "等待审批";
  }

  async function send(content) {
    if (!state.conversationId) {
      RF.toast("请先选择或新建会话。", "error");
      return;
    }
    RF.clear(eventList);
    clearApprovals();
    runState.textContent = "运行中…";
    try {
      const result = await RF.post(
        "/conversations/" + state.conversationId + "/messages",
        { content: content, task_id: state.taskId }
      );
      state.taskId = result.task_id;
      state.runId = result.run_id;
      if (state.stream) {
        state.stream.close();
      }
      state.stream = RFStream.open(result.run_id, {
        onEvent: function (name, payload) {
          if (name === "approval_required") {
            renderApproval(payload);
          }
          appendEvent(name, payload);
        },
        onDone: function () {
          runState.textContent = "已完成";
          clearApprovals();
          loadMessages();
        }
      });
      input.value = "";
      loadMessages();
    } catch (error) {
      runState.textContent = "失败";
      RF.toast("发送失败：" + error.message, "error");
    }
  }

  document.getElementById("new-conversation").addEventListener("click", async function () {
    try {
      const created = await RF.post("/conversations", { title: "新会话" });
      state.conversationId = created.id;
      state.taskId = null;
      RF.clear(messageList);
      RF.clear(eventList);
      await loadConversations();
    } catch (error) {
      RF.toast("新建会话失败：" + error.message, "error");
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const content = input.value.trim();
    if (content) {
      send(content);
    }
  });

  loadConversations();
})();
