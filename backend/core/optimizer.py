"""Bullet point optimizer (SPEC §5.2): instant deterministic checks + an
on-demand LLM rewrite that never invents facts (metric placeholders only)."""
import re
from typing import Any, Dict, List

from backend.llm import prompts
from backend.llm.provider import LLMProvider

MAX_WORDS = 28
MAX_CHARS = 180

FILLER_PHRASES = [
    "responsible for", "worked on", "helped with", "assisted in",
    "duties included", "in charge of", "tasked with", "participated in",
    "involved in", "was part of", "team player", "hardworking",
    "results-driven", "successfully", "various", "etc",
]

WEAK_STARTERS = {
    "responsible", "worked", "helped", "assisted", "involved", "participated",
    "tasked", "duties", "was", "were", "did", "a", "the", "my", "i", "we",
    "also", "various", "in", "and",
}

_METRIC_RE = re.compile(r"[\d%$€£]")


def bullet_checks(text: str) -> List[Dict[str, str]]:
    """Instant, LLM-free checks. Returns [{code, message}]."""
    checks: List[Dict[str, str]] = []
    words = text.split()
    if not words:
        return checks

    if len(words) > MAX_WORDS or len(text) > MAX_CHARS:
        checks.append({"code": "too_long",
                       "message": f"Long ({len(words)} words) — aim for ≤ {MAX_WORDS}"})

    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    hits = [p for p in FILLER_PHRASES if f" {p} " in low or low.strip().startswith(p)]
    if hits:
        checks.append({"code": "filler",
                       "message": "Filler phrase: " + ", ".join(f"“{h}”" for h in hits)})

    if not _METRIC_RE.search(text):
        checks.append({"code": "no_metric",
                       "message": "No number — quantify the impact if you can"})

    first = words[0].lower().strip(".,;:")
    if first in WEAK_STARTERS or first.endswith("ing"):
        checks.append({"code": "weak_start",
                       "message": f"Starts with “{words[0]}” — lead with a strong action verb"})

    return checks


def optimize(text: str, provider: LLMProvider) -> Dict[str, Any]:
    """Checks + up to 2 truthful rewrites (tightened / metric scaffold).

    Two narrow calls rather than one combined call: 3B models reliably skip the
    metric scaffold when it shares a prompt with the tightening task, so the
    placeholder variant gets its own single-purpose call when the flag is set.
    """
    checks = bullet_checks(text)
    codes = {c["code"] for c in checks}
    suggestions = []

    flags = ", ".join(c["code"].replace("_", " ") for c in checks) or "none"
    raw = provider.complete_json(
        prompts.BULLET_REWRITE, f"Bullet: {text}\nFlags: {flags}", max_tokens=300)
    if isinstance(raw, dict):
        tight = raw.get("tightened")
        if isinstance(tight, str) and tight.strip() and tight.strip() != text.strip():
            suggestions.append({"label": "Tightened", "text": tight.strip()})

    if "no_metric" in codes:
        m = provider.complete_json(prompts.BULLET_METRIC, text, max_tokens=200)
        metric = m.get("metric_variant") if isinstance(m, dict) else None
        # must contain a bracketed placeholder and no bare invented digit
        if (isinstance(metric, str) and "[" in metric and "]" in metric):
            suggestions.append({"label": "With metric placeholder",
                                "text": metric.strip()})
    return {"checks": checks, "suggestions": suggestions}


def grammar_check(text: str, provider: LLMProvider) -> List[Dict[str, str]]:
    """LLM grammar pass for one section: [{quote, issue, fix}], max 5."""
    raw = provider.complete_json(prompts.GRAMMAR, text, max_tokens=600)
    issues = raw.get("issues") if isinstance(raw, dict) else None
    out = []
    for i in issues or []:
        if (isinstance(i, dict) and i.get("quote") and i.get("fix")
                and str(i["quote"]).strip() in text):  # drop hallucinated quotes
            out.append({"quote": str(i["quote"]).strip(),
                        "issue": str(i.get("issue", "")).strip(),
                        "fix": str(i["fix"]).strip()})
    return out[:5]
