"""Onboarding import (SPEC §4): PDF/DOCX/pasted text -> CV dict for review.

Deterministic first: extract raw text, split into sections by header keywords.
Then one small LLM call per detected section converts it to the schema. The
result is never saved directly — the user reviews it in the editor.
"""
import io
import re
from typing import Any, Dict, List, Tuple

from backend.core import cv_model
from backend.llm import prompts
from backend.llm.provider import LLMError, LLMProvider

# Header keywords -> canonical section. Order matters only for tie-breaking;
# matching is against a whole (short) line, case-insensitive.
SECTION_HEADERS = {
    "summary": ["summary", "professional summary", "profile", "about",
                "about me", "objective"],
    "experience": ["experience", "work experience", "employment",
                   "employment history", "professional experience",
                   "work history"],
    "education": ["education", "academic background", "qualifications"],
    "skills": ["skills", "technical skills", "core skills", "technologies",
               "competencies", "tech stack"],
    "projects": ["projects", "personal projects", "side projects",
                 "selected projects"],
    "certifications": ["certifications", "certificates", "licenses",
                       "licenses & certifications", "courses"],
}

_HEADER_LOOKUP = {kw: section
                  for section, kws in SECTION_HEADERS.items() for kw in kws}

# longest keyword first so "professional experience" beats "experience"
_HEADER_PATTERNS = [
    (re.compile(r"[\s&|/,]+".join(re.escape(w) for w in kw.split()) + r"\b[:\s]*",
                re.IGNORECASE), kw, section)
    for kw, section in sorted(_HEADER_LOOKUP.items(), key=lambda x: -len(x[0]))
]

_BULLET_MARKS = "●•▪‣○◦"

# "Languages: C++, C#, .NET" — a labelled list row (skills, contact rows, …)
_LABELLED_ROW_RE = re.compile(r"[A-Z][\w&/+.# ]{0,34}:\s")


def extract_text(filename: str, blob: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(blob))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx"):
        import docx
        doc = docx.Document(io.BytesIO(blob))
        return "\n".join(p.text for p in doc.paragraphs)
    return blob.decode("utf-8", errors="replace")


def _match_header(line: str) -> "Tuple[str, str] | None":
    """If `line` starts with a section header, return (section, remainder).

    Guards against word-wrap fragments from PDF extraction (a bullet whose
    last word lands on its own line, e.g. 'projects.'): the header text must
    not be all-lowercase and must not be followed by sentence punctuation.
    Combined headers ('CERTIFICATIONS & SKILLS ...') match on the first
    keyword and any further keywords/joiners are consumed too.
    """
    for pattern, kw, section in _HEADER_PATTERNS:
        m = pattern.match(line)
        if not m:
            continue
        matched = m.group(0).strip()
        if matched.islower():
            return None  # wrapped sentence fragment, not a header
        rest = line[m.end():]
        if rest[:1] in (".", ",", ";", ")"):
            return None
        # consume trailing sibling keywords: "CERTIFICATIONS & SKILLS"
        changed = True
        while changed:
            changed = False
            trimmed = re.sub(r"^([&|/,+]|\band\b|\s)+", "", rest, flags=re.IGNORECASE)
            for p2, _, _ in _HEADER_PATTERNS:
                m2 = p2.match(trimmed)
                if m2 and not m2.group(0).strip().islower():
                    rest = trimmed[m2.end():]
                    changed = True
                    break
        return section, rest.strip()
    return None


def _clean_lines(text: str) -> List[str]:
    """Undo PDF-extraction damage: put every bullet on its own line, collapse
    whitespace, and re-join word-wrap fragments into full lines."""
    for mark in _BULLET_MARKS:
        text = text.replace(mark, "\n" + mark + " ")
    lines = []
    for raw in text.splitlines():
        s = re.sub(r"\s+", " ", raw).strip()
        if s and s not in _BULLET_MARKS:
            lines.append(s)

    merged: List[str] = []
    for s in lines:
        starts_block = (s[0] in _BULLET_MARKS + "-*"
                        or _LABELLED_ROW_RE.match(s) is not None
                        or _match_header(s) is not None)
        can_extend = (merged
                      and not merged[-1].endswith((".", "!", "?", ":", ";"))
                      and _match_header(merged[-1]) is None)
        if starts_block or not can_extend:
            merged.append(s)
        else:
            merged[-1] += " " + s
    return merged


def split_sections(text: str) -> Dict[str, str]:
    """Split cleaned resume text on section-header lines. Everything before
    the first recognized header is the 'basics' block."""
    sections: List[Tuple[str, List[str]]] = [("basics", [])]
    for line in _clean_lines(text):
        hit = _match_header(line)
        if hit:
            section, remainder = hit
            sections.append((section, [remainder] if remainder else []))
        else:
            sections[-1][1].append(line)
    merged: Dict[str, str] = {}
    for name, lines in sections:
        body = "\n".join(lines).strip()
        if body:
            merged[name] = (merged[name] + "\n" + body) if name in merged else body
    return merged


def parse_skills_deterministic(body: str) -> List[Dict[str, Any]]:
    """Parse 'Group: a, b, c' rows without an LLM. Returns [] if the section
    doesn't look like labelled rows (caller falls back to the LLM)."""
    groups = []
    for line in body.splitlines():
        m = re.match(r"\s*([A-Z][\w&/+.# ]{0,34}):\s*(.+)", line)
        if not m:
            continue
        # rstrip only: sentence-final periods go, ".NET"-style names survive
        items = [i.strip().rstrip(".") or i.strip()
                 for i in re.split(r"[,;|]", m.group(2)) if i.strip()]
        if items:
            groups.append({"group": m.group(1).strip(), "items": items})
    return groups if len(groups) >= 2 else []


_SECTION_PROMPTS = {
    "experience": prompts.IMPORT_EXPERIENCE,
    "education": prompts.IMPORT_EDUCATION,
    "skills": prompts.IMPORT_SKILLS,  # only when deterministic parse fails
    "projects": prompts.IMPORT_PROJECTS,
    "certifications": prompts.IMPORT_CERTIFICATIONS,
}

# Keep each per-section call well inside num_ctx=4096.
_MAX_SECTION_CHARS = 6000


def parse_resume(text: str, provider: LLMProvider) -> Dict[str, Any]:
    """Sectioned text -> normalized CV dict. Sequential LLM calls (8GB rule).
    Sections the model chokes on are skipped rather than failing the import."""
    found = split_sections(text)
    result: Dict[str, Any] = {}
    errors: List[str] = []

    basics_block = found.get("basics", "")[:1500] or text[:1500]
    try:
        parsed = provider.complete_json(prompts.IMPORT_BASICS, basics_block)
        if isinstance(parsed, dict):
            result["basics"] = parsed
    except LLMError as e:
        errors.append(f"basics: {e}")

    # summary needs no LLM: the section body IS the summary
    if found.get("summary"):
        result["summary"] = " ".join(found["summary"].split())

    if found.get("skills"):
        result["skills"] = parse_skills_deterministic(found["skills"])

    for section, system in _SECTION_PROMPTS.items():
        body = found.get(section)
        if not body or result.get(section):
            continue
        try:
            parsed = provider.complete_json(system, body[:_MAX_SECTION_CHARS],
                                            max_tokens=1500)
            if isinstance(parsed, dict) and section in parsed:
                result[section] = parsed[section]
        except LLMError as e:
            errors.append(f"{section}: {e}")

    cv = cv_model.normalize(result)
    cv["_import_errors"] = errors  # stripped by normalize() on next save
    return cv
