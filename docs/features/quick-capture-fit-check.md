# Feature: Quick Capture & Instant Fit Check

Status: planned
Owner: local
Related SPEC sections: §5.1 (One-Click Job Tailoring), §5.6 (Application Tracker)

A low-friction front door: paste a job description (or URL later) and get an
**instant fit verdict** in the same action that saves the job to the tracker.
The verdict answers "is this worth my time?" before any tailoring, and the save
records a match score plus one concrete next step. Saving a job is never a dead
end again.

---

## 1. Motivation

The tool's real failure mode is not missing features — it is **activation
energy**. The observed behaviour: a job gets saved, then never applied to. Two
things cause the stall, and this feature attacks both:

1. **Doubt it's worth it.** Deciding whether to apply currently requires running
   the full tailor pipeline. That's too much work to answer a cheap question, so
   the job sits unevaluated in an undifferentiated pile.
2. **The next step is a blob.** "Tailor my CV and apply" is vague and heavy. The
   brain avoids blobs.

The fix is to make **saving itself pay off instantly**: the moment a JD is
captured, the user sees a coverage %, the top missing must-haves, and a single
small next action. The evaluation *is* the capture — there is no separate
"come back later to assess" step to skip.

This is deliberately **not** the full tailor flow. It exposes only steps 1–2 of
`tailor.py` (LLM extract + deterministic match) as a fast path, skipping the
expensive per-bullet rewrite calls (step 3). One small model call, then pure
Python. Fits the 8 GB / 3B constraint trivially.

---

## 2. What the user sees

A prominent **"Save a job"** box (on the tracker page, and ideally the home
page) with: company, role, optional URL, and a JD paste area. One button:
**"Save & check fit."**

On submit, in-place, it shows a **verdict card**:

- **Coverage score** (the existing `match.coverage`), shown as a band:
  Strong ≥70 / Partial 40–69 / Long shot <40. Bands are advisory, not gates.
- **Top missing must-haves** — up to 3 items from `match.missing`, prioritising
  anything also in `extraction.must_have_qualifications`.
- **Effort hint** — "~N bullets could be tailored to close the gap", computed
  deterministically (see §4) without running any rewrites.
- **One next action button** — the smallest next move, never the whole blob:
  - Strong fit → **"Tailor & apply"** (deep-links to `/tailor` with this app loaded)
  - Partial → **"Review N suggestions"** (same deep link)
  - Long shot → **"Save for later"** / **"Skip"** (still saved, just parked)

The application is created and the score stored **before** the card renders, so
even if the user closes the tab, the job is captured with its verdict intact.

---

## 3. Why it reduces friction (design rationale)

- **Payoff before effort.** Today: save → nothing → leave. New: save → verdict →
  already looking at the answer, one click from motion.
- **Doubt resolved at save time.** The score triages the pile automatically; a
  job is never an inert "should I?" question sitting in the backlog.
- **Blob broken into a single step.** The card offers exactly one next action,
  pre-teed, sized ("N bullets") so it reads as small.
- **Stacks with the tracker.** Because every captured job now carries a
  `match_score`, the dashboard can later sort/triage strong fits vs long shots
  with data it already has — no new storage.

---

## 4. Backend

### Reuses (no new core logic)
- `tailor.extract(jd_text, provider)` — the one LLM call (task `jd_extract`).
- `tailor.match(cv, extraction)` — deterministic coverage report.
- `tracker.create_application` / `update_application(match_score=, jd_text=,
  jd_extraction=, next_action=)` — all fields already exist in the schema.

### New: effort hint (deterministic, `tailor.py`)
`count_tailorable(cv, extraction, jd_text) -> int` — the number of distinct
experience bullets the rewrite step *would* pick, computed with the **existing**
`suggest` candidate-selection heuristic (`_context_words` / `_significant` /
`MAX_REWRITE_CALLS` cap) but **stopping before any LLM call**. Refactor the
pair-picking block at the top of `suggest()` into a shared
`_pick_rewrite_targets(...)` helper so both `suggest` and `count_tailorable`
use identical logic and never drift. No new model usage.

### New: `must_have` prioritisation for the card
Small helper (or inline in the route) that orders `match.missing` so items also
present in `extraction["must_have_qualifications"]` come first, then truncates to
3 for the card. Full lists stay available on the tracker detail page.

### Route — `POST /api/capture` (`backend/main.py`)
Body: `{company, role, url?, jd_text}`. All required except `url`.

1. Validate company/role/jd_text (mirror `/api/tailor/extract`'s 422s).
2. `create_application(...)` → `app_id`.
3. `extract(...)` (502 on `LLMError`, but the app row already exists so the save
   is never lost — return `application_id` alongside the error).
4. `match(...)`, `count_tailorable(...)`, prioritise missing.
5. Persist: `jd_text`, `jd_extraction`, `match_score = match["coverage"]`, and a
   default `next_action` string derived from the band.
6. Return `{application_id, company, coverage, band, top_missing[],
   tailorable_count, next_action}`.

This is essentially `/api/tailor/extract` for the **new-application** path plus
the score/effort payload — so much of it can be shared. Consider having
`/api/tailor/extract` reuse the same extract+persist helper to avoid two code
paths that can diverge.

### Deep link into tailor
`/tailor?app=<id>` should auto-load that application on page load (reusing
`GET /api/tailor/application/{app_id}`), so the card's "Tailor & apply" button
lands the user directly in the tailor flow with the JD already matched.

---

## 5. Frontend

- **`tracker.html`** — add the "Save a job" capture box at the top, above the
  status groups. It is the primary call to action on the page.
- **`base.html`** — the home route (`/`) could redirect to, or embed, this box so
  the very first thing on opening the app is "paste a job."
- New JS (small, vanilla, consistent with `editor.js`): POST to `/api/capture`,
  render the verdict card in place, wire the single next-action button.
- Verdict card styling: reuse the existing coverage/score styles from the tailor
  page so the band colours match what the user already sees there.

---

## 6. Scope decisions

- **Not** the full tailor flow. No per-bullet rewrites here — that's the payoff
  the "next action" button leads to, deliberately one click away, not upfront.
- **Save survives LLM failure.** The application row is created before the model
  call; a failed extract leaves a captured job the user can retry, not nothing.
- **Bands are advisory.** A low score never blocks saving or applying — it
  informs, it doesn't gate. The user's judgement stays authoritative (consistent
  with the suggest-and-approve ethos).
- **URL paste is out of scope here** (later nice-to-have per SPEC); the capture
  box takes a URL field only as tracker metadata for now. When URL-fetch lands,
  it slots in as a pre-step that fills `jd_text`.

---

## 7. Build order

1. Refactor `suggest()`'s target-picking into `_pick_rewrite_targets`; add
   `count_tailorable` on top of it (pure, testable, no LLM).
2. `POST /api/capture` reusing extract+match+persist; store `match_score` and a
   band-derived `next_action`.
3. Capture box + verdict card on `tracker.html`; `/tailor?app=` deep-link.
4. (Optional, follow-up) Make `/` open on the capture box; sort the tracker
   dashboard by `match_score` within the "saved" group.
