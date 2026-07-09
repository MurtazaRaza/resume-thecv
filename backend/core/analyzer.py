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


# --- ATS score (deterministic, 0–100) ----------------------------------------
#
# A recruiter-side ATS does two things that a resume can help or hurt: parse the
# document into clean fields, and match it against a role. We can't see the role
# here, so this score measures *parse-ability and hygiene* only — the things
# that make an ATS mangle or down-rank a resume regardless of the job. It is a
# weighted rollup of six categories, each scored 0–1 by pure rules (no LLM), so
# the same CV always yields the same number.

ATS_WEIGHTS = {
    "contact": 15,      # ATS needs to extract who you are and how to reach you
    "parsing": 25,      # emoji/symbols, oversized skill lists, links → parse errors
    "sections": 15,     # standard sections present and non-empty
    "keywords": 20,     # quantified, skill-dense bullets are what matchers index
    "formatting": 15,   # consistent dates/punctuation, sane bullet lengths
    "hygiene": 10,      # tense, gaps, bias/age signals, overused words
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _score_contact(cv) -> float:
    b = cv["basics"]
    pts = 0.0
    if b["name"].strip():
        pts += 0.30
    if _EMAIL_RE.match(b["email"].strip()):
        pts += 0.30
    elif b["email"].strip():
        pts += 0.10  # present but malformed — ATS may still choke on it
    if b["phone"].strip():
        pts += 0.20
    if b["location"].strip():
        pts += 0.10
    if b["title"].strip():
        pts += 0.10
    return min(pts, 1.0)


def _score_parsing(cv) -> float:
    """1.0 = clean. Each hard parse hazard subtracts."""
    full = _full_text(cv)
    pts = 1.0
    if _EMOJI_RE.findall(full):
        pts -= 0.5  # emoji/symbols are the single worst offender for parsers
    oversized = sum(1 for s in cv["skills"] if len(s["items"]) > 20)
    pts -= min(oversized, 2) * 0.2
    # bare/untitled links read as noise; a labelled link parses cleanly
    bad_links = sum(1 for l in cv["basics"].get("links", [])
                    if isinstance(l, dict) and l.get("url")
                    and not str(l.get("label", "")).strip())
    if bad_links:
        pts -= 0.15
    return max(pts, 0.0)


def _score_sections(cv) -> float:
    have = 0
    checks = [
        bool(cv["summary"].strip()),
        bool(cv["experience"]),
        bool(cv["education"]),
        bool(cv["skills"]),
    ]
    have = sum(1 for c in checks if c)
    return have / len(checks)


def _score_keywords(cv) -> float:
    """Reward quantified, weakly-flagged-free bullets and a real skills section."""
    bullets = [b["text"] for _, b in _all_bullets(cv) if b["text"].strip()]
    if not bullets:
        return 0.0 if not cv["skills"] else 0.3
    flagged = 0
    quantified = 0
    for t in bullets:
        codes = {c["code"] for c in optimizer.bullet_checks(t)}
        if codes & {"no_metric", "filler", "weak_start"}:
            flagged += 1
        if not (codes & {"no_metric"}):
            quantified += 1
    clean_ratio = 1 - flagged / len(bullets)
    quant_ratio = quantified / len(bullets)
    skills_pts = 1.0 if any(s["items"] for s in cv["skills"]) else 0.0
    return 0.45 * clean_ratio + 0.35 * quant_ratio + 0.20 * skills_pts


def _score_formatting(cv) -> float:
    pts = 1.0
    texts = [b["text"] for _, b in _all_bullets(cv) if b["text"].strip()]
    if texts:
        dotted = sum(1 for t in texts if t.endswith("."))
        if 0 < dotted < len(texts):
            pts -= 0.25  # mixed bullet punctuation
        lens = [len(t.split()) for t in texts]
        avg = sum(lens) / len(lens)
        if avg > 24:
            pts -= 0.25  # dense, hard-to-parse bullets
    fmts = set()
    for e in cv["experience"] + cv["education"]:
        for d in (e.get("start"), e.get("end")):
            if d:
                fmts.add("YYYY-MM" if "-" in str(d) else "YYYY")
    if len(fmts) > 1:
        pts -= 0.25  # mixed date formats confuse date extractors
    return max(pts, 0.0)


def _score_hygiene(cv, findings: List[Finding]) -> float:
    """Deduct for the non-parse issues the rules engine already surfaced."""
    pts = 1.0
    cats = Counter(f["category"] for f in findings
                   if f["severity"] in ("error", "warn"))
    for cat in ("tense", "dates", "bias", "repetition"):
        if cats.get(cat):
            pts -= 0.25
    return max(pts, 0.0)


def ats_score(cv: Dict[str, Any],
              findings: Optional[List[Finding]] = None) -> Dict[str, Any]:
    """0–100 ATS-friendliness score with a per-category breakdown.

    Measures parse-ability and hygiene, not fit to a specific job (no JD here).
    `findings` is reused if the caller already ran analyze(); otherwise computed.
    """
    if findings is None:
        findings = analyze(cv)

    parts = {
        "contact": _score_contact(cv),
        "parsing": _score_parsing(cv),
        "sections": _score_sections(cv),
        "keywords": _score_keywords(cv),
        "formatting": _score_formatting(cv),
        "hygiene": _score_hygiene(cv, findings),
    }

    # Parsing/formatting/hygiene reward the *absence* of problems, so an empty
    # CV would earn them for free. Scale them by how much content exists, so a
    # blank resume can't score well on "nothing to complain about".
    has_bullets = any(b["text"].strip() for _, b in _all_bullets(cv))
    if not has_bullets:
        for k in ("parsing", "formatting", "hygiene"):
            parts[k] *= 0.3

    total_weight = sum(ATS_WEIGHTS.values())
    breakdown = []
    weighted = 0.0
    for key, weight in ATS_WEIGHTS.items():
        frac = max(0.0, min(parts[key], 1.0))
        earned = frac * weight
        weighted += earned
        breakdown.append({
            "key": key,
            "label": key.capitalize(),
            "earned": round(earned),
            "max": weight,
            "frac": round(frac, 3),
        })

    score = round(weighted / total_weight * 100)
    if score >= 80:
        band = "good"
    elif score >= 60:
        band = "mid"
    else:
        band = "low"
    return {"score": score, "band": band, "breakdown": breakdown}


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
