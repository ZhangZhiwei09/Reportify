(function () {
  "use strict";

  const list = document.getElementById("template-list");
  const detail = document.getElementById("template-detail");
  const validateBtn = document.getElementById("validate");
  let selected = null;

  function renderTemplate(template) {
    const item = RF.el("li", undefined, "list-item selectable");
    if (template.name === selected) {
      item.classList.add("selected");
    }
    const label = RF.el("span");
    label.appendChild(RF.el("strong", template.display_name));
    label.appendChild(document.createTextNode(" "));
    label.appendChild(RF.el("span", template.name, "meta"));
    item.appendChild(label);
    item.appendChild(RF.badge("schema v" + template.schema_version, "muted"));
    item.addEventListener("click", function () {
      selected = template.name;
      loadDetail(template.name);
      load();
    });
    return item;
  }

  async function load() {
    try {
      const templates = await RF.get("/report-templates");
      RF.clear(list);
      if (!templates.length) {
        list.appendChild(RF.el("li", "workspace 中没有模板。", "list-item meta"));
        return;
      }
      templates.forEach(function (template) {
        list.appendChild(renderTemplate(template));
      });
    } catch (error) {
      RF.toast("加载模板失败：" + error.message, "error");
    }
  }

  async function loadDetail(name) {
    try {
      const template = await RF.get("/report-templates/" + encodeURIComponent(name));
      detail.textContent = template.raw;
      validateBtn.disabled = false;
    } catch (error) {
      detail.textContent = "加载失败：" + error.message;
    }
  }

  document.getElementById("reload").addEventListener("click", async function () {
    try {
      const result = await RF.post("/report-templates/reload");
      RF.toast("已重载 " + result.templates + " 个模板");
      load();
    } catch (error) {
      RF.toast("重载失败：" + error.message, "error");
    }
  });

  validateBtn.addEventListener("click", async function () {
    if (!selected) {
      return;
    }
    try {
      const result = await RF.post(
        "/report-templates/" + encodeURIComponent(selected) + "/validate"
      );
      RF.toast("校验通过：" + (result.sections || []).join(" / "));
    } catch (error) {
      RF.toast("校验失败：" + error.message, "error");
    }
  });

  load();
})();
