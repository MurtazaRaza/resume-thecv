/* Project & experience bank manager (docs/features/profiles-and-bank.md §3).
   Add/edit tagged entries, "Suggest tags" (one LLM call, approve/edit only),
   and "Insert into CV" (suggest-and-approve — the click is the approval).
   Saves reload the page so the server-rendered list stays authoritative. */
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

  async function send(url, method, body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const resp = await fetch(url, opts);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  const bank = JSON.parse($("#bank-data").textContent || "{}");
  function findEntry(id) {
    return (bank.projects || []).concat(bank.experiences || [])
      .find((e) => e.id === id);
  }

  const form = $("#entry-form");
  const projFields = $("#ef-project-fields");
  const expFields = $("#ef-experience-fields");
  const projOrgNote = $("#ef-project-org-note");

  function showForm(kind, entry) {
    entry = entry || {};
    $("#entry-form-title").textContent =
      (entry.id ? "Edit " : "New ") + (kind === "experiences" ? "experience" : "project");
    $("#ef-id").value = entry.id || "";
    $("#ef-kind").value = kind;
    const isExp = kind === "experiences";
    projFields.hidden = isExp;
    projOrgNote.hidden = isExp;
    expFields.hidden = !isExp;
    $("#ef-name").value = entry.name || "";
    $("#ef-url").value = entry.url || "";
    $("#ef-p-company").value = entry.company || "";
    $("#ef-p-title").value = entry.title || "";
    $("#ef-company").value = entry.company || "";
    $("#ef-title").value = entry.title || "";
    $("#ef-location").value = entry.location || "";
    $("#ef-start").value = entry.start || "";
    $("#ef-end").value = entry.end || "";
    $("#ef-tags").value = (entry.tags || []).join(", ");
    $("#ef-bullets").value = (entry.bullets || []).map((b) => b.text).join("\n");
    $("#ef-status").textContent = "";
    form.hidden = false;
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function readForm() {
    const kind = $("#ef-kind").value;
    const tags = $("#ef-tags").value.split(",").map((t) => t.trim()).filter(Boolean);
    const bullets = $("#ef-bullets").value.split("\n")
      .map((t) => t.trim()).filter(Boolean).map((text) => ({ text }));
    const entry = { tags, bullets };
    if (kind === "experiences") {
      entry.company = $("#ef-company").value.trim();
      entry.title = $("#ef-title").value.trim();
      entry.location = $("#ef-location").value.trim();
      entry.start = $("#ef-start").value.trim();
      entry.end = $("#ef-end").value.trim() || null;
    } else {
      entry.name = $("#ef-name").value.trim();
      entry.url = $("#ef-url").value.trim();
      entry.company = $("#ef-p-company").value.trim();
      entry.title = $("#ef-p-title").value.trim();
    }
    const id = $("#ef-id").value;
    if (id) entry.id = id;
    return { kind, entry, id };
  }

  $("#add-project-btn").addEventListener("click", () => showForm("projects"));
  $("#add-experience-btn").addEventListener("click", () => showForm("experiences"));
  $("#ef-cancel").addEventListener("click", () => { form.hidden = true; });

  $("#ef-save").addEventListener("click", async () => {
    const { kind, entry, id } = readForm();
    const label = kind === "experiences" ? (entry.company || entry.title) : entry.name;
    if (!label) { toast("Give the entry a name or company first", true); return; }
    $("#ef-status").textContent = "Saving…";
    try {
      if (id) await send("/api/bank/" + id, "PUT", { entry });
      else await send("/api/bank", "POST", { kind, entry });
      window.location.reload();
    } catch (e) {
      $("#ef-status").textContent = "";
      toast(e.message, true);
    }
  });

  $("#ef-suggest-tags").addEventListener("click", async () => {
    const { entry } = readForm();
    $("#ef-status").textContent = "Thinking…";
    try {
      const { tags } = await send("/api/bank/suggest-tags", "POST", { entry });
      $("#ef-status").textContent = "";
      if (!tags.length) { toast("No tags suggested", false); return; }
      // merge with existing, de-duped, and let the user edit before saving
      const have = new Set($("#ef-tags").value.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean));
      const merged = Array.from(have);
      tags.forEach((t) => { if (!have.has(t.toLowerCase())) merged.push(t); });
      $("#ef-tags").value = merged.join(", ");
    } catch (e) {
      $("#ef-status").textContent = "";
      toast(e.message, true);
    }
  });

  // per-card actions (edit / delete / insert)
  document.querySelectorAll(".bank-entry").forEach((card) => {
    const id = card.dataset.id;
    const kind = card.dataset.kind;
    $(".bank-edit", card).addEventListener("click", () => showForm(kind, findEntry(id)));
    $(".bank-delete", card).addEventListener("click", async () => {
      if (!window.confirm("Delete this entry from the bank?")) return;
      try { await send("/api/bank/" + id, "DELETE"); window.location.reload(); }
      catch (e) { toast(e.message, true); }
    });
    $(".bank-insert", card).addEventListener("click", async () => {
      try {
        await send("/api/bank/insert", "POST", { id });
        toast("Inserted into your CV — open the Editor to review.", false);
      } catch (e) { toast(e.message, true); }
    });
  });
})();
