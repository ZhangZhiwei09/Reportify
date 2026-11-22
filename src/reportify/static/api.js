/* fetch wrapper + DOM helpers. All dynamic text goes through textContent. */
(function () {
  "use strict";

  const API_BASE = "/api/v1";

  async function request(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(API_BASE + path, options);
    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        payload = null;
      }
      const message = payload && payload.detail ? payload.detail : response.statusText;
      const failure = new Error(message);
      failure.code = payload && payload.code ? payload.code : "http_" + response.status;
      failure.status = response.status;
      throw failure;
    }
    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    if (className) {
      node.className = className;
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function setStatus(text) {
    const node = document.getElementById("app-status");
    if (node) {
      node.textContent = text || "";
    }
  }

  let toastTimer = null;
  function toast(message, kind) {
    const node = document.getElementById("app-toast");
    if (!node) {
      return;
    }
    node.textContent = message;
    node.className = kind === "error" ? "toast error" : "toast";
    node.hidden = false;
    if (toastTimer) {
      window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(function () {
      node.hidden = true;
    }, 4000);
  }

  function badge(text, kind) {
    return el("span", text, kind ? "badge " + kind : "badge");
  }

  function shortId(value) {
    return value ? String(value).slice(0, 8) : "—";
  }

  function formatTime(value) {
    if (!value) {
      return "—";
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
  }

  window.RF = {
    get: function (path) { return request("GET", path); },
    post: function (path, body) { return request("POST", path, body); },
    patch: function (path, body) { return request("PATCH", path, body); },
    put: function (path, body) { return request("PUT", path, body); },
    del: function (path) { return request("DELETE", path); },
    el: el,
    clear: clear,
    setStatus: setStatus,
    toast: toast,
    badge: badge,
    shortId: shortId,
    formatTime: formatTime
  };
})();
