/* Reusable diff helpers, shared by every suggest-and-approve surface.
   No build step, no dependencies — a small LCS is all a personal CV tool needs.

   Exposes window.CVDiff:
     words(oldStr, newStr)          -> HTML: word-level inline diff of two strings
     unified(oldStr, newStr, opts)  -> HTML: git-style line diff, with word-level
                                       highlighting inside changed lines
   Both return escaped HTML safe to drop into innerHTML. */
(function () {
  "use strict";

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  // Longest-common-subsequence over an array of tokens -> a list of ops:
  //   {t: "eq"|"del"|"ins", v: token}
  // Classic DP; token counts here are tiny (a bullet, a YAML file), so the
  // O(n*m) table is fine and keeps the code readable.
  function diffTokens(a, b) {
    const n = a.length, m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = a[i] === b[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const ops = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { ops.push({ t: "eq", v: a[i] }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ t: "del", v: a[i] }); i++; }
      else { ops.push({ t: "ins", v: b[j] }); j++; }
    }
    while (i < n) ops.push({ t: "del", v: a[i++] });
    while (j < m) ops.push({ t: "ins", v: b[j++] });
    return ops;
  }

  // Split on whitespace but KEEP the whitespace as its own tokens, so joining
  // the ops back together reproduces the original spacing exactly.
  function splitWords(s) {
    return (s || "").split(/(\s+)/).filter((t) => t.length);
  }

  // Word-level inline diff of two strings. Runs of same-type ops are merged so
  // we emit one <del>/<ins> per changed phrase, not one per word.
  function words(oldStr, newStr) {
    const ops = diffTokens(splitWords(oldStr), splitWords(newStr));
    let html = "", run = "", runType = null;
    const flush = () => {
      if (!run) { runType = null; return; }
      const esc = escapeHtml(run);
      if (runType === "del") html += "<del>" + esc + "</del>";
      else if (runType === "ins") html += "<ins>" + esc + "</ins>";
      else html += esc;
      run = ""; runType = null;
    };
    ops.forEach((op) => {
      if (op.t !== runType) flush();
      runType = op.t;
      run += op.v;
    });
    flush();
    return '<span class="wdiff">' + html + "</span>";
  }

  // Unified (git-style) line diff. Changed lines get word-level highlighting;
  // pure adds/removes are shown whole. opts.context trims unchanged runs to N
  // lines on each side of a change (null/omitted = show everything).
  function unified(oldStr, newStr, opts) {
    opts = opts || {};
    const ops = diffTokens((oldStr || "").split("\n"), (newStr || "").split("\n"));

    // Pair an adjacent del-run with an ins-run so we can word-diff line i
    // against line i of the replacement (typical for an edited bullet/title).
    const rows = [];  // {t, html} where t in eq|del|ins|del-word|ins-word
    for (let k = 0; k < ops.length; k++) {
      const op = ops[k];
      if (op.t === "eq") { rows.push({ t: "eq", html: escapeHtml(op.v) }); continue; }
      if (op.t === "del") {
        // collect the del-run and the ins-run that follows it
        const dels = [op.v];
        while (k + 1 < ops.length && ops[k + 1].t === "del") dels.push(ops[++k].v);
        const inss = [];
        while (k + 1 < ops.length && ops[k + 1].t === "ins") inss.push(ops[++k].v);
        const paired = Math.min(dels.length, inss.length);
        for (let p = 0; p < paired; p++) {
          const w = words(dels[p], inss[p]);
          rows.push({ t: "del-word", html: stripIns(w) });
          rows.push({ t: "ins-word", html: stripDel(w) });
        }
        for (let p = paired; p < dels.length; p++) rows.push({ t: "del", html: escapeHtml(dels[p]) });
        for (let p = paired; p < inss.length; p++) rows.push({ t: "ins", html: escapeHtml(inss[p]) });
      } else { // a lone ins-run (no preceding del)
        rows.push({ t: "ins", html: escapeHtml(op.v) });
      }
    }

    const trimmed = opts.context == null ? rows : trimContext(rows, opts.context);
    const sign = { eq: " ", del: "-", ins: "+", "del-word": "-", "ins-word": "+" };
    const line = (r) => r === null
      ? '<div class="dline gap">⋯</div>'
      : '<div class="dline ' + r.t + '"><span class="sgn">' + sign[r.t] +
        "</span>" + r.html + "</div>";
    return '<div class="udiff">' + trimmed.map(line).join("") + "</div>";
  }

  // From a word-diff <span>, keep only the "old" side (drop <ins>, unwrap <del>)
  // or only the "new" side, so a paired change renders as two aligned lines.
  function stripIns(wdiffHtml) {
    return wdiffHtml.replace(/<ins>.*?<\/ins>/g, "").replace(/^<span class="wdiff">|<\/span>$/g, "");
  }
  function stripDel(wdiffHtml) {
    return wdiffHtml.replace(/<del>.*?<\/del>/g, "").replace(/^<span class="wdiff">|<\/span>$/g, "");
  }

  // Collapse runs of >2*context unchanged lines into a single "⋯" marker.
  function trimContext(rows, ctx) {
    const changed = rows.map((r) => r.t !== "eq");
    const keep = new Array(rows.length).fill(false);
    rows.forEach((r, i) => {
      if (!changed[i]) return;
      for (let d = -ctx; d <= ctx; d++) if (i + d >= 0 && i + d < rows.length) keep[i + d] = true;
    });
    const out = [];
    let gap = false;
    rows.forEach((r, i) => {
      if (keep[i]) { out.push(r); gap = false; }
      else if (!gap) { out.push(null); gap = true; }
    });
    return out;
  }

  // Strip machine-generated bookkeeping (bullet `id:` hashes) from a CV YAML
  // string so the whole-CV diff only shows content the user actually wrote.
  // Bullets dump as `- id: <hash>` then `  text: ...` on the next line; we drop
  // the id and fold the `-` list marker onto the text line, so the bullet reads
  // `- text: ...` and pairs cleanly instead of leaving an orphan `-` line.
  function stripBookkeeping(yamlStr) {
    const lines = (yamlStr || "").split("\n");
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/^(\s*)- id: \S+$/);
      const next = lines[i + 1];
      const nm = next != null ? next.match(/^(\s+)text: (.*)$/) : null;
      if (m && nm) {                       // `- id: X` immediately followed by `text:`
        out.push(m[1] + "- text: " + nm[2]);
        i++;                               // consume the text line too
      } else {
        out.push(lines[i]);
      }
    }
    return out.join("\n");
  }

  window.CVDiff = { words, unified, escapeHtml, stripBookkeeping };
})();
