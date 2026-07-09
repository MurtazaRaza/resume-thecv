/* Tracker dashboard (SPEC §5.6): the app's home. Lists applications grouped by
   status; a row click opens the detail page; "+ New application" creates one
   with no LLM involvement. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);

  let toastTimer;
  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
  }

  async function post(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  // row -> detail page. Ignore clicks on links inside the row.
  document.querySelectorAll(".app-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      window.location.href = row.dataset.href;
    });
  });

  // new-application form
  const pane = $("#new-app-pane");
  $("#new-app-btn").addEventListener("click", () => {
    pane.hidden = !pane.hidden;
    if (!pane.hidden) $("#na-company").focus();
  });
  $("#na-cancel").addEventListener("click", () => { pane.hidden = true; });

  $("#na-create").addEventListener("click", async () => {
    const company = $("#na-company").value.trim();
    const role = $("#na-role").value.trim();
    if (!company || !role) { toast("Company and role are required", true); return; }
    const btn = $("#na-create");
    btn.disabled = true;
    $("#na-status").textContent = "Creating…";
    try {
      const data = await post("/api/applications", {
        company, role, url: $("#na-url").value.trim(),
      });
      window.location.href = "/tracker/" + data.id;
    } catch (e) {
      $("#na-status").textContent = "Failed: " + e.message;
      btn.disabled = false;
    }
  });
})();
