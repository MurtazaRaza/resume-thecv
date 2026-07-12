"""CV data model: YAML load/save, schema normalization, stable bullet IDs.

The CV lives in data/cv.yaml as the single source of truth. We work with
plain dicts (the schema is small and YAML-shaped); `normalize()` guarantees
every expected key exists and every bullet has a stable 6-char id, so the
rest of the app can address bullets individually.
"""
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from backend import config

SECTION_KEYS = ["basics", "summary", "experience", "education", "skills",
                "projects", "certifications"]


def empty_cv() -> Dict[str, Any]:
    return {
        "basics": {"name": "", "title": "", "email": "", "phone": "",
                   "location": "", "links": []},
        "summary": "",
        "experience": [],
        "education": [],
        "skills": [],
        "projects": [],
        "certifications": [],
    }


def _new_id(taken: Set[str]) -> str:
    while True:
        bid = uuid.uuid4().hex[:6]
        if bid not in taken:
            taken.add(bid)
            return bid


def _str(v: Any) -> str:
    """YAML may parse dates/numbers into objects; the model stores strings."""
    return "" if v is None else str(v)


def _norm_bullets(raw: Any, taken: Set[str]) -> List[Dict[str, str]]:
    bullets = []
    for b in raw or []:
        if isinstance(b, str):
            b = {"text": b}
        if not isinstance(b, dict):
            continue
        text = _str(b.get("text")).strip()
        bid = _str(b.get("id")).strip()
        if not bid or bid in taken:
            bid = _new_id(taken)
        else:
            taken.add(bid)
        bullets.append({"id": bid, "text": text})
    return bullets


def normalize(data: Any) -> Dict[str, Any]:
    """Coerce arbitrary YAML into the full schema; assign missing bullet ids."""
    if not isinstance(data, dict):
        data = {}
    cv = empty_cv()
    taken: Set[str] = set()
    # collect existing ids first so we never reassign one that's already stable
    for section in ("experience", "projects"):
        for entry in data.get(section) or []:
            if isinstance(entry, dict):
                for b in entry.get("bullets") or []:
                    if isinstance(b, dict) and b.get("id"):
                        taken.add(_str(b["id"]))

    basics = data.get("basics") or {}
    if isinstance(basics, dict):
        for k in ("name", "title", "email", "phone", "location"):
            cv["basics"][k] = _str(basics.get(k)).strip()
        for link in basics.get("links") or []:
            if isinstance(link, dict) and (link.get("label") or link.get("url")):
                cv["basics"]["links"].append(
                    {"label": _str(link.get("label")).strip(),
                     "url": _str(link.get("url")).strip()})

    cv["summary"] = _str(data.get("summary")).strip()

    for e in data.get("experience") or []:
        if not isinstance(e, dict):
            continue
        cv["experience"].append({
            "company": _str(e.get("company")).strip(),
            "title": _str(e.get("title")).strip(),
            "location": _str(e.get("location")).strip(),
            "start": _str(e.get("start")).strip()[:7],
            "end": (_str(e.get("end")).strip()[:7] or None),
            "bullets": _norm_bullets(e.get("bullets"), taken),
        })

    for e in data.get("education") or []:
        if not isinstance(e, dict):
            continue
        cv["education"].append({
            "institution": _str(e.get("institution")).strip(),
            "degree": _str(e.get("degree")).strip(),
            "start": _str(e.get("start")).strip()[:7],
            "end": (_str(e.get("end")).strip()[:7] or None),
            "details": _str(e.get("details")).strip(),
        })

    for s in data.get("skills") or []:
        if isinstance(s, dict):
            items = [_str(i).strip() for i in s.get("items") or [] if _str(i).strip()]
            cv["skills"].append({"group": _str(s.get("group")).strip(), "items": items})

    for p in data.get("projects") or []:
        if not isinstance(p, dict):
            continue
        cv["projects"].append({
            "name": _str(p.get("name")).strip(),
            "url": _str(p.get("url")).strip(),
            "bullets": _norm_bullets(p.get("bullets"), taken),
        })

    for c in data.get("certifications") or []:
        if isinstance(c, dict):
            cv["certifications"].append({
                "name": _str(c.get("name")).strip(),
                "issuer": _str(c.get("issuer")).strip(),
                "date": _str(c.get("date")).strip()[:7],
            })

    return cv


def load_cv(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_cv()
    with open(path) as f:
        return normalize(yaml.safe_load(f))


def dump_yaml(cv: Dict[str, Any]) -> str:
    return yaml.safe_dump(cv, sort_keys=False, allow_unicode=True, width=100)


def save_cv(cv: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """Normalize (assigning ids to new bullets) and write to disk."""
    cv = normalize(cv)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(dump_yaml(cv))
    return cv


def parse_yaml_str(text: str) -> Dict[str, Any]:
    """Parse user-edited raw YAML; raises yaml.YAMLError on bad input."""
    return normalize(yaml.safe_load(text))


def cv_is_empty(cv: Dict[str, Any]) -> bool:
    return not (cv["basics"]["name"] or cv["experience"] or cv["summary"])


def find_bullet(cv: Dict[str, Any], bullet_id: str) -> Optional[Dict[str, str]]:
    for section in ("experience", "projects"):
        for entry in cv[section]:
            for b in entry["bullets"]:
                if b["id"] == bullet_id:
                    return b
    return None
