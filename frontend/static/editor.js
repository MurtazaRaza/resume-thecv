/* Editor: form <-> JSON serialization, save, YAML tab, live PDF preview.
   The backend is the source of truth: PUT /api/cv returns the normalized CV
   (with ids assigned to new bullets), which we write back into the DOM. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const field = (root, name) => root.querySelector('[data-f="' + name + '"]');
  const fval = (root, name) => {
    const el = field(root, name);
    return el ? el.value.trim() : "";
  };

  // ---- toast ----------------------------------------------------------------
  let toastTimer;
  function toast(msg, isError) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
  }

  // ---- serialize form -> CV object ------------------------------------------
  function bullets(entry) {
    return $$(".bullet-row", $(".bullets", entry)).map((row) => ({
      id: fval(row, "id"),
      text: fval(row, "text"),
    })).filter((b) => b.text);
  }

  function serialize() {
    const basics = $("#sec-basics");
    return {
      basics: {
        name: fval(basics, "name"),
        title: fval(basics, "title"),
        email: fval(basics, "email"),
        phone: fval(basics, "phone"),
        location: fval(basics, "location"),
        links: $$(".link-row", $("#links-list")).map((row) => ({
          label: fval(row, "label"), url: fval(row, "url"),
        })).filter((l) => l.label || l.url),
      },
      summary: fval($("#sec-summary"), "summary"),
      experience: $$("#exp-list > .entry").map((e) => ({
        company: fval(e, "company"), title: fval(e, "title"),
        location: fval(e, "location"), start: fval(e, "start"),
        end: fval(e, "end") || null, bullets: bullets(e),
      })),
      education: $$("#edu-list > .entry").map((e) => ({
        institution: fval(e, "institution"), degree: fval(e, "degree"),
        start: fval(e, "start"), end: fval(e, "end") || null,
        details: fval(e, "details"),
      })),
      skills: $$("#skill-list > .entry").map((e) => ({
        group: fval(e, "group"),
        items: fval(e, "items").split(",").map((s) => s.trim()).filter(Boolean),
      })).filter((s) => s.group || s.items.length),
      projects: $$("#proj-list > .entry").map((e) => ({
        name: fval(e, "name"), url: fval(e, "url"), bullets: bullets(e),
      })).filter((p) => p.name || p.bullets.length),
      certifications: $$("#cert-list > .entry").map((e) => ({
        name: fval(e, "name"), issuer: fval(e, "issuer"), date: fval(e, "date"),
      })).filter((c) => c.name),
    };
  }

  // write server-assigned bullet ids back into the DOM (order is preserved)
  function applyIds(cv) {
    [["#exp-list", cv.experience], ["#proj-list", cv.projects]].forEach(([sel, entries]) => {
      $$(sel + " > .entry").forEach((entryEl, i) => {
        if (!entries[i]) return;
        // only rows that serialized (non-empty text) got saved
        const rows = $$(".bullet-row", $(".bullets", entryEl))
          .filter((row) => fval(row, "text"));
        rows.forEach((row, j) => {
          if (entries[i].bullets[j]) field(row, "id").value = entries[i].bullets[j].id;
        });
      });
    });
  }

  // ---- preview ---------------------------------------------------------------
  const preview = $("#preview");
  async function refreshPreview() {
    if (!preview) return; // typst missing
    const resp = await fetch("/api/cv/render", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) { toast(data.error || "Render failed", true); return; }
    preview.src = data.pdf_url;
    $("#pdf-link").href = data.pdf_url;
    $("#txt-link").href = data.txt_url;
  }

  // ---- save ------------------------------------------------------------------
  const saveBtn = $("#save-btn");
  const status = $("#save-status");

  async function save() {
    saveBtn.disabled = true;
    status.textContent = "saving…";
    try {
      let resp;
      if (activeTab === "yaml") {
        resp = await fetch("/api/cv/yaml", { method: "PUT", body: $("#yaml-text").value });
        if (resp.ok) { location.reload(); return; }
      } else {
        resp = await fetch("/api/cv", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(serialize()),
        });
      }
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || resp.statusText);
      applyIds(data);
      status.textContent = "saved " + new Date().toLocaleTimeString();
      refreshPreview();
    } catch (e) {
      status.textContent = "";
      toast("Save failed: " + e.message, true);
    } finally {
      saveBtn.disabled = false;
    }
  }

  saveBtn.addEventListener("click", save);
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); }
  });

  // ---- tabs -------------------------------------------------------------------
  let activeTab = "form";
  $$(".tab").forEach((btn) => btn.addEventListener("click", async () => {
    activeTab = btn.dataset.tab;
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $("#tab-form").hidden = activeTab !== "form";
    $("#tab-yaml").hidden = activeTab !== "yaml";
    if (activeTab === "yaml") {
      // show YAML for the *current* form state without saving it
      const resp = await fetch("/api/cv/yaml/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serialize()),
      });
      $("#yaml-text").value = await resp.text();
    }
  }));

  // ---- add/remove entries -----------------------------------------------------
  function addFromTemplate(tplId, listSel) {
    const tpl = $("#" + tplId);
    const list = $(listSel);
    list.appendChild(tpl.content.cloneNode(true));
    const added = list.lastElementChild;
    const first = added.querySelector("input[type=text], textarea");
    if (first) first.focus();
    return added;
  }

  const ADD_MAP = { exp: "#exp-list", edu: "#edu-list", skill: "#skill-list",
                    proj: "#proj-list", cert: "#cert-list" };

  document.addEventListener("click", (e) => {
    const t = e.target;
    if (t.dataset && t.dataset.add) {
      addFromTemplate("tpl-" + t.dataset.add, ADD_MAP[t.dataset.add]);
    } else if (t.id === "add-link") {
      addFromTemplate("tpl-link", "#links-list");
    } else if (t.classList.contains("add-bullet")) {
      const holder = $(".bullets", t.closest(".entry"));
      holder.appendChild($("#tpl-bullet").content.cloneNode(true));
      holder.lastElementChild.querySelector("textarea").focus();
    } else if (t.classList.contains("rm-bullet") || t.classList.contains("rm-row")) {
      t.closest(".bullet-row").remove();
    } else if (t.classList.contains("rm-entry")) {
      t.closest(".entry").remove();
    }
  });

  // auto-grow bullet textareas
  document.addEventListener("input", (e) => {
    if (e.target.matches(".bullet-row textarea")) {
      e.target.style.height = "auto";
      e.target.style.height = e.target.scrollHeight + "px";
    }
  });

  // initial preview
  refreshPreview();
})();
