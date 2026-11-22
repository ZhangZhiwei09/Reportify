(function () {
  "use strict";

  const list = document.getElementById("skill-list");
  const detail = document.getElementById("skill-detail");
  const validateBtn = document.getElementById("validate");
  let selected = null;

  function renderSkill(skill) {
    const item = RF.el("li", undefined, "list-item selectable");
    if (skill.name === selected) {
      item.classList.add("selected");
    }
    const label = RF.el("span");
    label.appendChild(RF.el("strong", skill.display_name));
    label.appendChild(document.createTextNode(" "));
    label.appendChild(RF.el("span", skill.name, "meta"));
    item.appendChild(label);
    item.appendChild(RF.badge("v" + skill.version, "muted"));
    item.addEventListener("click", function () {
      selected = skill.name;
      loadDetail(skill.name);
      load();
    });
    return item;
  }

  async function load() {
    try {
      const skills = await RF.get("/skills");
      RF.clear(list);
      if (!skills.length) {
        list.appendChild(RF.el("li", "workspace 中没有 Skill。", "list-item meta"));
        return;
      }
      skills.forEach(function (skill) {
        list.appendChild(renderSkill(skill));
      });
    } catch (error) {
      RF.toast("加载 Skills 失败：" + error.message, "error");
    }
  }

  async function loadDetail(name) {
    try {
      const skill = await RF.get("/skills/" + encodeURIComponent(name));
      detail.textContent = skill.content;
      validateBtn.disabled = false;
    } catch (error) {
      detail.textContent = "加载失败：" + error.message;
    }
  }

  document.getElementById("reload").addEventListener("click", async function () {
    try {
      const result = await RF.post("/skills/reload");
      RF.toast("已重载 " + result.skills + " 个 Skill");
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
      const result = await RF.post("/skills/" + encodeURIComponent(selected) + "/validate");
      RF.toast(result.ok ? "校验通过" : "校验失败：" + result.errors.join("; "), result.ok ? undefined : "error");
    } catch (error) {
      RF.toast("校验失败：" + error.message, "error");
    }
  });

  load();
})();
