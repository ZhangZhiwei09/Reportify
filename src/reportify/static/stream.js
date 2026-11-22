/* SSE helper for run events (07 §6). Read-only; reconnects with Last-Event-ID. */
(function () {
  "use strict";

  function openRunStream(runId, handlers) {
    const options = handlers || {};
    let lastEventId = 0;
    let source = null;
    let closed = false;

    function connect() {
      if (closed) {
        return;
      }
      const base = "/api/v1/runs/" + encodeURIComponent(runId) + "/events";
      const url = lastEventId ? base + "?after=" + encodeURIComponent(lastEventId) : base;
      source = new EventSource(url);
      RF.setStatus("已连接事件流");

      const known = [
        "run_started", "plan", "model_request", "tool_call", "tool_result",
        "usage", "approval_required", "report_generated", "run_completed", "error"
      ];
      known.forEach(function (name) {
        source.addEventListener(name, function (event) {
          if (event.lastEventId) {
            lastEventId = Number(event.lastEventId) || lastEventId;
          }
          let payload = {};
          try {
            payload = JSON.parse(event.data);
          } catch (error) {
            payload = { raw: event.data };
          }
          if (options.onEvent) {
            options.onEvent(name, payload, event.lastEventId);
          }
          if (name === "run_completed" || name === "error") {
            closed = true;
            source.close();
            RF.setStatus(name === "error" ? "运行失败" : "运行结束");
            if (options.onDone) {
              options.onDone(name, payload);
            }
          }
        });
      });

      source.onerror = function () {
        if (closed) {
          return;
        }
        source.close();
        RF.setStatus("事件流断开，正在重连…");
        window.setTimeout(connect, 2000);
      };
    }

    connect();

    return {
      close: function () {
        closed = true;
        if (source) {
          source.close();
        }
      }
    };
  }

  window.RFStream = { open: openRunStream };
})();
