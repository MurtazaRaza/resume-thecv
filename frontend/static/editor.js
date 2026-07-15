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
      section_order: $$("#order-list > .order-item").map((li) => li.dataset.key),
      section_spacing: $$("#order-list > .order-item").reduce((acc, li) => {
        const v = field(li, "spacing");
        if (v && v.value !== "") acc[li.dataset.key] = Number(v.value);
        return acc;
      }, {}),
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
      runAnalysis();
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

  // ---- left-pane tabs (form / yaml) ------------------------------------------
  let activeTab = "form";
  $$("[data-tab]").forEach((btn) => btn.addEventListener("click", async () => {
    activeTab = btn.dataset.tab;
    $$("[data-tab]").forEach((b) => b.classList.toggle("active", b === btn));
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

  // ---- right-pane tabs (preview / checks) ------------------------------------
  $$("[data-rtab]").forEach((btn) => btn.addEventListener("click", () => {
    const which = btn.dataset.rtab;
    $$("[data-rtab]").forEach((b) => b.classList.toggle("active", b === btn));
    $("#rtab-preview").hidden = which !== "preview";
    $("#rtab-checks").hidden = which !== "checks";
    if (which === "checks") runAnalysis();
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
    } else if (t.classList.contains("opt-bullet")) {
      optimizeBullet(t.closest(".bullet-row"));
    } else if (t.classList.contains("rm-bullet") || t.classList.contains("rm-row")) {
      t.closest(".bullet-row").remove();
    } else if (t.classList.contains("rm-entry")) {
      t.closest(".entry").remove();
    } else if (t.classList.contains("order-up")) {
      const li = t.closest(".order-item");
      if (li.previousElementSibling) li.parentNode.insertBefore(li, li.previousElementSibling);
    } else if (t.classList.contains("order-down")) {
      const li = t.closest(".order-item");
      if (li.nextElementSibling) li.parentNode.insertBefore(li.nextElementSibling, li);
    }
  });

  // ---- analyzer (Checks tab) --------------------------------------------------
  const CAT_ORDER = { error: 0, warn: 1, info: 2 };
  let analysisSeq = 0;

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function runAnalysis() {
    const seq = ++analysisSeq;
    const box = $("#findings");
    try {
      const resp = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(serialize()),
      });
      const data = await resp.json();
      if (seq !== analysisSeq) return; // a newer run superseded this one
      renderAtsScore(data.ats);
      renderFindings(data.findings || []);
    } catch (e) {
      if (seq === analysisSeq) box.innerHTML =
        '<p class="dropnote">Checks failed: ' + escapeHtml(e.message) + "</p>";
    }
  }

  function renderAtsScore(ats) {
    const card = $("#ats-score");
    if (!card) return;
    if (!ats || typeof ats.score !== "number") {
      card.hidden = true;
      return;
    }
    const bars = (ats.breakdown || []).map((b) => {
      const pct = Math.round((b.frac || 0) * 100);
      return (
        '<div class="ats-row">' +
        '<span class="ats-cat">' + escapeHtml(b.label) + "</span>" +
        '<span class="ats-track"><span class="ats-fill" style="width:' +
        pct + '%"></span></span>' +
        '<span class="ats-pts">' + b.earned + "/" + b.max + "</span></div>"
      );
    }).join("");
    card.className = "ats-card " + ats.band;
    card.innerHTML =
      '<div class="ats-head">' +
      '<div class="ats-num">' + ats.score + '<span class="ats-pct">%</span></div>' +
      '<div class="ats-title">ATS-friendliness' +
      '<span class="ats-sub">parse-ability &amp; resume hygiene</span></div>' +
      "</div>" +
      '<div class="ats-bars">' + bars + "</div>";
    card.hidden = false;
  }

  function renderFindings(findings) {
    const box = $("#findings");
    const badge = $("#checks-count");
    const actionable = findings.filter((f) => f.severity !== "info").length;
    if (actionable > 0) {
      badge.textContent = actionable;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
    if (!findings.length) {
      box.innerHTML = '<p class="checks-empty">✓ No issues found. Nice.</p>';
      return;
    }
    box.innerHTML = findings.map((f) => {
      const ids = f.bullet_ids || (f.bullet_id ? [f.bullet_id] : []);
      const cls = "finding " + f.severity + (ids.length ? " clickable" : "");
      const attr = ids.length ? ' data-bullets="' + ids.join(",") + '"' : "";
      return '<div class="' + cls + '"' + attr + '>' +
        '<span class="sev">' + f.severity + '</span>' +
        '<div><div>' + escapeHtml(f.message) + "</div>" +
        '<span class="cat">' + escapeHtml(f.category) + "</span></div></div>";
    }).join("");
  }

  // click a finding -> jump to & flash the first referenced bullet
  $("#findings").addEventListener("click", (e) => {
    const card = e.target.closest("[data-bullets]");
    if (!card) return;
    const firstId = card.dataset.bullets.split(",")[0];
    const idField = $$('#tab-form [data-f="id"]').find((el) => el.value === firstId);
    if (!idField) return;
    if (activeTab !== "form") $('[data-tab="form"]').click();
    const row = idField.closest(".bullet-row");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.remove("flash");
    void row.offsetWidth; // restart the animation
    row.classList.add("flash");
  });

  // ---- grammar pass (LLM) -----------------------------------------------------
  $("#run-grammar").addEventListener("click", async () => {
    const btn = $("#run-grammar");
    const section = $("#grammar-section").value;
    const gstatus = $("#grammar-status");
    const results = $("#grammar-results");
    btn.disabled = true;
    gstatus.innerHTML = '<span class="spinner"></span> checking…';
    results.innerHTML = "";
    try {
      const resp = await fetch("/api/analyze/grammar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cv: serialize(), section }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || resp.statusText);
      gstatus.textContent = "";
      if (data.empty) {
        results.innerHTML = '<p class="dropnote">That section is empty.</p>';
      } else if (!data.issues.length) {
        results.innerHTML = '<p class="checks-empty">✓ No grammar issues found.</p>';
      } else {
        results.innerHTML = data.issues.map((iss, i) =>
          '<div class="gissue" data-quote="' + escapeHtml(iss.quote).replace(/"/g, "&quot;") +
          '" data-fix="' + escapeHtml(iss.fix).replace(/"/g, "&quot;") + '">' +
          CVDiff.words(iss.quote, iss.fix) +
          (iss.issue ? ' <span class="issue-tag">(' + escapeHtml(iss.issue) + ")</span>" : "") +
          '<button type="button" class="btn btn-sm apply-grammar">Apply</button>' +
          "</div>").join("");
      }
    } catch (e) {
      gstatus.textContent = "";
      results.innerHTML = '<p class="dropnote">Grammar check failed: ' +
        escapeHtml(e.message) + "</p>";
    } finally {
      btn.disabled = false;
    }
  });

  // apply a grammar fix: find the first form field containing the quoted text
  // and splice in the fix. Suggest-and-approve — the user still has to Save.
  $("#grammar-results").addEventListener("click", (e) => {
    if (!e.target.classList.contains("apply-grammar")) return;
    const card = e.target.closest(".gissue");
    const quote = card.dataset.quote;
    const fix = card.dataset.fix;
    const fields = $$("#tab-form textarea, #tab-form input[type=text]");
    const target = fields.find((f) => f.value.includes(quote));
    if (!target) { toast("Couldn't locate that text — edit it by hand", true); return; }
    target.value = target.value.replace(quote, fix);
    target.dispatchEvent(new Event("input", { bubbles: true }));
    card.classList.add("applied");
    e.target.disabled = true;
    e.target.textContent = "Applied";
    toast("Applied — remember to Save");
  });

  // ---- per-bullet optimize popover -------------------------------------------
  let openPop = null;
  function closePop() { if (openPop) { openPop.remove(); openPop = null; } }
  document.addEventListener("click", (e) => {
    if (openPop && !openPop.contains(e.target) &&
        !e.target.classList.contains("opt-bullet")) closePop();
  });

  async function optimizeBullet(row) {
    closePop();
    const ta = field(row, "text");
    const text = ta.value.trim();
    if (!text) { toast("Write the bullet first", true); return; }

    const pop = document.createElement("div");
    pop.className = "opt-pop";
    pop.innerHTML = '<button type="button" class="btn-ghost close-x">✕</button>' +
      '<h4>Optimizing…</h4><p><span class="spinner"></span> asking the local model</p>';
    document.body.appendChild(pop);
    openPop = pop;
    positionPop(pop, row);
    pop.querySelector(".close-x").addEventListener("click", closePop);

    try {
      const resp = await fetch("/api/bullets/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || resp.statusText);
      if (openPop !== pop) return; // user closed it while waiting
      renderPop(pop, row, ta, data);
      positionPop(pop, row);
    } catch (e) {
      if (openPop === pop) pop.innerHTML =
        '<button type="button" class="btn-ghost close-x">✕</button>' +
        '<p class="dropnote">Failed: ' + escapeHtml(e.message) + "</p>";
      pop.querySelector(".close-x")?.addEventListener("click", closePop);
    }
  }

  function renderPop(pop, row, ta, data) {
    let html = '<button type="button" class="btn-ghost close-x">✕</button>';
    if (data.checks.length) {
      html += "<h4>Checks</h4>";
      html += data.checks.map((c) =>
        '<div class="opt-check">• ' + escapeHtml(c.message) + "</div>").join("");
    }
    if (data.suggestions.length) {
      const original = ta.value.trim();
      html += "<h4>Suggestions</h4>";
      data.suggestions.forEach((s, i) => {
        // metric-scaffold variants use [X%]/[N] placeholders — a word-diff
        // against the original just adds noise there, so only diff rewrites
        const showDiff = !/\[[^\]]+\]/.test(s.text);
        const body = showDiff ? CVDiff.words(original, s.text) : escapeHtml(s.text);
        html += '<div class="opt-suggestion"><div class="lbl">' +
          escapeHtml(s.label) + '</div><div class="txt">' + body +
          '</div><button type="button" class="btn btn-sm btn-primary apply-sug" ' +
          'data-i="' + i + '">Apply</button></div>';
      });
    } else if (!data.checks.length) {
      html += '<p class="none">✓ This bullet looks good.</p>';
    } else {
      html += '<p class="dropnote">No automatic rewrite — the model couldn\'t ' +
        "improve it without inventing facts.</p>";
    }
    pop.innerHTML = html;
    pop.querySelector(".close-x").addEventListener("click", closePop);
    pop.querySelectorAll(".apply-sug").forEach((b) => b.addEventListener("click", () => {
      ta.value = data.suggestions[+b.dataset.i].text;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      closePop();
      toast("Applied — remember to Save");
    }));
  }

  function positionPop(pop, row) {
    const r = row.getBoundingClientRect();
    const top = window.scrollY + r.bottom + 6;
    let left = window.scrollX + r.left;
    left = Math.min(left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 12);
    pop.style.top = top + "px";
    pop.style.left = Math.max(8, left) + "px";
  }

  // ---- summary + headline generator (M4, §5.3) -------------------------------
  async function genPost(url) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cv: serialize() }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  const genSummaryBtn = $("#gen-summary");
  if (genSummaryBtn) {
    genSummaryBtn.addEventListener("click", async () => {
      const status = $("#gen-summary-status");
      const list = $("#summary-variants");
      genSummaryBtn.disabled = true;
      status.textContent = "Asking the local model…";
      list.hidden = true;
      try {
        const data = await genPost("/api/summary/generate");
        const ta = field($("#sec-summary"), "summary");
        const current = ta.value.trim();
        list.innerHTML = data.variants.map((v, i) => {
          // if there's an existing summary, diff against it; else show plain
          const body = current ? CVDiff.words(current, v) : escapeHtml(v);
          return '<div class="variant"><div class="txt">' + body +
            '</div><button type="button" class="btn btn-sm btn-primary use-variant" ' +
            'data-i="' + i + '">Use this</button></div>';
        }).join("");
        list.hidden = false;
        list.querySelectorAll(".use-variant").forEach((b) =>
          b.addEventListener("click", () => {
            ta.value = data.variants[+b.dataset.i];
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            list.hidden = true;
            toast("Summary set — remember to Save");
          }));
        status.textContent = "";
      } catch (e) {
        status.textContent = "Failed: " + e.message;
      } finally {
        genSummaryBtn.disabled = false;
      }
    });
  }

  document.addEventListener("click", (e) => {
    if (!e.target.classList.contains("gen-headline")) return;
    closePop();
    const titleInput = field($("#sec-basics"), "title");
    const wrap = e.target.closest(".field-with-btn") || e.target.parentElement;
    const pop = document.createElement("div");
    pop.className = "opt-pop";
    pop.innerHTML = '<button type="button" class="btn-ghost close-x">✕</button>' +
      '<h4>Headline options</h4><p><span class="spinner"></span> asking the local model</p>';
    document.body.appendChild(pop);
    openPop = pop;
    positionPop(pop, wrap);
    pop.querySelector(".close-x").addEventListener("click", closePop);

    genPost("/api/headline/generate").then((data) => {
      if (openPop !== pop) return;
      let html = '<button type="button" class="btn-ghost close-x">✕</button>' +
        "<h4>Headline options</h4>";
      html += data.headlines.map((h, i) =>
        '<div class="opt-suggestion"><div class="txt">' + escapeHtml(h) +
        '</div><button type="button" class="btn btn-sm btn-primary use-head" ' +
        'data-i="' + i + '">Use</button></div>').join("");
      pop.innerHTML = html;
      pop.querySelector(".close-x").addEventListener("click", closePop);
      pop.querySelectorAll(".use-head").forEach((b) =>
        b.addEventListener("click", () => {
          titleInput.value = data.headlines[+b.dataset.i];
          titleInput.dispatchEvent(new Event("input", { bubbles: true }));
          closePop();
          toast("Headline set — remember to Save");
        }));
      positionPop(pop, wrap);
    }).catch((err) => {
      if (openPop !== pop) return;
      pop.innerHTML = '<button type="button" class="btn-ghost close-x">✕</button>' +
        '<p class="dropnote">Failed: ' + escapeHtml(err.message) + "</p>";
      pop.querySelector(".close-x").addEventListener("click", closePop);
    });
  });

  // initial preview + analysis
  refreshPreview();
  runAnalysis();
})();
