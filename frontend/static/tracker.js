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

  // ---- Quick Capture & Instant Fit Check -------------------------------------
  const BANDS = {
    strong: { pill: "good", label: "Strong fit" },
    partial: { pill: "mid", label: "Partial fit" },
    longshot: { pill: "low", label: "Long shot" },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function renderVerdict(data) {
    const band = BANDS[data.band] || BANDS.longshot;
    const card = $("#verdict-card");

    const pill = $("#verdict-pill");
    pill.textContent = data.coverage + "%";
    pill.className = "match-pill " + band.pill;
    $("#verdict-band").textContent = band.label;

    const fill = $("#verdict-fill");
    fill.style.width = data.coverage + "%";
    fill.className = "coverage-fill " + band.pill;

    const missing = data.top_missing || [];
    $("#verdict-missing").innerHTML = missing.length
      ? '<span class="dropnote">Top missing must-haves:</span> ' +
        missing.map((m) => '<span class="chip miss">' + escapeHtml(m) + "</span>").join("")
      : '<span class="dropnote">No must-haves missing from your CV.</span>';

    const n = data.tailorable_count;
    $("#verdict-effort").textContent = n
      ? "~" + n + " bullet" + (n === 1 ? "" : "s") + " could be tailored to close the gap."
      : "No bullets obviously relate to the missing keywords.";

    const action = $("#verdict-action");
    action.textContent = data.next_action;
    action.href = "/tailor?app=" + data.application_id;
    $("#verdict-open").href = "/tracker/" + data.application_id;

    card.hidden = false;
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  $("#cap-submit").addEventListener("click", async () => {
    const company = $("#cap-company").value.trim();
    const role = $("#cap-role").value.trim();
    const jd = $("#cap-jd").value.trim();
    if (!company || !role) { toast("Company and role are required", true); return; }
    if (!jd) { toast("Paste the job description first", true); return; }
    const btn = $("#cap-submit");
    btn.disabled = true;
    $("#cap-status").textContent = "Saving & checking fit…";
    try {
      const data = await post("/api/capture", {
        company, role, url: $("#cap-url").value.trim(), jd_text: jd,
      });
      $("#cap-status").textContent = "";
      renderVerdict(data);
    } catch (e) {
      // the save survives an LLM failure; the app row already exists
      $("#cap-status").textContent = "Saved, but fit check failed: " + e.message;
    } finally {
      btn.disabled = false;
    }
  });
})();
