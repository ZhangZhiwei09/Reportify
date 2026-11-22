(function () {
  "use strict";
  // Scheduling itself is §12+; this view only reports the current state honestly.
  RF.setStatus("定时任务未启用");
  const lastRun = document.getElementById("last-run");
  if (lastRun) {
    const stamp = window.localStorage.getItem("reportify:lastRun");
    lastRun.textContent = stamp ? stamp : "—";
  }
})();
