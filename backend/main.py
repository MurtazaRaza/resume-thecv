"""FastAPI app — all routes. Pages are server-rendered Jinja2 (frontend/
templates); JSON endpoints exist only where the editor needs structured data.

All per-person state lives under a profile resolved per request from the
`cve_profile` cookie (see core/profiles.py). Routes take the resolved Profile
via the current_profile dependency and pass profile.* paths into every core
call, so two browsers with different cookies operate on separate data.
Run: .venv/bin/uvicorn backend.main:app --port 8877 --reload
"""
import datetime
import json
import shutil

import yaml
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend import config
from backend.core import (analyzer, bank, cover_letter, cv_model, importer,
                          optimizer, profiles, render, summary, tailor, tracker)
from backend.core.profiles import Profile
from backend.llm.provider import LLMError, get_provider

app = FastAPI(title="Resume the CV")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def current_profile(request: Request) -> Profile:
    """Resolve the cve_profile cookie to a Profile, falling back to the first
    existing profile (auto-creating `default` if none exist). Also ensures the
    resolved profile's tracker db is initialized."""
    prof = profiles.resolve(request.cookies.get(profiles.COOKIE_NAME))
    tracker.init_db(prof.tracker_db)
    return prof


@app.on_event("startup")
def startup() -> None:
    config.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profiles.list_profiles()  # auto-create `default` if none exist
    if not config.TYPST_BIN:
        print("WARNING: typst binary not found (tools/typst or PATH) — "
              "PDF preview/export disabled until installed.")


def page_ctx(request: Request, profile: Profile, **extra):
    return {"request": request, "typst_ok": bool(config.TYPST_BIN),
            "model": config.MODEL, "profile": profile,
            "profiles": profiles.list_profiles(), **extra}


def _provider_up() -> bool:
    """Health check for the active provider; Anthropic stub is always "ok"
    since it has nothing to probe yet."""
    if config.LLM_PROVIDER in ("ollama", "gemini"):
        return get_provider().is_up()
    return True


# --- profiles ------------------------------------------------------------------

@app.get("/api/profile")
def list_profiles_route(profile: Profile = Depends(current_profile)):
    return {"active": profile.slug,
            "profiles": [{"slug": p.slug, "name": p.name}
                         for p in profiles.list_profiles()]}


@app.post("/api/profile")
async def create_profile_route(request: Request):
    name = ((await request.json()).get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "A profile name is required"},
                            status_code=422)
    prof = profiles.create_profile(name)
    resp = JSONResponse({"slug": prof.slug, "name": prof.name})
    resp.set_cookie(profiles.COOKIE_NAME, prof.slug, max_age=60 * 60 * 24 * 365,
                    samesite="lax")
    return resp


@app.post("/api/profile/switch")
async def switch_profile_route(request: Request):
    slug = ((await request.json()).get("slug") or "").strip()
    if profiles.get_profile(slug) is None:
        return JSONResponse({"error": "Unknown profile"}, status_code=404)
    resp = JSONResponse({"ok": True, "slug": slug})
    resp.set_cookie(profiles.COOKIE_NAME, slug, max_age=60 * 60 * 24 * 365,
                    samesite="lax")
    return resp


@app.delete("/api/profile/{slug}")
def delete_profile_route(slug: str, profile: Profile = Depends(current_profile)):
    if profiles.get_profile(slug) is None:
        return JSONResponse({"error": "Unknown profile"}, status_code=404)
    try:
        profiles.delete_profile(slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    resp = JSONResponse({"ok": True})
    if slug == profile.slug:
        # switch the cookie to whatever profile remains
        resp.set_cookie(profiles.COOKIE_NAME, profiles.list_profiles()[0].slug,
                        max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# --- pages -------------------------------------------------------------------

@app.get("/")
def home(profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    if cv_model.cv_is_empty(cv):
        return RedirectResponse("/import")
    # /tracker is the app's home once a CV exists (SPEC §5.6)
    return RedirectResponse("/tracker")


@app.get("/editor")
def editor(request: Request, profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    return templates.TemplateResponse("editor.html", page_ctx(
        request, profile, cv=cv, cv_yaml=cv_model.dump_yaml(cv)))


@app.get("/import")
def import_page(request: Request, profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    return templates.TemplateResponse("import.html", page_ctx(
        request, profile, cv_empty=cv_model.cv_is_empty(cv),
        ollama_ok=_provider_up()))


# --- CV load/save --------------------------------------------------------------

@app.get("/api/cv")
def get_cv(profile: Profile = Depends(current_profile)):
    return cv_model.load_cv(profile.cv_path)


@app.put("/api/cv")
async def put_cv(request: Request, profile: Profile = Depends(current_profile)):
    return cv_model.save_cv(await request.json(), profile.cv_path)


@app.get("/api/cv/yaml")
def get_cv_yaml(profile: Profile = Depends(current_profile)):
    return PlainTextResponse(cv_model.dump_yaml(cv_model.load_cv(profile.cv_path)))


@app.post("/api/cv/yaml/preview")
async def cv_yaml_preview(request: Request):
    """Convert editor form state to YAML without saving (YAML tab sync)."""
    return PlainTextResponse(cv_model.dump_yaml(cv_model.normalize(await request.json())))


@app.put("/api/cv/yaml")
async def put_cv_yaml(request: Request, profile: Profile = Depends(current_profile)):
    text = (await request.body()).decode("utf-8")
    try:
        cv = cv_model.save_cv(cv_model.parse_yaml_str(text), profile.cv_path)
    except yaml.YAMLError as e:
        return JSONResponse({"error": f"Invalid YAML: {e}"}, status_code=422)
    return cv


# --- rendering -----------------------------------------------------------------

@app.post("/api/cv/render")
def render_cv(profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    try:
        render.render_txt(cv, profile.out_dir)
        pdf = render.render_pdf(cv, profile.out_dir)
    except render.RenderError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    stamp = int(pdf.stat().st_mtime)
    return {"pdf_url": f"/out/cv.pdf?v={stamp}", "txt_url": f"/out/cv.txt?v={stamp}"}


@app.get("/out/{filename}")
def out_file(filename: str, profile: Profile = Depends(current_profile)):
    base = profile.out_dir
    path = (base / filename).resolve()
    if base.resolve() not in path.parents or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


# Serve tracker-linked artifacts (tailored CV snapshots, cover letter PDFs/md)
# from the *active profile's* dirs. Restricted to these two kinds and
# path-traversal guarded like /out.
_ARTIFACT_KINDS = {"versions", "letters"}


def _artifact_base(profile: Profile, kind: str):
    return {"versions": profile.versions_dir,
            "letters": profile.letters_dir}.get(kind)


@app.get("/data/{kind}/{filename}")
def artifact_file(kind: str, filename: str,
                  profile: Profile = Depends(current_profile)):
    base = _artifact_base(profile, kind)
    if base is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = (base / filename).resolve()
    if base.resolve() not in path.parents or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


# --- analyzer + bullet optimizer (M2) -------------------------------------------

@app.post("/api/analyze")
async def analyze_cv(request: Request):
    """Rules engine on the *current* editor state (body = CV JSON)."""
    cv = cv_model.normalize(await request.json())
    findings = analyzer.analyze(cv)
    return {"findings": findings, "ats": analyzer.ats_score(cv, findings)}


@app.post("/api/analyze/grammar")
async def grammar_pass(request: Request):
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or {})
    text = analyzer.section_text(cv, data.get("section", "summary"))
    if not text.strip():
        return {"issues": [], "empty": True}
    try:
        return {"issues": optimizer.grammar_check(text, get_provider("grammar"))}
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/bullets/optimize")
async def optimize_bullet(request: Request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Empty bullet"}, status_code=422)
    try:
        return optimizer.optimize(text, get_provider("bullet_optimize"))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# --- summary + headline generator (M4, §5.3) ------------------------------------

@app.post("/api/summary/generate")
async def summary_generate(request: Request,
                           profile: Profile = Depends(current_profile)):
    """3 summary variants from a deterministic digest of the posted CV state.
    Body may carry the live editor CV so unsaved edits feed the digest."""
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or cv_model.load_cv(profile.cv_path))
    try:
        return summary.generate_summaries(
            cv, get_provider("summary"), target_title=str(data.get("target_title") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/headline/generate")
async def headline_generate(request: Request,
                            profile: Profile = Depends(current_profile)):
    """3 plain-text headline options for basics.title (same digest, tiny call)."""
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or cv_model.load_cv(profile.cv_path))
    try:
        return summary.generate_headlines(
            cv, get_provider("headline"), target_title=str(data.get("target_title") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# --- job tailoring (M3) ----------------------------------------------------------

@app.get("/tailor")
def tailor_page(request: Request, profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    return templates.TemplateResponse("tailor.html", page_ctx(
        request, profile, cv_empty=cv_model.cv_is_empty(cv),
        applications=tracker.list_applications(profile.tracker_db),
        skill_groups=[g["group"] for g in cv["skills"] if g["group"]],
        current_title=cv["basics"]["title"],
        ollama_ok=_provider_up()))


def _tailoring_context(profile: Profile, app_id):
    """Load the application + its cached JD extraction, or a 4xx response."""
    entry = tracker.get_application(profile.tracker_db, int(app_id)) if app_id else None
    if entry is None:
        return None, None, JSONResponse({"error": "Application not found"},
                                        status_code=404)
    if not entry["jd_extraction"]:
        return None, None, JSONResponse(
            {"error": "Run “Extract & match” first"}, status_code=422)
    return entry, json.loads(entry["jd_extraction"]), None


@app.get("/api/tailor/application/{app_id}")
def tailor_load_application(app_id: int,
                            profile: Profile = Depends(current_profile)):
    """Reload a saved application's cached JD + extraction so picking it from
    the dropdown restores its match report without re-running the model."""
    entry, extraction, err = _tailoring_context(profile, app_id)
    if err:
        return err
    cv = cv_model.load_cv(profile.cv_path)
    return {"application_id": entry["id"], "company": entry["company"],
            "jd_text": entry["jd_text"] or "",
            "extraction": extraction, "match": tailor.match(cv, extraction),
            "current_title": cv["basics"]["title"],
            "skill_groups": [g["group"] for g in cv["skills"] if g["group"]]}


@app.post("/api/tailor/preview")
async def tailor_preview(request: Request,
                         profile: Profile = Depends(current_profile)):
    """Server-side render of the tailored CV for the live diff preview. Returns
    both the master and tailored YAML so the client can show a unified diff of
    exactly what a save would change. Reuses apply_tailoring + dump_yaml so the
    tailored side is byte-identical to a saved snapshot. No LLM, no typst."""
    data = await request.json()
    entry, extraction, err = _tailoring_context(profile, data.get("application_id"))
    if err:
        return err
    master = cv_model.load_cv(profile.cv_path)
    tailored = tailor.apply_tailoring(
        master, extraction,
        accepted=data.get("accepted") or [],
        add_skills=data.get("add_skills") or [],
        skills_group=str(data.get("skills_group") or ""),
        new_title=str(data.get("new_title") or ""))
    return {"master_yaml": cv_model.dump_yaml(master),
            "tailored_yaml": cv_model.dump_yaml(tailored)}


@app.post("/api/tailor/extract")
async def tailor_extract(request: Request,
                         profile: Profile = Depends(current_profile)):
    data = await request.json()
    jd_text = (data.get("jd_text") or "").strip()
    if not jd_text:
        return JSONResponse({"error": "Paste the job description first"},
                            status_code=422)
    app_id = data.get("application_id")
    if app_id:
        entry = tracker.get_application(profile.tracker_db, int(app_id))
        if entry is None:
            return JSONResponse({"error": "Application not found"}, status_code=404)
        company = entry["company"]
    else:
        company = (data.get("company") or "").strip()
        role = (data.get("role") or "").strip()
        if not company or not role:
            return JSONResponse({"error": "Company and role are required for a "
                                          "new application"}, status_code=422)
        app_id = tracker.create_application(profile.tracker_db, company, role,
                                            (data.get("url") or "").strip())
    try:
        extraction = tailor.extract(jd_text, get_provider("jd_extract"))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    tracker.update_application(profile.tracker_db, app_id, jd_text=jd_text,
                               jd_extraction=json.dumps(extraction))
    cv = cv_model.load_cv(profile.cv_path)
    return {"application_id": app_id, "company": company,
            "extraction": extraction, "match": tailor.match(cv, extraction),
            "current_title": cv["basics"]["title"],
            "skill_groups": [g["group"] for g in cv["skills"] if g["group"]]}


@app.post("/api/tailor/suggest")
async def tailor_suggest(request: Request,
                         profile: Profile = Depends(current_profile)):
    data = await request.json()
    entry, extraction, err = _tailoring_context(profile, data.get("application_id"))
    if err:
        return err
    cv = cv_model.load_cv(profile.cv_path)
    result = tailor.suggest(cv, extraction, entry["jd_text"] or "",
                            get_provider("tailor_suggest"),
                            guidance=str(data.get("guidance") or ""))
    # deterministic bank matches (no LLM): projects/experiences from this
    # profile's bank that cover the JD's still-missing keywords (SPEC §3)
    result["bank_suggestions"] = bank.suggest_for_extraction(
        bank.load_bank(profile.bank_path), extraction, cv=cv)
    return result


@app.post("/api/tailor/apply")
async def tailor_apply(request: Request,
                       profile: Profile = Depends(current_profile)):
    data = await request.json()
    entry, extraction, err = _tailoring_context(profile, data.get("application_id"))
    if err:
        return err
    cv = cv_model.load_cv(profile.cv_path)
    before = tailor.match(cv, extraction)["coverage"]
    tailored = tailor.apply_tailoring(
        cv, extraction,
        accepted=data.get("accepted") or [],
        add_skills=data.get("add_skills") or [],
        skills_group=str(data.get("skills_group") or ""),
        new_title=str(data.get("new_title") or ""))
    after = tailor.match(tailored, extraction)["coverage"]
    path = tailor.save_snapshot(tailored, entry["company"], profile.versions_dir)
    rel = str(path.relative_to(config.PROJECT_ROOT))
    tracker.update_application(profile.tracker_db, entry["id"],
                               cv_version_path=rel, match_score=after)
    return {"snapshot": rel, "coverage_before": before, "coverage_after": after}


# --- cover letters (M4, §5.5) ---------------------------------------------------

@app.get("/letters/new")
def letters_new_page(request: Request, profile: Profile = Depends(current_profile)):
    cv = cv_model.load_cv(profile.cv_path)
    # only applications with a cached JD extraction can seed a letter's requirements
    apps = [a for a in tracker.list_applications(profile.tracker_db)
            if (tracker.get_application(profile.tracker_db, a["id"]) or {}).get("jd_extraction")]
    return templates.TemplateResponse("letters.html", page_ctx(
        request, profile, cv_empty=cv_model.cv_is_empty(cv), applications=apps,
        ollama_ok=_provider_up()))


@app.post("/api/letters/generate")
async def letters_generate(request: Request,
                           profile: Profile = Depends(current_profile)):
    data = await request.json()
    entry, extraction, err = _tailoring_context(profile, data.get("application_id"))
    if err:
        return err
    cv = cv_model.load_cv(profile.cv_path)
    try:
        result = cover_letter.generate(
            cv, extraction, entry["company"], entry["role"], get_provider("letters"),
            tone=str(data.get("tone") or "professional"),
            emphasize=str(data.get("emphasize") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    result["company"] = entry["company"]
    return result


@app.post("/api/letters/export")
async def letters_export(request: Request,
                         profile: Profile = Depends(current_profile)):
    """Save the (edited) letter as .md + .pdf in the profile's letters/, linked
    to the application. Body: {application_id, body}."""
    data = await request.json()
    entry, _extraction, err = _tailoring_context(profile, data.get("application_id"))
    if err:
        return err
    body = (data.get("body") or "").strip()
    if not body:
        return JSONResponse({"error": "Nothing to export — the letter is empty."},
                            status_code=422)
    cv = cv_model.load_cv(profile.cv_path)
    md_path = cover_letter.save_letter(body, entry["company"], profile.letters_dir)
    try:
        pdf_tmp = render.render_letter_pdf(cv, body, profile.out_dir, entry["company"])
    except render.RenderError as e:
        # still keep the .md; the PDF is optional if typst is missing
        rel_md = str(md_path.relative_to(config.PROJECT_ROOT))
        tracker.update_application(profile.tracker_db, entry["id"],
                                   cover_letter_path=rel_md)
        return JSONResponse({"error": str(e), "markdown": rel_md}, status_code=500)
    pdf_path = md_path.with_suffix(".pdf")
    shutil.copy(pdf_tmp, pdf_path)
    rel_pdf = str(pdf_path.relative_to(config.PROJECT_ROOT))
    tracker.update_application(profile.tracker_db, entry["id"],
                               cover_letter_path=rel_pdf)
    stamp = int(pdf_path.stat().st_mtime)
    return {"markdown": str(md_path.relative_to(config.PROJECT_ROOT)),
            "pdf": rel_pdf, "pdf_url": f"/out/letter.pdf?v={stamp}"}


# --- tracker (M5, §5.6) ---------------------------------------------------------

@app.get("/tracker")
def tracker_page(request: Request, profile: Profile = Depends(current_profile)):
    return templates.TemplateResponse("tracker.html", page_ctx(
        request, profile, dashboard=tracker.dashboard(profile.tracker_db),
        statuses=tracker.STATUSES))


@app.get("/tracker/{app_id}")
def tracker_detail_page(request: Request, app_id: int,
                        profile: Profile = Depends(current_profile)):
    entry = tracker.get_application(profile.tracker_db, app_id)
    if entry is None:
        return RedirectResponse("/tracker")
    extraction = None
    if entry["jd_extraction"]:
        try:
            extraction = json.loads(entry["jd_extraction"])
        except (ValueError, TypeError):
            extraction = None
    return templates.TemplateResponse("tracker_detail.html", page_ctx(
        request, profile, app=entry, extraction=extraction,
        statuses=tracker.STATUSES,
        cv_version_url=_artifact_url(entry["cv_version_path"]),
        cover_letter_url=_artifact_url(entry["cover_letter_path"]),
        history=tracker.get_status_history(profile.tracker_db, app_id)))


def _artifact_url(rel_path):
    """Map a stored 'data/profiles/<slug>/versions/...' or '.../letters/...'
    path to its servable /data/<kind>/<file> URL (the active profile serves
    it), or None if it isn't one of those."""
    if not rel_path:
        return None
    parts = rel_path.replace("\\", "/").split("/")
    for kind in _ARTIFACT_KINDS:
        if kind in parts:
            return f"/data/{kind}/{parts[-1]}"
    return None


@app.post("/api/applications")
async def create_application(request: Request,
                             profile: Profile = Depends(current_profile)):
    data = await request.json()
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    if not company or not role:
        return JSONResponse({"error": "Company and role are required"},
                            status_code=422)
    app_id = tracker.create_application(profile.tracker_db, company, role,
                                        (data.get("url") or "").strip())
    return {"id": app_id}


@app.put("/api/applications/{app_id}")
async def update_application(app_id: int, request: Request,
                             profile: Profile = Depends(current_profile)):
    if tracker.get_application(profile.tracker_db, app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    data = await request.json()
    fields = {k: v for k, v in data.items() if k in tracker._UPDATABLE}
    unknown = set(data) - tracker._UPDATABLE
    if unknown:
        return JSONResponse(
            {"error": f"Cannot update fields: {', '.join(sorted(unknown))}"},
            status_code=422)
    try:
        tracker.update_application(profile.tracker_db, app_id, **fields)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"ok": True}


@app.put("/api/applications/{app_id}/status")
async def set_application_status(app_id: int, request: Request,
                                 profile: Profile = Depends(current_profile)):
    if tracker.get_application(profile.tracker_db, app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    status = (await request.json()).get("status", "")
    try:
        tracker.set_status(profile.tracker_db, app_id, status)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"ok": True,
            "history": tracker.get_status_history(profile.tracker_db, app_id)}


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: int, profile: Profile = Depends(current_profile)):
    if tracker.get_application(profile.tracker_db, app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    tracker.delete_application(profile.tracker_db, app_id)
    return {"ok": True}


# --- project/experience bank (docs/features/profiles-and-bank.md) --------------

@app.get("/bank")
def bank_page(request: Request, profile: Profile = Depends(current_profile)):
    b = bank.load_bank(profile.bank_path)
    cv = cv_model.load_cv(profile.cv_path)
    return templates.TemplateResponse("bank.html", page_ctx(
        request, profile, bank=b, cv_empty=cv_model.cv_is_empty(cv),
        ollama_ok=_provider_up()))


@app.get("/api/bank")
def get_bank(profile: Profile = Depends(current_profile)):
    return bank.load_bank(profile.bank_path)


@app.post("/api/bank")
async def create_bank_entry(request: Request,
                            profile: Profile = Depends(current_profile)):
    data = await request.json()
    kind = (data.get("kind") or "").strip()
    entry = data.get("entry")
    if kind not in bank.ENTRY_KINDS or not isinstance(entry, dict):
        return JSONResponse({"error": "kind must be projects|experiences and "
                                      "entry an object"}, status_code=422)
    entry.pop("id", None)  # create: never trust a client id
    saved = bank.upsert_entry(profile.bank_path, kind, entry)
    return saved


@app.put("/api/bank/{entry_id}")
async def update_bank_entry(entry_id: str, request: Request,
                            profile: Profile = Depends(current_profile)):
    b = bank.load_bank(profile.bank_path)
    existing = bank.find_entry(b, entry_id)
    if existing is None:
        return JSONResponse({"error": "Bank entry not found"}, status_code=404)
    data = await request.json()
    entry = data.get("entry")
    if not isinstance(entry, dict):
        return JSONResponse({"error": "entry must be an object"}, status_code=422)
    entry["id"] = entry_id
    kind = "experiences" if "company" in existing else "projects"
    saved = bank.upsert_entry(profile.bank_path, kind, entry)
    return saved


@app.delete("/api/bank/{entry_id}")
def delete_bank_entry(entry_id: str, profile: Profile = Depends(current_profile)):
    b = bank.load_bank(profile.bank_path)
    if bank.find_entry(b, entry_id) is None:
        return JSONResponse({"error": "Bank entry not found"}, status_code=404)
    return bank.delete_entry(profile.bank_path, entry_id)


@app.post("/api/bank/suggest-tags")
async def bank_suggest_tags(request: Request,
                            profile: Profile = Depends(current_profile)):
    """One small LLM call proposing tags for an entry. Approve/edit only — the
    caller decides whether to save them (SPEC §3)."""
    entry = (await request.json()).get("entry")
    if not isinstance(entry, dict):
        return JSONResponse({"error": "entry must be an object"}, status_code=422)
    try:
        return {"tags": bank.suggest_tags(entry, get_provider("bank_tags"))}
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/bank/insert")
async def bank_insert(request: Request,
                      profile: Profile = Depends(current_profile)):
    """Insert a bank entry into the active profile's CV (suggest-and-approve:
    this route IS the approval). Projects append to cv.projects, experiences to
    cv.experience; bullet ids are reassigned by save_cv."""
    entry_id = ((await request.json()).get("id") or "").strip()
    b = bank.load_bank(profile.bank_path)
    entry = bank.find_entry(b, entry_id)
    if entry is None:
        return JSONResponse({"error": "Bank entry not found"}, status_code=404)
    cv = cv_model.load_cv(profile.cv_path)
    bullets = [{"text": bl["text"]} for bl in entry.get("bullets") or []]
    if "company" in entry:
        cv["experience"].append({
            "company": entry["company"], "title": entry["title"],
            "location": entry.get("location", ""),
            "start": entry.get("start", ""), "end": entry.get("end"),
            "bullets": bullets})
    else:
        cv["projects"].append({
            "name": entry["name"], "url": entry.get("url", ""), "bullets": bullets})
    cv_model.save_cv(cv, profile.cv_path)
    return {"ok": True}


# --- import --------------------------------------------------------------------

@app.post("/api/import")
async def import_cv(file: UploadFile = File(None), pasted: str = Form(""),
                    profile: Profile = Depends(current_profile)):
    if file is not None and file.filename:
        text = importer.extract_text(file.filename, await file.read())
    else:
        text = pasted
    if not text.strip():
        return JSONResponse({"error": "Nothing to import — upload a file or "
                                      "paste your resume text."}, status_code=422)
    try:
        parsed = importer.parse_resume(text, get_provider("import"))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    errors = parsed.pop("_import_errors", [])
    existing = cv_model.load_cv(profile.cv_path)
    if not cv_model.cv_is_empty(existing):
        # never clobber a real CV without a trace
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        profile.versions_dir.mkdir(parents=True, exist_ok=True)
        backup = profile.versions_dir / f"pre-import-{stamp}.yaml"
        shutil.copy(profile.cv_path, backup)
    cv_model.save_cv(parsed, profile.cv_path)
    return {"ok": True, "warnings": errors, "redirect": "/editor"}
