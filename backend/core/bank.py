"""Project / experience bank (docs/features/profiles-and-bank.md §3).

A per-profile, keyword-tagged library of projects and experiences that the
tailor flow can suggest swapping into the CV. It reuses the CV's bullet schema
and 6-char stable-id scheme (cv_model) and the tailor module's deterministic
keyword helpers, so matching stays within the 8 GB / 3B constraint — no extra
model calls for the core flow. `suggest_tags` (LLM) is the one optional call.
"""
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from backend.core import cv_model, tailor
from backend.llm import prompts
from backend.llm.provider import LLMError, LLMProvider

ENTRY_KINDS = ("projects", "experiences")


def empty_bank() -> Dict[str, List[Any]]:
    return {"projects": [], "experiences": []}


def _new_id(taken: Set[str]) -> str:
    while True:
        eid = uuid.uuid4().hex[:6]
        if eid not in taken:
            taken.add(eid)
            return eid


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _norm_tags(raw: Any) -> List[str]:
    """Lowercased, de-duplicated, order-preserving tag list."""
    out, seen = [], set()
    for t in raw or []:
        tag = _str(t).strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def normalize(data: Any) -> Dict[str, List[Any]]:
    """Coerce arbitrary YAML into the full bank schema; assign missing ids.
    Ids are unique across BOTH lists so a bank entry id is globally addressable.

    A project records its own `company`/`title` as free text. Projects and
    experiences are independent records — neither points at the other, and a
    project's company/title never reach the CV; they're for your own reference.
    """
    if not isinstance(data, dict):
        data = {}
    bank = empty_bank()
    taken: Set[str] = set()
    for kind in ENTRY_KINDS:
        for e in data.get(kind) or []:
            if isinstance(e, dict) and _str(e.get("id")).strip():
                taken.add(_str(e["id"]).strip())

    for p in data.get("projects") or []:
        if not isinstance(p, dict):
            continue
        eid = _str(p.get("id")).strip()
        if not eid or eid not in taken:
            eid = eid if eid else _new_id(taken)
        bank["projects"].append({
            "id": eid,
            "name": _str(p.get("name")).strip(),
            "url": _str(p.get("url")).strip(),
            "company": _str(p.get("company")).strip(),
            "title": _str(p.get("title")).strip(),
            "tags": _norm_tags(p.get("tags")),
            "bullets": cv_model._norm_bullets(p.get("bullets"), taken),
        })

    for e in data.get("experiences") or []:
        if not isinstance(e, dict):
            continue
        eid = _str(e.get("id")).strip() or _new_id(taken)
        bank["experiences"].append({
            "id": eid,
            "company": _str(e.get("company")).strip(),
            "title": _str(e.get("title")).strip(),
            "location": _str(e.get("location")).strip(),
            "start": _str(e.get("start")).strip()[:7],
            "end": (_str(e.get("end")).strip()[:7] or None),
            "tags": _norm_tags(e.get("tags")),
            "bullets": cv_model._norm_bullets(e.get("bullets"), taken),
        })
    return bank


def load_bank(path: Path) -> Dict[str, List[Any]]:
    if not path.exists():
        return empty_bank()
    with open(path) as f:
        return normalize(yaml.safe_load(f))


def dump_yaml(bank: Dict[str, Any]) -> str:
    return yaml.safe_dump(bank, sort_keys=False, allow_unicode=True, width=100)


def save_bank(bank: Dict[str, Any], path: Path) -> Dict[str, List[Any]]:
    bank = normalize(bank)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(dump_yaml(bank))
    return bank


# --- CRUD (all operate on the loaded bank dict, then save) ----------------------

def find_entry(bank: Dict[str, Any], entry_id: str) -> Optional[Dict[str, Any]]:
    for kind in ENTRY_KINDS:
        for e in bank[kind]:
            if e["id"] == entry_id:
                return e
    return None


def kind_of(bank: Dict[str, Any], entry_id: str) -> Optional[str]:
    """Which list an id lives in. Authoritative: projects carry a `company` of
    their own, so an entry's shape can't tell the two kinds apart."""
    for kind in ENTRY_KINDS:
        if any(e["id"] == entry_id for e in bank[kind]):
            return kind
    return None


def upsert_entry(path: Path, kind: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Create (no id) or update (matching id) one entry; returns the saved bank.
    `kind` is 'projects' or 'experiences'."""
    if kind not in ENTRY_KINDS:
        raise ValueError(f"Unknown bank kind: {kind}")
    bank = load_bank(path)
    entry = dict(entry)
    eid = _str(entry.get("id")).strip()
    existing_kind = kind_of(bank, eid) if eid else None
    if existing_kind is not None:
        # an entry never changes kind: update it in the list it already lives in
        bank[existing_kind] = [entry if e["id"] == eid else e
                               for e in bank[existing_kind]]
    else:
        bank[kind].append(entry)
    return save_bank(bank, path)


def delete_entry(path: Path, entry_id: str) -> Dict[str, Any]:
    bank = load_bank(path)
    for kind in ENTRY_KINDS:
        bank[kind] = [e for e in bank[kind] if e["id"] != entry_id]
    return save_bank(bank, path)


# --- deterministic matching (§3, no LLM) ----------------------------------------

def _entry_words(entry: Dict[str, Any]) -> Set[str]:
    """Significant words + tags describing a bank entry, for overlap scoring."""
    words: Set[str] = set(entry.get("tags") or [])
    words |= tailor._significant(entry.get("name") or entry.get("company") or "")
    words |= tailor._significant(entry.get("title") or "")
    for b in entry.get("bullets") or []:
        words |= tailor._significant(b["text"])
    return words


def _in_cv(entry: Dict[str, Any], cv: Dict[str, Any]) -> bool:
    """Is this bank entry already present in the CV? Matches by name/company."""
    key = (entry.get("name") or entry.get("company") or "").strip().lower()
    if not key:
        return False
    for p in cv.get("projects") or []:
        if p["name"].strip().lower() == key:
            return True
    for e in cv.get("experience") or []:
        if e["company"].strip().lower() == key:
            return True
    return False


def suggest_for_extraction(bank: Dict[str, Any], extraction: Dict[str, Any],
                           cv: Optional[Dict[str, Any]] = None,
                           limit: int = 5) -> List[Dict[str, Any]]:
    """Score each bank entry by overlap between its tags + bullet text and the
    JD's missing hard-skills + keywords, ranked by score. Excludes entries
    already in the CV. Fully deterministic (SPEC §3)."""
    scored = tailor._dedupe((extraction.get("hard_skills") or [])
                            + (extraction.get("keywords") or []))
    patterns = [(kw, tailor._kw_pattern(kw)) for kw in scored]
    # if a cv is given, only rank against keywords the CV is missing
    if cv is not None:
        cv = cv_model.normalize(cv)
        text = tailor._cv_text(cv)
        patterns = [(kw, p) for kw, p in patterns if not (p and p.search(text))]

    results = []
    for kind in ENTRY_KINDS:
        for entry in bank[kind]:
            if cv is not None and _in_cv(entry, cv):
                continue
            blob = " ".join([entry.get("name") or entry.get("company") or "",
                             entry.get("title") or "",
                             " ".join(entry.get("tags") or []),
                             " ".join(b["text"] for b in entry.get("bullets") or [])])
            matched = [kw for kw, p in patterns if p and p.search(blob)]
            if not matched:
                continue
            results.append({
                "id": entry["id"], "kind": kind,
                "title": entry.get("name") or entry.get("company") or "(untitled)",
                "subtitle": (entry.get("title") or entry.get("url") or ""),
                "tags": entry.get("tags") or [],
                "score": len(matched), "matched": matched,
                "bullets": [b["text"] for b in entry.get("bullets") or []],
            })
    results.sort(key=lambda r: -r["score"])
    return results[:limit]


# --- optional LLM tag suggestion (§3, Phase 3) ----------------------------------

def suggest_tags(entry: Dict[str, Any], provider: LLMProvider) -> List[str]:
    """One small LLM call proposing candidate tags from the entry's text.
    Suggestions are approve/edit only — never auto-applied to the entry."""
    lines = [entry.get("name") or entry.get("company") or "",
             entry.get("title") or ""]
    lines += [b["text"] for b in entry.get("bullets") or []]
    text = "\n".join(l for l in lines if l).strip()
    if not text:
        return []
    raw = provider.complete_json(prompts.BANK_TAGS, text, max_tokens=150)
    tags = raw.get("tags") if isinstance(raw, dict) else None
    if not isinstance(tags, list):
        raise LLMError("Model returned an unusable tag list; try again.")
    return _norm_tags(tags)
