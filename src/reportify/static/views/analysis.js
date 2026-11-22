(function () {
  "use strict";

  const state = { conversationId: null, stream: null, taskId: null };
  const conversationList = document.getElementById("conversation-list");
  const messageList = document.getElementById("message-list");
  const eventList = document.getElementById("event-list");
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

  async function send(content) {
    if (!state.conversationId) {
      RF.toast("请先选择或新建会话。", "error");
      return;
    }
    RF.clear(eventList);
    runState.textContent = "运行中…";
    try {
      const result = await RF.post(
        "/conversations/" + state.conversationId + "/messages",
        { content: content, task_id: state.taskId }
      );
      state.taskId = result.task_id;
      if (state.stream) {
        state.stream.close();
      }
      state.stream = RFStream.open(result.run_id, {
        onEvent: appendEvent,
        onDone: function () {
          runState.textContent = "已完成";
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
