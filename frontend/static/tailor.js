/* Tailor page (SPEC §5.1): extract & match -> skills gap + rewrite
   suggestions -> save a tailored snapshot. Suggest-and-approve throughout:
   only explicitly accepted changes reach the snapshot; cv.yaml is untouched. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);

  let applicationId = null;
  let suggestions = [];        // [{bullet_id, keyword, role, original, rewrite}]
  const accepted = new Set();  // indices into `suggestions`

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

  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
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

  async function getJson(url) {
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data;
  }

  // ---- live preview ----------------------------------------------------------
  // The current tailoring choices, POSTed to /api/tailor/preview. accepted[i]
  // carries the user's (possibly edited) rewrite text, so the diff and a save
  // stay byte-identical (both go through apply_tailoring server-side).
  function tailoringChoices() {
    return {
      application_id: applicationId,
      accepted: Array.from(accepted).map((i) => ({
        id: suggestions[i].bullet_id, text: suggestions[i].rewrite })),
      add_skills: Array.from(document.querySelectorAll(".gap-skill:checked"))
        .map((cb) => cb.value),
      skills_group: ($("#gap-group") || {}).value || "",
      new_title: $("#title-swap") && $("#title-swap").checked
        ? $("#title-swap-row").dataset.target : "",
    };
  }

  let previewTimer;
  let lastTailoredYaml = "";  // kept for the "Full YAML" tab
  function refreshPreview() {
    if (!applicationId) return;
    $("#preview-pane").hidden = false;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      const status = $("#preview-status");
      status.textContent = "updating…";
      try {
        const resp = await fetch("/api/tailor/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(tailoringChoices()),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || resp.statusText);
        lastTailoredYaml = data.tailored_yaml;
        $("#preview-yaml").value = lastTailoredYaml;
        const diff = $("#preview-diff");
        if (data.master_yaml === data.tailored_yaml) {
          diff.innerHTML = '<p class="diff-empty">No changes yet — accept a ' +
            "rewrite, swap the title, or add a gap skill to see the diff.</p>";
        } else {
          // Diff only user-authored content: drop bullet `id:` bookkeeping so
          // the hashes never surface as meaningless diff lines. The "Full YAML"
          // tab still shows the raw tailored_yaml, ids included.
          diff.innerHTML = CVDiff.unified(
            CVDiff.stripBookkeeping(data.master_yaml),
            CVDiff.stripBookkeeping(data.tailored_yaml),
            { context: 2 });
        }
        status.textContent = "";
      } catch (e) {
        status.textContent = "preview failed";
      }
    }, 200);
  }

  // preview sub-tabs: unified diff vs. the whole tailored YAML
  document.querySelectorAll("[data-ptab]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const which = btn.dataset.ptab;
      document.querySelectorAll("[data-ptab]").forEach((b) =>
        b.classList.toggle("active", b === btn));
      $("#preview-diff").hidden = which !== "diff";
      $("#preview-yaml").hidden = which !== "yaml";
    }));

  function spinner(label) {
    return '<span class="spinner" style="border-color:#999;border-top-color:transparent"></span> ' + label;
  }

  // ---- step 1: extract & match -----------------------------------------------
  // Reveal the match/suggest/apply panes and reset per-run state from a payload
  // (used by both a fresh extract and reloading a saved application).
  function applyPayload(data) {
    applicationId = data.application_id;
    renderMatch(data);
    suggestions = [];
    accepted.clear();
    $("#suggestions").innerHTML = "";
    $("#suggest-status").textContent = "";
    $("#apply-result").hidden = true;
    $("#match-pane").hidden = false;
    $("#suggest-pane").hidden = false;
    $("#apply-pane").hidden = false;
    refreshPreview();
  }

  $("#app-select").addEventListener("change", async () => {
    const val = $("#app-select").value;
    $("#new-app-fields").hidden = !!val;
    if (!val) return;
    // reload the saved JD + cached match without re-running the model
    const status = $("#extract-status");
    status.innerHTML = spinner("Loading saved application…");
    try {
      const data = await getJson("/api/tailor/application/" + val);
      $("#jd-text").value = data.jd_text;
      status.textContent = "";
      applyPayload(data);
      $("#match-pane").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      status.textContent = "";
      // no cached extraction yet (e.g. an app created elsewhere): let the user
      // paste/extract normally rather than erroring hard
      if (!/extract/i.test(e.message)) toast("Load failed: " + e.message, true);
    }
  });

  $("#extract-btn").addEventListener("click", async () => {
    const btn = $("#extract-btn");
    const status = $("#extract-status");
    const body = { jd_text: $("#jd-text").value };
    if ($("#app-select").value) {
      body.application_id = +$("#app-select").value;
    } else {
      body.company = $("#jd-company").value;
      body.role = $("#jd-role").value;
      body.url = $("#jd-url").value;
    }
    btn.disabled = true;
    status.innerHTML = spinner("Extracting with the local model…");
    try {
      const data = await post("/api/tailor/extract", body);
      // a fresh extract created a tracker entry: select it so re-running
      // (e.g. after tweaking the JD) updates it instead of creating a twin
      const sel = $("#app-select");
      if (!sel.value) {
        const opt = document.createElement("option");
        opt.value = String(data.application_id);
        opt.textContent = data.company + " — " + ($("#jd-role").value || "role") + " (saved)";
        sel.appendChild(opt);
        sel.value = opt.value;
        $("#new-app-fields").hidden = true;
      }
      status.textContent = "";
      applyPayload(data);
      $("#match-pane").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      status.textContent = "";
      toast("Extraction failed: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  function chips(items, cls) {
    if (!items.length) return '<span class="dropnote">none</span>';
    return items.map((k) => '<span class="chip ' + cls + '">' + escapeHtml(k) + "</span>").join("");
  }

  function renderMatch(data) {
    const m = data.match;
    $("#coverage-label").textContent = "match score: " + m.coverage + "%";
    const fill = $("#coverage-fill");
    fill.style.width = m.coverage + "%";
    fill.className = "coverage-fill " +
      (m.coverage >= 70 ? "good" : m.coverage >= 40 ? "mid" : "low");

    $("#covered-chips").innerHTML = chips(m.covered, "ok");
    $("#missing-chips").innerHTML = chips(m.missing, "miss");

    const soft = [];
    if (m.soft_covered.length) soft.push("covered: " + m.soft_covered.join(", "));
    if (m.soft_missing.length) soft.push("not found: " + m.soft_missing.join(", "));
    $("#soft-line").innerHTML = soft.length
      ? "<strong>Soft skills</strong> (not scored) — " + escapeHtml(soft.join(" · "))
      : "";

    const quals = data.extraction.must_have_qualifications;
    $("#musthaves").innerHTML = quals.length
      ? '<h4 class="subhead">Must-have qualifications (from the JD)</h4><ul class="qual-list">' +
        quals.map((q) => "<li>" + escapeHtml(q) + "</li>").join("") + "</ul>"
      : "";

    const target = data.extraction.target_title;
    const row = $("#title-swap-row");
    if (target && target.toLowerCase() !== (data.current_title || "").toLowerCase()) {
      $("#target-title").textContent = target;
      $("#current-title").textContent = data.current_title || "—";
      $("#title-swap").checked = false;
      row.hidden = false;
    } else {
      row.hidden = true;
    }
    row.dataset.target = target || "";

    const gap = m.skills_gap;
    $("#gap-block").hidden = !gap.length;
    $("#gap-list").innerHTML = gap.map((s) =>
      '<label class="checkline"><input type="checkbox" class="gap-skill" value="' +
      escapeAttr(s) + '"> ' + escapeHtml(s) + "</label>").join("");
  }

  // ---- step 3: suggestions -----------------------------------------------------
  $("#suggest-btn").addEventListener("click", async () => {
    const btn = $("#suggest-btn");
    const status = $("#suggest-status");
    btn.disabled = true;
    status.innerHTML = spinner("Rewriting related bullets one by one — this can take a few minutes…");
    try {
      const data = await post("/api/tailor/suggest", {
        application_id: applicationId,
        guidance: $("#suggest-guidance").value,
      });
      suggestions = data.suggestions;
      accepted.clear();
      status.textContent = "";
      renderSuggestions(data);
      refreshPreview();  // cleared any prior acceptances
    } catch (e) {
      status.textContent = "";
      toast("Suggestions failed: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  function renderSuggestions(data) {
    const box = $("#suggestions");
    if (!suggestions.length) {
      box.innerHTML = '<p class="dropnote">No truthful rewrites found' +
        (data.attempted ? " (the model declined " + data.attempted +
          " candidate" + (data.attempted > 1 ? "s" : "") +
          " rather than invent experience)" : " — no bullets relate to the missing keywords") +
        ".</p>";
    } else {
      // remember the model's untouched rewrite so "dirty" = user changed it
      suggestions.forEach((s) => { if (s.suggested == null) s.suggested = s.rewrite; });
      box.innerHTML = suggestions.map((s, i) =>
        '<div class="sug-card" data-i="' + i + '">' +
        '<div class="sug-meta"><span class="chip miss">' + escapeHtml(s.keyword) +
        '</span><span class="dropnote">' + escapeHtml(s.role) + "</span></div>" +
        '<div class="sug-texts">' + CVDiff.words(s.original, s.rewrite) + "</div>" +
        '<textarea class="diff-edit" rows="2">' + escapeHtml(s.rewrite) + "</textarea>" +
        '<div class="sug-actions">' +
        '<button type="button" class="btn btn-sm sug-accept">✓ Accept</button>' +
        '<button type="button" class="btn btn-sm sug-reject">✕ Reject</button>' +
        "</div></div>").join("");
    }
    if (data.errors && data.errors.length) {
      box.innerHTML += '<p class="dropnote">⚠ ' + data.errors.length +
        " rewrite call(s) failed and were skipped.</p>";
    }
  }

  $("#suggestions").addEventListener("click", (e) => {
    const card = e.target.closest(".sug-card");
    if (!card) return;
    const i = +card.dataset.i;
    if (e.target.classList.contains("sug-accept")) {
      // accept the *edited* text — the textarea is the source of truth
      suggestions[i].rewrite = $(".diff-edit", card).value.trim();
      accepted.add(i);
      card.classList.add("accepted");
      card.classList.remove("rejected");
    } else if (e.target.classList.contains("sug-reject")) {
      accepted.delete(i);
      card.classList.add("rejected");
      card.classList.remove("accepted");
    } else {
      return;
    }
    refreshPreview();
  });

  // live word-diff as the user tweaks a rewrite; re-preview if already accepted
  $("#suggestions").addEventListener("input", (e) => {
    if (!e.target.classList.contains("diff-edit")) return;
    const card = e.target.closest(".sug-card");
    const i = +card.dataset.i;
    const edited = e.target.value;
    e.target.classList.toggle("dirty", edited.trim() !== suggestions[i].suggested);
    $(".sug-texts", card).innerHTML = CVDiff.words(suggestions[i].original, edited);
    if (accepted.has(i)) {
      suggestions[i].rewrite = edited.trim();
      refreshPreview();
    }
  });

  // any tailoring toggle (title swap, gap-skill checkboxes) refreshes the preview
  $("#match-pane").addEventListener("change", (e) => {
    if (e.target.id === "title-swap" || e.target.classList.contains("gap-skill")
        || e.target.id === "gap-group") {
      refreshPreview();
    }
  });

  // ---- step 4: apply -------------------------------------------------------------
  $("#apply-btn").addEventListener("click", async () => {
    const btn = $("#apply-btn");
    const status = $("#apply-status");
    const body = tailoringChoices();
    const addSkills = body.add_skills;
    btn.disabled = true;
    status.innerHTML = spinner("Saving…");
    try {
      const data = await post("/api/tailor/apply", body);
      status.textContent = "";
      const result = $("#apply-result");
      result.hidden = false;
      result.innerHTML =
        "✓ Saved <code>" + escapeHtml(data.snapshot) + "</code><br>" +
        "Match score: <strong>" + data.coverage_before + "% → " +
        data.coverage_after + "%</strong> (" + body.accepted.length +
        " bullet rewrite" + (body.accepted.length === 1 ? "" : "s") + ", " +
        addSkills.length + " skill" + (addSkills.length === 1 ? "" : "s") + " added)";
      toast("Tailored version saved");
    } catch (e) {
      status.textContent = "";
      toast("Save failed: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  // Deep link from the tracker detail page: /tailor?app=<id> pre-selects that
  // application and loads its cached JD + match (if the option exists).
  const preId = new URLSearchParams(window.location.search).get("app");
  if (preId) {
    const sel = $("#app-select");
    if ([...sel.options].some((o) => o.value === preId)) {
      sel.value = preId;
      sel.dispatchEvent(new Event("change"));
    }
  }
})();
