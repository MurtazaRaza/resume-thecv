"""Resume summary + headline generator (SPEC §5.3).

Deterministic-first: compute a small candidate *digest* from the CV (years of
experience, current title, top skills, strongest bullets) in pure Python, then
one focused LLM call turns the digest into 3 summary variants and a separate
tiny call yields 3 headline options. The model only ever sees the digest (plus
an optional JD target), never the whole CV — keeps each call inside num_ctx and
gives a 3B model almost nothing to hallucinate from.
"""
import datetime
import re
from typing import Any, Dict, List, Optional, Set

from backend.llm import prompts
from backend.llm.provider import LLMError, LLMProvider

TOP_SKILLS = 8
TOP_BULLETS = 3
_METRIC_RE = re.compile(r"[\d%$€£]")


def _months(ym: str) -> Optional[int]:
    """'YYYY-MM' or 'YYYY' -> absolute month count, or None if unparseable."""
    m = re.match(r"^(\d{4})(?:-(\d{2}))?$", ym.strip())
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else 1
    if not 1 <= month <= 12:
        month = 1
    return year * 12 + (month - 1)


def years_experience(cv: Dict[str, Any]) -> int:
    """Total distinct months spanned by experience entries, in whole years.

    Uses a union of month intervals so concurrent/overlapping roles are not
    double-counted; an open (current) role runs to today.
    """
    now = datetime.date.today()
    today = now.year * 12 + (now.month - 1)
    intervals = []
    for e in cv["experience"]:
        start = _months(e["start"])
        if start is None:
            continue
        end = _months(e["end"]) if e["end"] else today
        if end is None:
            end = today
        intervals.append((start, min(end, today)))
    if not intervals:
        return 0
    intervals.sort()
    total, cur_s, cur_e = 0, *intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return round(total / 12)


def current_title(cv: Dict[str, Any]) -> str:
    """The title of the current role (no end date), else basics.title, else the
    most recent role's title."""
    for e in cv["experience"]:
        if not e["end"] and e["title"]:
            return e["title"]
    if cv["basics"]["title"]:
        return cv["basics"]["title"]
    return next((e["title"] for e in cv["experience"] if e["title"]), "")


def top_skills(cv: Dict[str, Any], limit: int = TOP_SKILLS) -> List[str]:
    """Flatten skill groups in order, dedupe, cap. Skills are the least
    hallucination-prone signal for the model to anchor on."""
    seen, out = set(), []
    for g in cv["skills"]:
        for item in g["items"]:
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                out.append(item)
                if len(out) >= limit:
                    return out
    return out


def strong_bullets(cv: Dict[str, Any], limit: int = TOP_BULLETS) -> List[str]:
    """Pick the strongest experience bullets, preferring ones with a metric,
    then longer (more substantive) ones. Deterministic, no LLM."""
    bullets = [b["text"] for e in cv["experience"] for b in e["bullets"]
               if b["text"].strip()]
    bullets.sort(key=lambda t: (bool(_METRIC_RE.search(t)), len(t.split())),
                 reverse=True)
    return bullets[:limit]


def compute_digest(cv: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic pre-compute (SPEC §5.3): the only thing the LLM ever sees."""
    return {
        "years": years_experience(cv),
        "current_title": current_title(cv),
        "top_skills": top_skills(cv),
        "strong_bullets": strong_bullets(cv),
    }


def _digest_text(digest: Dict[str, Any], target_title: str = "") -> str:
    lines = [
        f"Years: {digest['years']}.",
        f"Current title: {digest['current_title'] or 'not stated'}.",
        f"Top skills: {', '.join(digest['top_skills']) or 'not stated'}.",
        "Signature achievements: " +
        ("; ".join(digest["strong_bullets"]) or "not stated") + ".",
    ]
    if target_title.strip():
        lines.append(f"Target role: {target_title.strip()}")
    return "\n".join(lines)


def _clean_variants(raw: Any, key: str, n: int = 3) -> List[str]:
    items = raw.get(key) if isinstance(raw, dict) else None
    out = []
    for v in items or []:
        s = str(v).strip()
        if s:
            out.append(s)
    return out[:n]


def generate_summaries(cv: Dict[str, Any], provider: LLMProvider,
                       target_title: str = "") -> Dict[str, Any]:
    """3 summary variants from the digest (SPEC §5.3). Returns the digest too so
    the UI can show what the model was working from."""
    digest = compute_digest(cv)
    raw = provider.complete_json(prompts.SUMMARY_VARIANTS,
                                 _digest_text(digest, target_title),
                                 temperature=0.5, max_tokens=500)
    variants = _clean_variants(raw, "variants")
    if not variants:
        raise LLMError("Model returned no usable summary; try again.")
    return {"digest": digest, "variants": variants}


def _known_skills(cv: Dict[str, Any]) -> Set[str]:
    return {i.lower() for g in cv["skills"] for i in g["items"] if i}


def _prune_headline(headline: str, known: Set[str]) -> str:
    """Drop `·`-separated specialty tokens the CV doesn't actually list — a hard
    net under the prompt so a target role can't smuggle in invented tech. The
    first segment (the role/title) is always kept."""
    parts = [p.strip() for p in headline.split("·")]
    if not parts:
        return headline
    kept = [parts[0]]
    for p in parts[1:]:
        if p.lower() in known:
            kept.append(p)
    return " · ".join(kept)


def generate_headlines(cv: Dict[str, Any], provider: LLMProvider,
                       target_title: str = "") -> Dict[str, Any]:
    """3 plain-text headline options for basics.title (SPEC §5.3)."""
    digest = compute_digest(cv)
    raw = provider.complete_json(prompts.HEADLINE_VARIANTS,
                                 _digest_text(digest, target_title),
                                 temperature=0.5, max_tokens=200)
    heads = [re.sub(r"\s+", " ", h) for h in _clean_variants(raw, "headlines")]
    # ATS guard: pipes are a classic ATS red flag — swap for the middle dot the
    # prompt asks for. Slashes are left alone (legit in titles like "Tools/QA").
    heads = [re.sub(r"\s*\|\s*", " · ", h).strip() for h in heads if h]
    # Honesty net: strip specialties not present in the CV's skills.
    known = _known_skills(cv)
    heads = [_prune_headline(h, known) for h in heads]
    # de-dupe after pruning (pruning can collapse two headlines together)
    seen, out = set(), []
    for h in heads:
        if h and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    if not out:
        raise LLMError("Model returned no usable headline; try again.")
    return {"digest": digest, "headlines": out}
