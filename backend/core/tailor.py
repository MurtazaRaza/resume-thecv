"""Job tailoring (SPEC §5.1): JD extraction, deterministic keyword matching,
per-bullet rewrite suggestions, and tailored version snapshots.

Decomposed for a 3B model: one small extraction call, then deterministic
matching, then at most MAX_REWRITE_CALLS single-bullet rewrite calls. The
master cv.yaml is never touched — accepted changes go to data/versions/.
"""
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend import config
from backend.core import cv_model
from backend.llm import prompts
from backend.llm.provider import LLMError, LLMProvider

EXTRACTION_LIST_KEYS = ["hard_skills", "soft_skills", "keywords",
                        "action_verbs", "must_have_qualifications"]
MAX_LIST_ITEMS = 15
MAX_JD_WORDS = 3000
MAX_JD_CHARS = 6000          # keep the extract call well inside num_ctx=4096
MAX_REWRITE_CALLS = 10
MAX_BULLETS_PER_KEYWORD = 2

# paragraphs worth keeping when a JD is too long (SPEC §5.1 step 1)
_SIGNAL_RE = re.compile(
    r"requir|qualif|responsib|must.have|nice.to.have|preferred|proficien|"
    r"familiar|knowledge|competenc|skills|experience|you will|you have|"
    r"you are|we expect|what you", re.IGNORECASE)

_STOPWORDS = set("""a an and the for with to of in on at by from as is are was
were be been will would can could should our your their its this that these
those any all more most other than then when where which while you we they it
have has had do does did not or if so such per via etc strong ability years
year work working experience team teams skills skill including use using used
knowledge plus role position candidate ideal must nice preferred required
requirements responsibilities day help build make take well good great new
across within also both least e.g i.e""".split())

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-/]{2,}")


# --- JD extraction (LLM) --------------------------------------------------------

def truncate_jd(text: str) -> str:
    """Long JDs: keep only paragraphs that smell like requirements, then a
    hard char cap so the extract call always fits the context window."""
    if len(text.split()) > MAX_JD_WORDS:
        paras = re.split(r"\n\s*\n", text)
        kept = [p for p in paras if _SIGNAL_RE.search(p)]
        if kept:
            text = "\n\n".join(kept)
    return text[:MAX_JD_CHARS]


def _dedupe(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out = []
    for it in items:
        key = it.lower()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def extract(jd_text: str, provider: LLMProvider) -> Dict[str, Any]:
    """JD text -> normalized extraction dict (SPEC §5.1 step 1)."""
    raw = provider.complete_json(prompts.JD_EXTRACT, truncate_jd(jd_text),
                                 max_tokens=700)
    if not isinstance(raw, dict):
        raise LLMError("Model returned an unusable JD extraction; try again.")
    ext: Dict[str, Any] = {
        "target_title": str(raw.get("target_title") or "").strip()}
    for key in EXTRACTION_LIST_KEYS:
        vals = raw.get(key)
        items = [str(v).strip() for v in vals if str(v).strip()] \
            if isinstance(vals, list) else []
        ext[key] = _dedupe(items)[:MAX_LIST_ITEMS]
    return ext


# --- keyword matching (deterministic) -------------------------------------------

def _kw_pattern(kw: str) -> Optional[re.Pattern]:
    """Whole-word regex for a keyword: case-insensitive, flexible separators
    ('CI/CD' ~ 'CI CD'), simple plural/singular tolerance on the last token."""
    toks = [t for t in re.split(r"[\s\-/_]+", kw.lower()) if t]
    if not toks:
        return None
    last = toks[-1]
    variants = {last}
    if last.endswith("ies"):
        variants.add(last[:-3] + "y")
    elif last.endswith("es"):
        variants.update((last[:-2], last[:-1]))
    elif last.endswith("s"):
        variants.add(last[:-1])
    else:
        variants.add(last + "s")
        if last.endswith("y"):
            variants.add(last[:-1] + "ies")
    parts = [re.escape(t) for t in toks[:-1]]
    parts.append("(?:" + "|".join(re.escape(v) for v in sorted(variants)) + ")")
    body = r"[\s\-/_]+".join(parts)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])", re.IGNORECASE)


def _cv_text(cv: Dict[str, Any]) -> str:
    parts = [cv["basics"]["title"], cv["summary"]]
    for e in cv["experience"]:
        parts.append(e["title"])
        parts += [b["text"] for b in e["bullets"]]
    for p in cv["projects"]:
        parts.append(p["name"])
        parts += [b["text"] for b in p["bullets"]]
    for e in cv["education"]:
        parts += [e["degree"], e["details"]]
    parts += [i for s in cv["skills"] for i in s["items"]]
    parts += [c["name"] for c in cv["certifications"]]
    return "\n".join(p for p in parts if p)


def _partition(keywords: List[str], text: str):
    covered, missing = [], []
    for kw in keywords:
        pat = _kw_pattern(kw)
        (covered if pat and pat.search(text) else missing).append(kw)
    return covered, missing


def match(cv: Dict[str, Any], extraction: Dict[str, Any]) -> Dict[str, Any]:
    """Coverage report (SPEC §5.1 step 2). The score counts hard skills +
    keywords only; soft skills rarely appear verbatim in a CV, so they are
    reported separately and never drag the score down."""
    text = _cv_text(cv)
    scored = _dedupe(extraction["hard_skills"] + extraction["keywords"])
    covered, missing = _partition(scored, text)
    soft_covered, soft_missing = _partition(extraction["soft_skills"], text)
    missing_set = {m.lower() for m in missing}
    return {
        "coverage": round(100 * len(covered) / len(scored)) if scored else 0,
        "covered": covered,
        "missing": missing,
        "soft_covered": soft_covered,
        "soft_missing": soft_missing,
        # hard skills absent from the CV -> "do you actually have these?" UI
        "skills_gap": [k for k in extraction["hard_skills"]
                       if k.lower() in missing_set],
    }


# --- per-bullet rewrite suggestions (LLM) ----------------------------------------

def _significant(text: str) -> Set[str]:
    words = (w.rstrip("./,-") for w in _WORD_RE.findall(text.lower()))
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _context_words(jd_text: str, kw: str) -> Set[str]:
    """Significant words from the JD lines that mention the keyword — a bullet
    overlapping these plausibly relates to the keyword even when the keyword
    itself is absent from the CV."""
    pat = _kw_pattern(kw)
    words = _significant(kw)
    for line in jd_text.splitlines():
        if pat and pat.search(line):
            words |= _significant(line)
    return words


def _pick_rewrite_targets(cv: Dict[str, Any], extraction: Dict[str, Any],
                          jd_text: str) -> List[tuple]:
    """The deterministic (bullet, missing-keyword) selection shared by
    `suggest` (which then rewrites each) and `count_tailorable` (which just
    counts them). Word-overlap heuristic, capped at MAX_REWRITE_CALLS, one
    pick per bullet and at most MAX_BULLETS_PER_KEYWORD per keyword. No LLM.
    Returns a list of (keyword, entry, bullet) in priority order."""
    missing = match(cv, extraction)["missing"]
    bullets = [(e, b) for e in cv["experience"] for b in e["bullets"]
               if b["text"].strip()]

    pairs = []  # (score, keyword, entry, bullet)
    for kw in missing:
        ctx = _context_words(jd_text, kw)
        for e, b in bullets:
            overlap = len(ctx & _significant(b["text"]))
            if overlap:
                pairs.append((overlap, kw, e, b))
    pairs.sort(key=lambda p: -p[0])

    picked, used_bullets, per_kw = [], set(), {}
    for score, kw, e, b in pairs:
        if b["id"] in used_bullets or per_kw.get(kw, 0) >= MAX_BULLETS_PER_KEYWORD:
            continue
        used_bullets.add(b["id"])
        per_kw[kw] = per_kw.get(kw, 0) + 1
        picked.append((kw, e, b))
        if len(picked) >= MAX_REWRITE_CALLS:
            break
    return picked


def count_tailorable(cv: Dict[str, Any], extraction: Dict[str, Any],
                     jd_text: str) -> int:
    """How many distinct experience bullets the rewrite step *would* target,
    without running any LLM call (SPEC quick-capture effort hint). Shares
    `_pick_rewrite_targets` with `suggest` so the count can never drift from
    what tailoring would actually attempt."""
    return len(_pick_rewrite_targets(cv, extraction, jd_text))


def suggest(cv: Dict[str, Any], extraction: Dict[str, Any], jd_text: str,
            provider: LLMProvider, guidance: str = "") -> Dict[str, Any]:
    """Missing-keyword rewrite suggestions (SPEC §5.1 step 3). Word-overlap
    heuristic picks (bullet, keyword) pairs, max MAX_REWRITE_CALLS sequential
    LLM calls, one suggestion per bullet. A failed call skips that pair
    instead of losing the whole run.

    `guidance` is optional free-text steering from the user (tone, emphasis).
    It is appended to each per-bullet request but never overrides the honesty
    rules in the system prompt."""
    guidance = guidance.strip()
    picked = _pick_rewrite_targets(cv, extraction, jd_text)

    suggestions, errors = [], []
    for kw, e, b in picked:
        user = f"Keyword: {kw}\nBullet: {b['text']}"
        if guidance:
            user += (f"\nUser guidance (style only, never a licence to invent "
                     f"facts): {guidance}")
        try:
            raw = provider.complete_json(
                prompts.TAILOR_REWRITE, user, max_tokens=200)
        except LLMError as err:
            errors.append(str(err))
            continue
        rewrite = raw.get("rewrite") if isinstance(raw, dict) else None
        if not isinstance(rewrite, str) or not rewrite.strip():
            continue  # model honestly declined
        rewrite = rewrite.strip()
        pat = _kw_pattern(kw)
        if rewrite == b["text"].strip() or not (pat and pat.search(rewrite)):
            continue  # no change, or the keyword never made it in
        suggestions.append({
            "bullet_id": b["id"],
            "keyword": kw,
            "role": f"{e['title'] or 'role'} at {e['company'] or '?'}",
            "original": b["text"],
            "rewrite": rewrite,
        })
    return {"suggestions": suggestions, "errors": errors,
            "attempted": len(picked)}


# --- apply + snapshot (deterministic) --------------------------------------------

def apply_tailoring(cv: Dict[str, Any], extraction: Dict[str, Any],
                    accepted: List[Dict[str, str]],
                    add_skills: List[str], skills_group: str,
                    new_title: str = "") -> Dict[str, Any]:
    """Build the tailored CV (SPEC §5.1 steps 4-6): accepted bullet rewrites,
    optional title swap, user-confirmed gap skills, and skills reordered so
    JD-matched items come first. Returns a new dict; the input is untouched."""
    cv = cv_model.normalize(cv)  # fresh copy with the same bullet ids
    for a in accepted:
        b = cv_model.find_bullet(cv, str(a.get("id", "")))
        text = str(a.get("text", "")).strip()
        if b and text:
            b["text"] = text

    if new_title.strip():
        cv["basics"]["title"] = new_title.strip()

    add_skills = [s.strip() for s in add_skills if s.strip()]
    if add_skills:
        group = next((g for g in cv["skills"]
                      if g["group"].lower() == skills_group.strip().lower()), None)
        if group is None:
            group = {"group": skills_group.strip() or "Skills", "items": []}
            cv["skills"].append(group)
        have = {i.lower() for i in group["items"]}
        group["items"] += [s for s in add_skills if s.lower() not in have]

    patterns = [p for p in (_kw_pattern(k) for k in
                            extraction["hard_skills"] + extraction["keywords"]) if p]
    for g in cv["skills"]:
        g["items"].sort(key=lambda item: not any(p.search(item) for p in patterns))
    return cv


def save_snapshot(cv: Dict[str, Any], company: str, versions_dir: Path) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-") or "job"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = versions_dir / f"tailored-{slug}-{stamp}.yaml"
    versions_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(cv_model.dump_yaml(cv))
    return path
