"""Deterministic content analyzer (SPEC §5.4). Pure Python, instant, no LLM —
the LLM grammar pass lives in optimizer.grammar_check and runs on demand.

Findings: {severity: error|warn|info, category, message, bullet_id?}
severity: error = will hurt with an ATS/recruiter; warn = likely a mistake;
info = worth a look.
"""
import re
from collections import Counter
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from backend.core import optimizer

Finding = Dict[str, Any]

STOPWORDS = set("""a an and the for with to of in on at by from as is are was
were be been using used via across into over under after before during their
our its it this that these those any all more most other than then when where
which while""".split())

PAST_IRREGULAR = {
    "built", "led", "wrote", "ran", "made", "grew", "cut", "drove", "oversaw",
    "won", "held", "took", "brought", "taught", "sold", "found", "founded",
    "kept", "set", "put", "sent", "spent", "began", "gave", "got", "chose",
    "rose", "did", "saw", "came", "went", "read", "wore", "threw", "showed",
}

PRESENT_VERBS = {
    "develop", "build", "manage", "lead", "create", "design", "maintain",
    "work", "help", "oversee", "drive", "run", "write", "own", "support",
    "coordinate", "architect", "engineer", "deliver", "implement", "optimize",
    "collaborate", "mentor", "handle", "conduct", "author", "program",
}

BIAS_TERMS = [
    "young", "energetic", "youthful", "digital native", "recent graduate",
    "manpower", "chairman", "salesman", "married", "single mother",
    "date of birth", "marital status", "photo", "headshot",
]

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️←-⇿"
    "✀-➿①-⓿⭐]")


def _ym(s: Optional[str], default_month: int = 1) -> Optional[int]:
    """'2022-04' -> absolute month index; '2022' uses default_month."""
    if not s:
        return None
    m = re.match(r"(\d{4})(?:-(\d{1,2}))?$", str(s).strip())
    if not m:
        return None
    month = int(m.group(2)) if m.group(2) else default_month
    return int(m.group(1)) * 12 + min(max(month, 1), 12) - 1


def _now() -> int:
    t = date.today()
    return t.year * 12 + t.month - 1


def _all_bullets(cv):
    for e in cv["experience"]:
        for b in e["bullets"]:
            yield e, b
    for p in cv["projects"]:
        for b in p["bullets"]:
            yield p, b


def _full_text(cv) -> str:
    parts = [cv["summary"], cv["basics"]["title"]]
    parts += [b["text"] for _, b in _all_bullets(cv)]
    parts += [e.get("details", "") for e in cv["education"]]
    parts += [i for s in cv["skills"] for i in s["items"]]
    return "\n".join(p for p in parts if p)


# --- individual checks (each appends via `add`) -------------------------------

def _check_dates(cv, add):
    roles = []
    for e in cv["experience"]:
        label = f"{e['title'] or 'role'} at {e['company'] or '?'}"
        s, en = _ym(e["start"]), _ym(e["end"], default_month=12)
        if s is None:
            add("warn", "dates", f"{label}: missing or unparseable start date")
            continue
        if e["end"] and en is None:
            add("warn", "dates", f"{label}: unparseable end date")
        if en is not None and e["end"] and en < s:
            add("error", "dates", f"{label}: ends before it starts")
        roles.append((s, en if e["end"] else _now(), label))

    current = [e for e in cv["experience"] if not e["end"]]
    if len(current) > 1:
        add("warn", "dates",
            f"{len(current)} roles have no end date — only current roles "
            "should read “Present”")

    roles.sort(key=lambda r: r[0], reverse=True)
    for (s1, e1, l1), (s2, e2, l2) in zip(roles, roles[1:]):
        gap = s1 - e2 - 1
        if gap > 6:
            add("warn", "dates",
                f"{gap}-month gap between “{l2}” and “{l1}” — be ready to "
                "explain it")
        if e2 - s1 > 1:
            add("warn", "dates", f"“{l2}” and “{l1}” overlap — intentional?")


def _check_tense(cv, add):
    for e in cv["experience"]:
        ended = bool(e["end"])
        # Present-tense verbs in an *ended* role are a real error and worth
        # flagging per bullet. Past-tense in a current role is a common,
        # defensible style choice — aggregate it into one gentle note per role.
        present_in_past = []
        for b in e["bullets"]:
            words = b["text"].split()
            if not words:
                continue
            first = words[0].lower().strip(".,;:")
            if ended and first in PRESENT_VERBS:
                present_in_past.append(b["id"])
        if present_in_past:
            add("warn", "tense",
                f"Ended role at {e['company'] or 'a past job'}: "
                f"{len(present_in_past)} bullet(s) use present-tense verbs — "
                "past roles should read in past tense",
                bullet_ids=present_in_past)


def _check_consistency(cv, add):
    texts = [b["text"] for _, b in _all_bullets(cv) if b["text"]]
    dotted = sum(1 for t in texts if t.endswith("."))
    if 0 < dotted < len(texts):
        add("info", "consistency",
            f"Mixed bullet punctuation: {dotted} end with a period, "
            f"{len(texts) - dotted} don't — pick one style")

    fmts = set()
    for e in cv["experience"] + cv["education"]:
        for d in (e.get("start"), e.get("end")):
            if d:
                fmts.add("YYYY-MM" if "-" in str(d) else "YYYY")
    if len(fmts) > 1:
        add("info", "consistency",
            "Mixed date formats (some month+year, some year only)")


def _check_repetition(cv, add):
    texts = [(b["id"], b["text"]) for _, b in _all_bullets(cv) if b["text"]]

    words = Counter()
    for _, t in texts:
        toks = {w for w in re.findall(r"[a-z][a-z\-+#./]{3,}", t.lower())
                if w not in STOPWORDS}
        words.update(toks)  # once per bullet
    repeated = [w for w, n in words.most_common(8) if n >= 3]
    if repeated:
        add("warn", "repetition",
            "Overused words across bullets: " + ", ".join(f"“{w}”" for w in repeated))

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a = set(re.findall(r"\w+", texts[i][1].lower()))
            b = set(re.findall(r"\w+", texts[j][1].lower()))
            if a and b and len(a & b) / len(a | b) > 0.7:
                add("warn", "repetition",
                    f"Near-duplicate bullets: “{texts[i][1][:50]}…” and "
                    f"“{texts[j][1][:50]}…”", bullet_id=texts[j][0])

    for e in cv["experience"]:
        leads = Counter(b["text"].split()[0].lower() for b in e["bullets"]
                        if b["text"].split())
        for verb, n in leads.items():
            if n >= 3:
                add("info", "repetition",
                    f"{n} bullets at {e['company'] or 'a role'} start with "
                    f"“{verb}” — vary the leading verbs")


def _check_ats(cv, add):
    full = _full_text(cv)
    emojis = set(_EMOJI_RE.findall(full))
    if emojis:
        add("error", "ats",
            "Emoji/symbols found (" + " ".join(sorted(emojis)) +
            ") — many ATS parsers choke on these")
    for s in cv["skills"]:
        if len(s["items"]) > 20:
            add("error", "ats",
                f"Skill group “{s['group']}” has {len(s['items'])} items — "
                "trim to the ones that matter (≤ 20)")


def _check_bias(cv, add):
    for e in cv["education"]:
        end = _ym(e.get("end"), default_month=6)
        if end and (_now() - end) / 12 > 15:
            add("warn", "bias",
                f"Graduation year {str(e['end'])[:4]} is 15+ years back — "
                "consider dropping it to avoid age signalling")
    low = _full_text(cv).lower()
    hits = [t for t in BIAS_TERMS if t in low]
    if hits:
        add("warn", "bias",
            "Terms that can trigger bias: " + ", ".join(f"“{t}”" for t in hits))


def _check_readability(cv, add):
    lens = [len(b["text"].split()) for _, b in _all_bullets(cv) if b["text"]]
    if lens:
        avg = sum(lens) / len(lens)
        if avg > 24:
            add("info", "readability",
                f"Bullets average {avg:.0f} words — dense to skim; aim for "
                "15–20")
    for sent in re.split(r"(?<=[.!?])\s+", cv["summary"]):
        if len(sent.split()) > 32:
            add("info", "readability",
                f"Summary sentence is {len(sent.split())} words — split it: "
                f"“{sent[:60]}…”")


def _check_completeness(cv, add):
    if not cv["summary"]:
        add("info", "completeness", "No summary — recruiters read it first")
    for k in ("email", "phone", "location"):
        if not cv["basics"][k]:
            add("info", "completeness", f"Missing contact field: {k}")
    if not cv["skills"]:
        add("info", "completeness", "No skills section")
    for e in cv["experience"]:
        if len(e["bullets"]) < 2:
            add("info", "completeness",
                f"Only {len(e['bullets'])} bullet at "
                f"{e['company'] or 'a role'} — add at least 2")


def _check_bullet_quality(cv, add):
    by_code: Dict[str, List[str]] = {}
    for _, b in _all_bullets(cv):
        for c in optimizer.bullet_checks(b["text"]):
            by_code.setdefault(c["code"], []).append(b["id"])
    labels = {"too_long": "run long", "filler": "contain filler phrases",
              "no_metric": "have no number/metric",
              "weak_start": "start weakly"}
    for code, ids in by_code.items():
        add("info", "bullets",
            f"{len(ids)} bullet{'s' if len(ids) > 1 else ''} "
            f"{labels[code]} — use the ✨ button to fix",
            bullet_ids=ids)


def analyze(cv: Dict[str, Any]) -> List[Finding]:
    findings: List[Finding] = []

    def add(severity, category, message, **extra):
        findings.append({"severity": severity, "category": category,
                         "message": message, **extra})

    for check in (_check_dates, _check_tense, _check_consistency,
                  _check_repetition, _check_ats, _check_bias,
                  _check_readability, _check_completeness,
                  _check_bullet_quality):
        check(cv, add)

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return findings


def section_text(cv: Dict[str, Any], section: str) -> str:
    """Plain text of one section, for the LLM grammar pass."""
    if section == "summary":
        return cv["summary"]
    if section == "experience":
        return "\n".join(b["text"] for e in cv["experience"] for b in e["bullets"])
    if section == "projects":
        return "\n".join(b["text"] for p in cv["projects"] for b in p["bullets"])
    if section == "education":
        return "\n".join(f"{e['degree']}, {e['institution']}. {e['details']}"
                         for e in cv["education"])
    return ""
