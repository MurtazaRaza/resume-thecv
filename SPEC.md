# Resume the CV — Specification & Implementation Plan

A personal, local-first resume tool inspired by Enhancv. Runs entirely on this machine
(M1 MacBook Air, 8 GB RAM) using small local LLMs via Ollama, with a provider
abstraction so a cloud API (e.g. Claude Haiku) can be plugged in later.

---

## 1. Goals & Non-Goals

### Goals
- Edit a single canonical CV in a structured format, with live preview.
- Produce **ATS-friendly** output: single-column PDF with real text, plus a plain-text export.
- Seven features, all decomposed into small, single-purpose LLM calls that a 3–4B model can handle:
  1. One-click job tailoring (incl. skills-gap suggestions + match score)
  2. Bullet point optimizer
  3. Resume summary generator (+ headline/title line)
  4. Integrated content analyzer
  5. Cover letter generator
  6. Job application tracker
  7. Interview prep kit (likely questions, STAR stories, personal pitch)
- Every LLM suggestion is **suggest-and-approve**: nothing is auto-applied to the CV.
- Zero cloud dependency by default; zero cost to run.

### Non-Goals (for now)
- Multi-user support, auth, hosting.
- Visual/designer resume templates (conflicts with ATS goal).
- Scraping job boards (JD is pasted in; URL fetch is a later nice-to-have).
- .docx export (later nice-to-have via python-docx; docx *import* IS in scope, §4).
- Company-research briefs for interview prep (needs web scraping; notes field instead).
- Voice mock interviews, translation, browser extensions (Enhancv features that need
  cloud scale or heavier models than this machine can run).

---

## 2. Hard Constraints & Design Consequences

| Constraint | Consequence |
|---|---|
| 8 GB RAM, M1 | Max one ~3–4B model loaded at a time. `num_ctx` capped at 4096. No parallel LLM calls. |
| Small model quality | Never send the whole CV + JD in one prompt. Decompose: extract → match → per-bullet rewrite. Deterministic rules do everything they can before an LLM is involved. |
| ATS output | Single column, standard section headers, common font, no tables/columns/icons/images in the PDF. Plain-text export for web forms. |
| Local-first, extensible | `LLMProvider` interface; `OllamaProvider` now, `AnthropicProvider` stub later. All prompts live in one module, independent of provider. |

**Recommended model:** `qwen2.5:3b-instruct` (~1.9 GB, strong JSON/instruction-following).
Fallback: already-installed `llama3.2:3b`. Model name is a config value, not hardcoded.

---

## 3. Architecture

- **Backend:** Python + FastAPI, served with uvicorn on `localhost:8877`.
- **Frontend:** Server-rendered Jinja2 templates + htmx + a small amount of vanilla JS.
  No node toolchain, no build step. htmx vendored locally (single file in `static/`).
- **PDF rendering:** [Typst](https://typst.app) CLI (`brew install typst`), invoked via
  `subprocess`. Compiles in ~100 ms, single static binary, far lighter than LaTeX.
- **Storage:**
  - CV data: YAML files on disk (human-editable outside the app too).
  - Tracker: SQLite (stdlib `sqlite3`, thin data-access layer — no ORM).
- **LLM:** Ollama HTTP API (`http://localhost:11434/api/chat`) with `format: "json"`
  for structured outputs. Talked to via `httpx`.

### Project layout

Backend and frontend are strictly separated at the top level: `backend/` is
Python only, `frontend/` is templates/CSS/JS only. All dependencies are
project-local: Python packages live in `.venv/`, htmx is a vendored file
(no node/npm at all), and the Typst binary lives in `tools/` (no brew needed).

```
resume-the-cv/
├── SPEC.md
├── requirements.txt          # fastapi, uvicorn, jinja2, httpx, pyyaml, python-multipart, pypdf, python-docx
├── run.sh                    # starts uvicorn from .venv on :8877
├── .venv/                    # project-local Python env (gitignored)
├── tools/                    # project-local typst binary (gitignored)
├── backend/                  # ALL Python code
│   ├── main.py               # FastAPI app, routes
│   ├── config.py             # model name, paths, ollama URL, num_ctx
│   ├── llm/
│   │   ├── provider.py       # LLMProvider ABC + AnthropicProvider stub + get_provider()
│   │   ├── ollama.py         # OllamaProvider
│   │   └── prompts.py        # ALL system prompts (see §6)
│   └── core/
│       ├── cv_model.py       # schema normalization + YAML load/save + bullet IDs
│       ├── analyzer.py       # deterministic rules engine (§5.4)          [M2]
│       ├── optimizer.py      # bullet checks + rewrite orchestration (§5.2) [M2]
│       ├── tailor.py         # JD extraction + keyword matching + rewrites (§5.1) [M3]
│       ├── summary.py        # §5.3                                       [M4]
│       ├── cover_letter.py   # §5.5                                       [M4]
│       ├── interview.py      # questions, STAR stories, pitch (§5.7)      [M6]
│       ├── importer.py       # PDF/DOCX/text → YAML onboarding (§4)
│       ├── render.py         # typst compile, plain-text export
│       └── tracker.py        # sqlite DAO (§5.6; schema exists from M1)
├── frontend/                 # ALL UI code (server-rendered, no build step)
│   ├── templates/            # Jinja2: base, editor, import; tailor/tracker/letters later
│   └── static/               # style.css, editor.js, vendor/htmx.min.js
├── typst/
│   ├── cv.typ                # ATS-safe resume template
│   └── letter.typ            # cover letter template                      [M4]
└── data/                     # personal data, gitignored
    ├── cv.yaml               # canonical CV (single source of truth)
    ├── versions/             # tailored snapshots + pre-import backups
    ├── letters/              # generated cover letters (.md + .pdf)
    ├── out/                  # compiled PDFs / .txt exports
    └── tracker.db
```

---

## 4. CV Data Model (`data/cv.yaml`)

Structured so every bullet is individually addressable (stable `id` = 6-char hash
assigned on save). This is what makes per-bullet LLM ops, diffs, and version
comparison possible.

```yaml
basics:
  name: ""
  title: ""            # current/target title
  email: ""
  phone: ""
  location: ""
  links: [{label: GitHub, url: ""}]
summary: ""
experience:
  - company: ""
    title: ""
    location: ""
    start: 2022-04     # YYYY-MM; end: null means "Present"
    end: null
    bullets:
      - id: a3f9c1
        text: ""
education:
  - {institution: "", degree: "", start: 2018-09, end: 2022-06, details: ""}
skills:
  - group: Languages
    items: [Python, TypeScript]
projects:
  - {name: "", url: "", bullets: [{id: "", text: ""}]}
certifications:
  - {name: "", issuer: "", date: 2024-01}
```

**Onboarding:** first run shows an import page — upload a PDF/DOCX (text extracted via
`pypdf` / `python-docx`) or paste raw text (works for LinkedIn profile copy-paste too).
Deterministic pre-split into sections by header keywords, then one LLM call per section
converts it to this schema; user fixes anything wrong in the editor.

**Versioning:** `data/cv.yaml` is the master. "Tailor for job X" writes a snapshot to
`data/versions/` linked to the tracker entry; the master is only changed through the
editor. Snapshots are full YAML copies (cheap, diffable with any tool).

---

## 5. Feature Specifications

### 5.1 One-Click Job Tailoring
**Page:** `/tailor` — paste JD, pick/create tracker entry, run.

Pipeline (each step small enough for a 3B model):
1. **Extract (LLM → JSON):** JD text → `{target_title, hard_skills[], soft_skills[],
   keywords[], action_verbs[], must_have_qualifications[]}`. JDs longer than ~3000
   words are truncated to the requirements/responsibilities sections first
   (deterministic heuristic: keep paragraphs containing requirement-signal words).
2. **Match (deterministic):** case-insensitive + simple-plural matching of extracted
   keywords against CV text → *covered* / *missing* lists + coverage %.
3. **Suggest (LLM, per bullet):** for each experience bullet that plausibly relates to
   a missing keyword (word-overlap heuristic picks candidates, max ~10 calls), ask for
   a rewrite that works the keyword in **only if truthful to the original meaning**;
   model must return `null` when it can't do that honestly.
4. **Skills gap (deterministic + user confirmation):** JD hard skills absent from the
   CV are listed as "Do you actually have these?" checkboxes — checked ones are added
   to the matching skill group. Never added silently; unchecked ones stay a visible
   gap in the coverage report. Existing skills reordered so JD-matched items come first.
5. **Review UI:** side-by-side diff per suggestion, Accept/Reject each. Also offers:
   swap `basics.title` to target title.
6. **Save:** accepted changes → snapshot in `data/versions/`, linked to tracker entry.
   Coverage % before/after stored on the application as its **match score**, shown on
   the tracker dashboard (§5.6).

### 5.2 Bullet Point Optimizer
**Where:** inline in the editor (per-bullet "optimize" button) + "check all" sweep.

**Deterministic checks (no LLM, instant):**
- Too long: > 28 words or > ~180 chars.
- Generic filler: matches curated phrase list (`responsible for`, `worked on`,
  `helped with`, `assisted in`, `duties included`, `various`, `successfully`,
  `team player`, …).
- Missing metric: no digit/%/$ present → flag "add a number".
- Doesn't start with an action verb (POS-free heuristic: first word in weak-starter list
  or ends in "-ing").
- Repeated leading verb across bullets in the same role.

**LLM step (per bullet, only on request):** return JSON with up to 2 rewrites:
one *tightened* (shorter, stronger verb, filler removed) and — when the metric flag is
set — one *metric-scaffold* variant using explicit placeholders like `[X%]` / `[N users]`
that the user fills in. Placeholders, never invented numbers.

### 5.3 Resume Summary Generator
**Page:** editor sidebar → "Generate summary".

- Deterministic pre-compute: years of experience (from dates), current title, top skill
  groups, 3 strongest bullets (prefer ones containing metrics).
- One LLM call using only that pre-computed digest (not the whole CV) + optional JD
  extraction from §5.1 → **3 variants**, 2–3 sentences each, no first-person pronouns,
  no clichés (prompt includes a banned-word list).
- User picks a variant, edits inline, saves to `summary`.
- **Headline generator:** same digest, separate tiny call → 3 title-line options for
  `basics.title` (e.g. "Backend Engineer · Python · Distributed Systems"), constrained
  to plain text, no pipes/emojis that would trip an ATS.

### 5.4 Integrated Content Analyzer
**Where:** persistent sidebar panel in the editor; re-runs debounced on every save.
Deterministic-first: the rules engine is instant and free; LLM grammar check is a
button, not automatic.

**Rules engine (pure Python, `analyzer.py`):**
| Check | Severity |
|---|---|
| Date issues: overlaps, gaps > 6 months, end-before-start, non-current role with no end | warn |
| Tense: present-tense verbs in ended roles / past-tense in current role (verb-list heuristic) | warn |
| Consistency: bullet end-punctuation mixed; date format mixed; Oxford-comma mixed in skills | info |
| Repetition: same significant word ≥ 3× across bullets; near-duplicate bullets (token overlap > 70%) | warn |
| ATS red flags: emojis, unusual unicode, images referenced, very long skill lists (> 20/group) | error |
| Bias/age signals: graduation year > 15 yrs back shown, gendered terms, "young/energetic", photos, marital status | warn |
| Readability: avg words-per-bullet, sentence length in summary, jargon density (acronyms without expansion) | info |
| Completeness: empty summary, role with < 2 bullets, missing contact fields | info |
| All §5.2 deterministic bullet checks, aggregated | info |

**LLM grammar pass (on demand):** one call per section, returns JSON list of
`{quote, issue, fix}`; UI shows them anchored to the matching text.

### 5.5 Cover Letter Generator
**Page:** `/letters/new` — pick tracker entry (brings its JD extraction), set tone
(professional / warm / direct), add optional "points to emphasize".

Small-model-safe pipeline:
1. **Outline (LLM → JSON):** 4 beats — hook, fit paragraph 1 (maps 2 CV achievements
   to top JD requirements), fit paragraph 2, close. Input is the JD extraction + the
   summary digest from §5.3, not raw documents.
2. **Draft (LLM, one call per beat):** each call gets only its beat + the 1–2 relevant
   CV achievements. Keeps every call well inside a 3B model's competence.
3. **Assemble + edit:** stitched into an editable textarea; nothing is sent anywhere.
4. **Export:** `typst/letter.typ` → PDF; saved to `data/letters/`, linked to the
   tracker entry.

### 5.6 Job Application Tracker
**Page:** `/tracker` — the app's home page. No LLM involvement.

SQLite schema:
```sql
CREATE TABLE applications (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL,
  role TEXT NOT NULL,
  url TEXT,
  jd_text TEXT,
  jd_extraction TEXT,          -- cached JSON from §5.1 step 1
  status TEXT NOT NULL DEFAULT 'saved',
      -- saved | applied | screening | interview | offer | rejected | withdrawn
  applied_date TEXT,
  cv_version_path TEXT,        -- data/versions/...
  cover_letter_path TEXT,      -- data/letters/...
  notes TEXT,                  -- markdown: interview notes, contacts, prep
  next_action TEXT,
  next_action_date TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE status_history (
  id INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES applications(id),
  status TEXT, changed_at TEXT
);
```

Add columns: `match_score INTEGER` (coverage % from §5.1) and `interview_prep TEXT`
(JSON blob from §5.7).

Dashboard: table grouped by status with counts, match score per row; overdue
`next_action_date` highlighted.
Detail page: JD, notes editor, links to the exact CV version + letter PDFs used,
status history, one-click "Tailor CV for this job" (jumps to §5.1 pre-filled), and the
interview prep kit (§5.7).

### 5.7 Interview Prep Kit
**Where:** tab on the tracker application detail page. Requires the cached JD
extraction; everything is generated per application and stored on it.

Three independent generators (each its own button, each small-model-sized):
1. **Likely questions (LLM → JSON):** JD extraction + role title → ~10 questions in
   two groups, *expertise fit* (from hard skills/qualifications) and *culture fit*
   (from soft skills/company signals in the JD). Stored with a free-text answer field
   the user fills during prep.
2. **STAR stories (LLM, per bullet):** user picks 2–4 of their strongest CV bullets;
   one call per bullet expands it into a Situation/Task/Action/Result outline the user
   edits. Prompt rule: only elaborate structure, never invent events — put `[fill in]`
   where the CV lacks detail.
3. **Personal pitch (LLM):** the §5.3 digest + target role → a ~60-second
   "tell me about yourself" draft, editable.

Company research stays manual: the `notes` field is the home for it (non-goal: scraping).

### 5.8 Suggestion Review UI (cross-cutting)
The app's core promise (§1) is that **every LLM suggestion is suggest-and-approve**.
That promise is only as good as how legible the review is, so all suggestion
surfaces share one review vocabulary instead of each inventing its own — a single
vendored, dependency-free helper (`static/diff.js`, exposes `window.CVDiff`) that
does word-level and unified diffing with a tiny LCS (no build step, no CDN; the
text is bullet- or CV-sized, so an O(n·m) table is fine). Diffing is pure
client-side JS: zero LLM calls, zero extra memory pressure.

- **Word-level diff** — changed words highlighted in place (not two full
  strikethrough copies) so a 2-word edit reads in a glance. Used by tailor bullet
  cards, the editor bullet-optimize popover, grammar fixes, and summary variants
  (each variant diffed against the current summary). Metric-scaffold rewrites
  (`[X%]` placeholders) skip the diff — it would just be noise.
- **Editable target** — on the tailor page a suggestion's rewrite lands in an
  editable field; the word-diff re-renders live as you tweak it, and Accept saves
  *your edited text*, not the raw model output. Removes the all-or-nothing feel
  while keeping human approval mandatory. The model's untouched suggestion is
  remembered so an edited field is marked dirty.
- **Whole-CV unified diff** — the tailor live preview shows a git-style unified
  diff of master-vs-tailored YAML (inline, word-highlighted inside changed lines,
  ±2 lines of context), so before a snapshot is saved every net change is visible
  at once. A "Full YAML" sub-tab still shows the complete tailored document.
- **Apply, everywhere** — grammar fixes gained an Apply button they previously
  lacked (locate the quoted text in a form field, splice in the fix; still needs
  a manual Save). Consistency: no surface shows a suggestion the user can't act on.

Deliberately NOT a CodeMirror/Monaco-style editor: that needs npm or a CDN
(violates the vendored/no-build constraint) and is overkill for bullet-sized text.

---

## 6. LLM Layer

### Provider interface (`llm/provider.py`)
```python
class LLMProvider(ABC):
    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, max_tokens: int = 800) -> str: ...
```
- `OllamaProvider`: POST `/api/chat`, `options: {num_ctx: 4096, temperature}`,
  `format: "json"` when `json_mode`. 120 s timeout. On invalid JSON: one retry with the
  error appended; then surface a friendly failure in the UI (never crash a page).
- `AnthropicProvider`: stub raising `NotImplementedError`, wired to config key
  `provider: ollama | anthropic` so enabling it later is a config change + one class.

### Prompt principles (all prompts in `llm/prompts.py`)
- One narrow task per prompt; explicit JSON schema in the system prompt; one worked
  example (few-shot) each — small models need it.
- Hard honesty rules stated in every rewrite prompt: *never invent facts, numbers,
  employers, or technologies; return null if a truthful rewrite is impossible.*
- Word/sentence limits stated numerically ("max 25 words"), not vaguely.

Example — JD extraction system prompt (abridged):
> You extract structured data from job descriptions. Respond with ONLY valid JSON
> matching: {"target_title": str, "hard_skills": [str], "soft_skills": [str],
> "keywords": [str], "action_verbs": [str], "must_have_qualifications": [str]}.
> hard_skills = technologies/tools/methods explicitly named. keywords = other terms an
> ATS would match. Max 15 items per list. No commentary.

---

## 7. Rendering (`core/render.py` + `typst/cv.typ`)

ATS rules baked into the template:
- Single column, no tables/grids for layout, no icons/photos/graphics.
- Standard headers exactly: *Summary, Experience, Education, Skills, Projects, Certifications*.
- Font: Helvetica (system) or Typst-bundled Libertinus; 10–11 pt; dates as plain text
  on the same line as the role (`Software Engineer, Acme — Apr 2022 – Present`).
- Bullets as plain `•` list items.

Flow: YAML → Python dict → written to a temp `.json` → `typst compile cv.typ
--input data=<path> out.pdf`. Also emits `out/cv.txt` — a plain-text rendering for
paste-into-form ATS portals — from the same data.

Preview: editor's right pane shows the compiled PDF in an `<embed>`, refreshed on save
(compile is fast enough to feel live).

---

## 8. HTTP API (internal, consumed by htmx)

Status: ✅ = implemented (M1–M4). Others are planned for their milestone.

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | ✅ Redirects to /import (empty CV) or /editor |
| `/editor` | GET | ✅ CV editor (form + YAML tab + preview + Checks tab) |
| `/import` | GET | ✅ Onboarding import page |
| `/api/cv` | GET/PUT | ✅ Load/save canonical CV (JSON) |
| `/api/cv/yaml` | GET/PUT | ✅ Load/save CV as raw YAML (YAML tab) |
| `/api/cv/yaml/preview` | POST | ✅ Form-state → YAML without saving |
| `/api/cv/render` | POST | ✅ Compile PDF + txt, return preview URLs |
| `/out/{file}` | GET | ✅ Serve compiled PDF/txt (path-traversal guarded) |
| `/api/import` | POST | ✅ PDF/DOCX/text upload → parsed YAML, saved |
| `/api/analyze` | POST | ✅ Rules engine on posted CV state → findings |
| `/api/analyze/grammar` | POST | ✅ LLM grammar pass for one section |
| `/api/bullets/optimize` | POST | ✅ Checks + rewrite candidates for a posted bullet |
| `/tailor` | GET | ✅ Job tailoring page (JD → match report → suggestions → snapshot) |
| `/api/tailor/application/{id}` | GET | ✅ Reload a saved application's cached JD + match (dropdown auto-reload) |
| `/api/tailor/extract` | POST | ✅ JD → extraction JSON (cached on tracker entry) |
| `/api/tailor/suggest` | POST | ✅ Missing-keyword bullet suggestions (optional user guidance) |
| `/api/tailor/preview` | POST | ✅ Master + tailored CV YAML → client renders the live unified diff |
| `/api/tailor/apply` | POST | ✅ Accepted changes → version snapshot |
| `/api/summary/generate` | POST | ✅ 3 summary variants from a deterministic CV digest |
| `/api/headline/generate` | POST | ✅ 3 ATS-safe title-line options (honesty net drops invented specialties) |
| `/letters/new` | GET | ✅ Cover letter page (pick application → draft → edit → export) |
| `/api/letters/generate` | POST | ✅ Outline + per-beat draft pipeline → editable letter text |
| `/api/letters/export` | POST | ✅ Edited letter → .md + .pdf in data/letters/, linked to the application |
| `/api/applications` (+`/{id}`, `/{id}/status`) | CRUD | Tracker |
| `/api/applications/{id}/interview/{questions\|star\|pitch}` | POST | Interview prep generators (§5.7) |

---

## 9. Implementation Milestones

Each milestone ends runnable and independently useful.

- **M1 — Foundation & Editor** *(the core "edit my own CV" ability)* ✅ DONE
  Scaffold FastAPI + config + Ollama client smoke test. CV model + YAML load/save +
  bullet IDs. Typst templates + render + txt export. Editor page with form editing,
  raw-YAML tab, live PDF preview. Onboarding import (PDF/DOCX upload or paste →
  section split → LLM parse → review).
- **M2 — Analyzer + Bullet Optimizer** ✅ DONE
  Rules engine (`analyzer.py`: dates, tense, consistency, repetition, ATS, bias,
  readability, completeness, aggregated bullet-quality) surfaced in a "Checks" tab
  in the right pane (re-runs on save, clickable findings jump to the bullet).
  Per-bullet ✨ optimize popover (`optimizer.py`): instant deterministic checks +
  a tightened rewrite, plus a metric-placeholder variant from a *separate* focused
  LLM call (3B models skip the scaffold in a combined prompt). On-demand LLM grammar
  pass per section returning quote/issue/fix. Suggestions are apply-or-ignore; never
  auto-applied.
- **M3 — Job Tailoring** ✅ DONE
  `/tailor` page (`tailor.py`): JD extraction (one LLM call, requirement-section
  truncation for long JDs), deterministic keyword matching with plural/separator
  tolerance → coverage % match score (hard skills + keywords; soft skills shown
  but not scored), skills-gap "do you actually have these?" checkboxes, title
  swap offer, per-bullet rewrite suggestions (word-overlap candidate picking via
  JD context lines, ≤ 10 sequential calls, null escape hatch, accept/reject
  cards), tailored snapshots to `data/versions/` linked to a tracker entry with
  before/after coverage stored as `match_score`. Minimal tracker DAO
  (list/create/get/update) added ahead of M5.
  Live side-by-side preview: the tailored CV rendered as YAML (server-side via
  `apply_tailoring` + `dump_yaml`, so it is byte-identical to what a save writes),
  refreshed on every title-swap / accept / gap-skill toggle. Picking a saved
  application from the dropdown reloads its cached JD + match report with no LLM
  call. Optional free-text guidance steers rewrite tone (style only — honesty
  rules still win).
- **M4 — Summary + Cover Letters** ✅ DONE
  Summary generator (`summary.py`): deterministic digest (union-of-intervals
  years of experience, current title, top skills, metric-preferring strongest
  bullets) → one LLM call for 3 pronoun-free, cliché-banned variants + a
  separate tiny call for 3 headline options; editor sidebar "✨ Generate
  summary" and a per-field "✨" headline picker. Headlines carry a deterministic
  honesty net that strips any `·`-specialty absent from the CV's skills (a
  target role can reword the role part but never smuggle in invented tech).
  Cover letters (`cover_letter.py`, `/letters/new`): pick a tracked application
  (brings its cached JD extraction), tone + emphasize; small-model-safe pipeline
  = one outline call (4 beats) then one draft call per beat, each fed only its
  plan + the 1-2 word-overlap-relevant CV facts; assembled into an editable
  textarea; export renders `typst/letter.typ` → .md + .pdf in data/letters/ and
  links the PDF to the application. LLM inputs are always the digest/extraction,
  never raw documents; a failed beat degrades to an empty paragraph, not a lost
  letter.
- **M5 — Tracker**
  SQLite DAO, dashboard with match scores, detail page, linking versions/letters,
  status history. (Built last so it can link artifacts from M3/M4; the schema exists
  from M1.)
- **M6 — Interview Prep Kit**
  Question generator, STAR story builder, personal pitch — all on the application
  detail page. (Needs M3's JD extraction and M5's detail page.)
- **Later:** AnthropicProvider, .docx export, JD-from-URL fetch, keyword coverage
  history per application.

### Setup (one time, everything project-local — no brew/npm/global pip)
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# typst: standalone binary in tools/ (already downloaded; to refresh:)
curl -sL -o /tmp/typst.tar.xz https://github.com/typst/typst/releases/latest/download/typst-aarch64-apple-darwin.tar.xz
tar -xf /tmp/typst.tar.xz -C tools --strip-components=1
ollama pull qwen2.5:3b-instruct   # default model (override with CVE_MODEL)

./run.sh   # http://localhost:8877
```

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| 3B model returns malformed JSON | `format:"json"` + schema-in-prompt + 1 retry + graceful UI error |
| 3B model hallucinates achievements | Honesty rules in every prompt, `null` escape hatch, metric *placeholders* only, and mandatory human accept/reject on every change |
| Long JDs blow the 4k context | Deterministic pre-truncation to requirement sections |
| Memory pressure while browser + Ollama run | One model, `num_ctx: 4096`, sequential calls only |
| Cover letter quality on 3B | Beat-by-beat pipeline keeps each call trivial; text is fully editable; this is also the first candidate for the future API provider |
| Typst missing | Startup check with a clear "brew install typst" message; app still works minus PDF |
```
