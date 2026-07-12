# Feature: User Profiles & Project/Experience Bank

Status: planned
Owner: local
Related SPEC sections: §1 (Goals/Non-Goals), §3 (Architecture), §4 (Data Model)

Two related features that turn the single-CV tool into a multi-person tool with a
reusable, tag-based library of projects and experiences.

---

## 1. Motivation

- **Bank:** When tailoring to a job description we can only rewrite the bullets
  already in the CV. Often the better move is to swap in a *different* project or
  past role that is more relevant to the JD. A reusable, keyword-tagged bank of
  projects and experiences lets the tailor flow suggest those swaps deterministically.
- **Profiles:** Because a bank stores projects and experiences *per person*, the
  tool must separate one person's data from another's. This also enables a single
  installation to be used by several people (e.g. someone helping others tailor CVs).

This revises the original SPEC non-goal "Multi-user support" — see §5 below.

---

## 2. User Profiles

### Model
- A profile is a directory `data/profiles/<slug>/` holding **all** per-person state:
  `cv.yaml`, `versions/`, `letters/`, `out/`, `tracker.db`, and `bank.yaml`.
- `data/profiles/<slug>/profile.yaml` holds display metadata: `name`, `created_at`.
- `slug` is a filesystem-safe slugification of the display name, de-duplicated.

### Active-profile resolution (session cookie)
- The active profile is selected **per request** via a `cve_profile` cookie.
- A FastAPI dependency `current_profile(request)` resolves the cookie to a `Profile`,
  falling back to the first existing profile, auto-creating `default` if none exist.
- A profile switcher in the nav calls `POST /api/profile/switch`, which sets the cookie.
- Consequence: this is genuine concurrent multi-person use (two browsers/cookies →
  two profiles simultaneously), so per-user paths can **no longer be module-level
  constants** in `config.py`; they become attributes of the resolved `Profile`.

### Scope decisions
- Bank is **per-profile** (not a shared global bank).
- No auth. Profiles are a data-partitioning convenience on a trusted local machine,
  not a security boundary.
- **No migration** of existing data: the current `data/cv.yaml`, `tracker.db`,
  `versions/`, `letters/`, `out/` were test data and are wiped. New profiles start empty.

---

## 3. Project / Experience Bank

### Model — `data/profiles/<slug>/bank.yaml`
```yaml
projects:
  - id: <6-char>            # stable id (reuses cv_model bullet-id scheme)
    name: ...
    url: ...
    tags: [python, fastapi, llm]
    bullets: [{id, text}, ...]
experiences:
  - id: <6-char>
    company: ...
    title: ...
    location: ...
    start: 2023-01
    end: 2024-06
    tags: [...]
    bullets: [{id, text}, ...]
```

### Matching (deterministic — no LLM)
- `suggest_for_extraction(bank, extraction)` scores each bank entry by overlap
  between its tags + bullet text and the JD's missing hard-skills + keywords.
- Reuses the existing `tailor._kw_pattern` / `tailor._significant` helpers.
- Returns entries ranked by score, excluding entries already present in the CV.
- Fully deterministic keeps it within the 8 GB / 3B constraint (no extra model calls).

### Tagging (manual + optional LLM suggestion)
- Manual tags per entry are authoritative.
- Optional `suggest_tags(entry, provider)` generates candidate tags from the entry's
  text via one small LLM call (new prompt `BANK_TAGS`, new task `bank_tags` in
  `config.TASK_MODELS`). Suggestions are approve/edit only — never auto-applied.

### Suggest-and-approve (consistent with SPEC §5.8)
- Nothing from the bank auto-edits the CV. Both the standalone "insert into CV" action
  and the tailor-flow suggestions go through explicit approval and `cv_model.save_cv`.

---

## 4. Surfaces

### Backend — `backend/core/`
- `profiles.py` — `Profile` dataclass (resolved paths), `list/create/delete/get_profile`, `slugify`.
- `bank.py` — load/save/normalize, CRUD, `suggest_for_extraction`, `suggest_tags`.
- `tracker.py` — every DAO function gains a `db_path` parameter (routes pass `profile.tracker_db`).
- `cv_model` / `render` / `cover_letter` / `tailor` already accept optional paths; routes pass `profile.*`.

### Routes — `backend/main.py`
- `POST /api/profile/switch`, `GET /api/profile` (list), `POST /api/profile` (create),
  `DELETE /api/profile/{slug}`.
- `GET /bank` (manager page); `GET/POST /api/bank`, `PUT/DELETE /api/bank/{id}`.
- `POST /api/bank/suggest-tags`, `POST /api/bank/insert` (into active profile CV).
- `POST /api/tailor/suggest` response extended with a `bank_suggestions` list.
- Every route gains the `current_profile` dependency.

### Frontend — `frontend/templates/`
- `bank.html` — manage/tag entries, "suggest tags", "insert into CV".
- `base.html` — nav profile switcher/dropdown + "Bank" link.
- `tailor.html` — "Relevant projects from your bank" section alongside bullet rewrites.

---

## 5. SPEC revisions this feature makes

- **§1 Non-Goals:** "Multi-user support, auth, hosting" is narrowed. Multiple *profiles*
  (local data partitions, no auth, no hosting) are now in scope; hosting and real auth remain out.
- **§3 Storage / layout:** per-user state moves under `data/profiles/<slug>/`; `config.py`
  path constants become `Profile` attributes resolved per request.
- **§4 Data Model:** adds `data/profiles/<slug>/bank.yaml` alongside the canonical `cv.yaml`.

---

## 6. Build order

1. Profile layer + config repoint + wipe test data + thread `profile` paths through all
   modules/routes (single-profile-per-cookie working end to end).
2. Bank module + CRUD routes + `bank.html` + nav.
3. Tag suggestion (`BANK_TAGS`) + tailor-flow `bank_suggestions` integration.
