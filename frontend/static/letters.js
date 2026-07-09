/* Cover letter page (SPEC §5.5): pick an application -> beat-by-beat LLM draft
   -> edit -> export .md + .pdf. Nothing is applied to the CV; the letter text is
   fully editable before export. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);

  let applicationId = null;

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

  $("#app-select").addEventListener("change", (e) => {
    applicationId = e.target.value || null;
  });

  $("#gen-btn").addEventListener("click", async () => {
    if (!applicationId) { toast("Pick an application first", true); return; }
    const status = $("#gen-status");
    const btn = $("#gen-btn");
    btn.disabled = true;
    status.textContent = "Drafting beat by beat — this runs several small calls…";
    try {
      const data = await post("/api/letters/generate", {
        application_id: Number(applicationId),
        tone: $("#tone-select").value,
        emphasize: $("#emphasize").value,
      });
      $("#beat-list").innerHTML = data.beats.map((b) =>
        "<li><strong>" + escapeHtml(b.name) + ":</strong> " +
        escapeHtml(b.point) + "</li>").join("");
      $("#letter-body").value = data.body;
      $("#draft-pane").hidden = false;
      $("#export-pane").hidden = false;
      if (data.errors && data.errors.length) {
        status.textContent = "Draft ready (" + data.errors.length +
          " beat(s) failed — edit as needed).";
      } else {
        status.textContent = "Draft ready — edit the text, then export.";
      }
    } catch (e) {
      status.textContent = "Failed: " + e.message;
    } finally {
      btn.disabled = false;
    }
  });

  $("#export-btn").addEventListener("click", async () => {
    if (!applicationId) { toast("Pick an application first", true); return; }
    const status = $("#export-status");
    const btn = $("#export-btn");
    btn.disabled = true;
    status.textContent = "Rendering PDF…";
    try {
      const data = await post("/api/letters/export", {
        application_id: Number(applicationId),
        body: $("#letter-body").value,
      });
      const result = $("#export-result");
      result.hidden = false;
      result.innerHTML = "Saved <code>" + escapeHtml(data.pdf) + "</code>";
      status.textContent = "Exported.";
      if (data.pdf_url) {
        $("#preview-pane").hidden = false;
        $("#letter-preview").src = data.pdf_url;
      }
      toast("Cover letter saved to data/letters/");
    } catch (e) {
      status.textContent = "Failed: " + e.message;
    } finally {
      btn.disabled = false;
    }
  });
})();
