"""Cover letter generator (SPEC §5.5).

Small-model-safe, beat-by-beat pipeline:
  1. Outline (1 LLM call): 4 beats — hook, fit1, fit2, close — from the JD
     extraction + the §5.3 digest, never raw documents.
  2. Draft (1 LLM call per beat): each call sees only its beat instruction and
     the 1-2 candidate facts most relevant to it, keeping every call trivial.
  3. Assemble: greeting + paragraphs + sign-off into editable text.
The result is fully editable text; nothing is applied or sent anywhere.
"""
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from backend import config
from backend.core import summary
from backend.llm import prompts
from backend.llm.provider import LLMError, LLMProvider

BEATS = ["hook", "fit1", "fit2", "close"]
TONES = {"professional", "warm", "direct"}

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-/]{2,}")
_STOPWORDS = set("""a an and the for with to of in on at by from as is are was
were be will your our their this that these those you we they it have has had do
does did not or if so connect map candidate role requirement achievement need
express open close conversation experience work using strong""".split())


def _words(text: str) -> Set[str]:
    return {w for w in _WORD_RE.findall(text.lower())
            if len(w) > 2 and w not in _STOPWORDS}


def _relevant_facts(point: str, digest: Dict[str, Any],
                    requirements: List[str]) -> str:
    """Pick the 1-2 candidate bullets whose words best overlap the beat's plan,
    plus the digest headline facts — so each draft call sees only what it needs."""
    pw = _words(point)
    ranked = sorted(digest["strong_bullets"],
                    key=lambda b: len(pw & _words(b)), reverse=True)
    picked = [b for b in ranked[:2]]
    if not picked:
        picked = digest["strong_bullets"][:1]
    facts = [f"{digest['years']} years of experience as "
             f"{digest['current_title'] or 'a professional'}.",
             "Core skills: " + ", ".join(digest["top_skills"][:6]) + "."]
    facts += picked
    return " ".join(facts)


def _requirements(extraction: Dict[str, Any]) -> List[str]:
    reqs = list(extraction.get("must_have_qualifications") or [])
    reqs += list(extraction.get("hard_skills") or [])[:6]
    return reqs[:10]


def outline(digest: Dict[str, Any], extraction: Dict[str, Any],
            company: str, role: str, provider: LLMProvider,
            emphasize: str = "") -> List[Dict[str, str]]:
    """One LLM call → 4 beat plans (SPEC §5.5 step 1)."""
    reqs = _requirements(extraction)
    user = (f"Role: {role or extraction.get('target_title') or 'the role'} at "
            f"{company or 'the company'}. Top requirements: "
            f"{'; '.join(reqs) or 'not stated'}. Candidate digest: "
            f"{digest['years']} yrs as {digest['current_title'] or 'professional'}; "
            f"{'; '.join(digest['strong_bullets']) or 'no highlights'}; "
            f"skills {', '.join(digest['top_skills']) or 'not stated'}.")
    if emphasize.strip():
        user += f" Points to emphasize: {emphasize.strip()}."
    raw = provider.complete_json(prompts.LETTER_OUTLINE, user, max_tokens=400)
    beats = raw.get("beats") if isinstance(raw, dict) else None
    by_name = {}
    for b in beats or []:
        if isinstance(b, dict) and b.get("name") and b.get("point"):
            by_name[str(b["name"]).strip().lower()] = str(b["point"]).strip()
    # guarantee all four beats exist, in order, with a sane fallback plan
    fallback = {
        "hook": f"Open with interest in the {role or 'role'} at "
                f"{company or 'the company'} and relevant experience.",
        "fit1": "Connect a top achievement to a key job requirement.",
        "fit2": "Connect a second achievement to another requirement.",
        "close": "Express enthusiasm and invite a conversation.",
    }
    return [{"name": n, "point": by_name.get(n) or fallback[n]} for n in BEATS]


def draft_beat(beat: Dict[str, str], digest: Dict[str, Any],
               extraction: Dict[str, Any], tone: str,
               provider: LLMProvider) -> str:
    """One LLM call → one paragraph for a single beat (SPEC §5.5 step 2)."""
    facts = _relevant_facts(beat["point"], digest, _requirements(extraction))
    user = (f"Tone: {tone}\nBeat: {beat['point']}\nRelevant facts: {facts}")
    raw = provider.complete_json(prompts.LETTER_BEAT, user,
                                 temperature=0.5, max_tokens=300)
    para = raw.get("paragraph") if isinstance(raw, dict) else None
    return re.sub(r"\s+", " ", str(para).strip()) if para else ""


def _greeting(company: str) -> str:
    return f"Dear {company} Hiring Team," if company.strip() else "Dear Hiring Team,"


def generate(cv: Dict[str, Any], extraction: Dict[str, Any],
             company: str, role: str, provider: LLMProvider,
             tone: str = "professional", emphasize: str = "") -> Dict[str, Any]:
    """Full pipeline → assembled, editable letter text (SPEC §5.5 steps 1-3).

    Returns the beats and the stitched body so the UI can show the plan and let
    the user edit the prose. A failed beat becomes an empty paragraph (its plan
    is still shown) rather than losing the whole letter."""
    tone = tone if tone in TONES else "professional"
    digest = summary.compute_digest(cv)
    beats = outline(digest, extraction, company, role, provider, emphasize)

    paragraphs, errors = [], []
    for beat in beats:
        try:
            para = draft_beat(beat, digest, extraction, tone, provider)
        except LLMError as e:
            errors.append(str(e))
            para = ""
        beat["paragraph"] = para
        if para:
            paragraphs.append(para)

    if not paragraphs:
        raise LLMError("Model produced no letter paragraphs; try again.")

    body = "\n\n".join([_greeting(company), *paragraphs,
                        "Sincerely,", cv["basics"]["name"] or ""])
    return {"beats": beats, "body": body.strip(), "tone": tone, "errors": errors}


# --- save (deterministic) --------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def save_letter(body: str, company: str) -> Path:
    """Persist the edited letter text as Markdown in data/letters/, returning the
    path (the .pdf sits beside it after export)."""
    slug = _slug(company) or "letter"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    config.LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LETTERS_DIR / f"letter-{slug}-{stamp}.md"
    path.write_text(body.rstrip() + "\n")
    return path
