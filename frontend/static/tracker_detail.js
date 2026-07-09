/* Tracker application detail (SPEC §5.6): status transitions (logged to
   history), notes + next-action editing, delete. No LLM involvement. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const appId = Number($(".detail-wrap").dataset.appId);

  let toastTimer;
  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function req(method, url, body) {
    const opts = { method };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  // status change -> re-render history
  $("#status-select").addEventListener("change", async (e) => {
    const status = e.target.value;
    try {
      const data = await req("PUT", "/api/applications/" + appId + "/status", { status });
      const list = $("#history-list");
      list.innerHTML = data.history.map((h) =>
        '<li><span class="status-dot status-' + escapeHtml(h.status) + '">' +
        '<span class="dot"></span></span> ' + escapeHtml(h.status) +
        ' <span class="dropnote">' + escapeHtml(h.changed_at.replace("T", " ")) +
        "</span></li>").join("");
      toast("Status → " + status);
    } catch (err) {
      toast("Failed: " + err.message, true);
    }
  });

  async function saveFields(fields, statusEl, btn) {
    btn.disabled = true;
    statusEl.textContent = "Saving…";
    try {
      await req("PUT", "/api/applications/" + appId, fields);
      statusEl.textContent = "Saved.";
      toast("Saved.");
    } catch (err) {
      statusEl.textContent = "Failed: " + err.message;
    } finally {
      btn.disabled = false;
    }
  }

  $("#save-notes").addEventListener("click", () =>
    saveFields({ notes: $("#notes").value }, $("#notes-status"), $("#save-notes")));

  $("#save-next").addEventListener("click", () =>
    saveFields({
      next_action: $("#next-action").value.trim(),
      next_action_date: $("#next-action-date").value || null,
    }, $("#next-status"), $("#save-next")));

  $("#delete-btn").addEventListener("click", async () => {
    if (!window.confirm("Delete this application and its status history? " +
        "This cannot be undone. (Saved CV versions and letters on disk are kept.)")) return;
    try {
      await req("DELETE", "/api/applications/" + appId);
      window.location.href = "/tracker";
    } catch (err) {
      toast("Failed: " + err.message, true);
    }
  });
})();
