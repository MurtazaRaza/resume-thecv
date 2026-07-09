"""FastAPI app — all routes. Pages are server-rendered Jinja2 (frontend/
templates); JSON endpoints exist only where the editor needs structured data.
Run: .venv/bin/uvicorn backend.main:app --port 8877 --reload
"""
import datetime
import json
import shutil

import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend import config
from backend.core import (analyzer, cover_letter, cv_model, importer, optimizer,
                          render, summary, tailor, tracker)
from backend.llm.provider import LLMError, get_provider

app = FastAPI(title="Resume the CV")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


@app.on_event("startup")
def startup() -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    tracker.init_db()
    if not config.TYPST_BIN:
        print("WARNING: typst binary not found (tools/typst or PATH) — "
              "PDF preview/export disabled until installed.")


def page_ctx(request: Request, **extra):
    return {"request": request, "typst_ok": bool(config.TYPST_BIN),
            "model": config.MODEL, **extra}


# --- pages -------------------------------------------------------------------

@app.get("/")
def home():
    cv = cv_model.load_cv()
    if cv_model.cv_is_empty(cv):
        return RedirectResponse("/import")
    # /tracker is the app's home once a CV exists (SPEC §5.6)
    return RedirectResponse("/tracker")


@app.get("/editor")
def editor(request: Request):
    cv = cv_model.load_cv()
    return templates.TemplateResponse("editor.html", page_ctx(
        request, cv=cv, cv_yaml=cv_model.dump_yaml(cv)))


@app.get("/import")
def import_page(request: Request):
    cv = cv_model.load_cv()
    return templates.TemplateResponse("import.html", page_ctx(
        request, cv_empty=cv_model.cv_is_empty(cv),
        ollama_ok=get_provider().is_up() if config.LLM_PROVIDER == "ollama" else True))


# --- CV load/save --------------------------------------------------------------

@app.get("/api/cv")
def get_cv():
    return cv_model.load_cv()


@app.put("/api/cv")
async def put_cv(request: Request):
    cv = cv_model.save_cv(await request.json())
    return cv


@app.get("/api/cv/yaml")
def get_cv_yaml():
    return PlainTextResponse(cv_model.dump_yaml(cv_model.load_cv()))


@app.post("/api/cv/yaml/preview")
async def cv_yaml_preview(request: Request):
    """Convert editor form state to YAML without saving (YAML tab sync)."""
    return PlainTextResponse(cv_model.dump_yaml(cv_model.normalize(await request.json())))


@app.put("/api/cv/yaml")
async def put_cv_yaml(request: Request):
    text = (await request.body()).decode("utf-8")
    try:
        cv = cv_model.save_cv(cv_model.parse_yaml_str(text))
    except yaml.YAMLError as e:
        return JSONResponse({"error": f"Invalid YAML: {e}"}, status_code=422)
    return cv


# --- rendering -----------------------------------------------------------------

@app.post("/api/cv/render")
def render_cv():
    cv = cv_model.load_cv()
    try:
        render.render_txt(cv)
        pdf = render.render_pdf(cv)
    except render.RenderError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    stamp = int(pdf.stat().st_mtime)
    return {"pdf_url": f"/out/cv.pdf?v={stamp}", "txt_url": f"/out/cv.txt?v={stamp}"}


@app.get("/out/{filename}")
def out_file(filename: str):
    path = (config.OUT_DIR / filename).resolve()
    if config.OUT_DIR.resolve() not in path.parents or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


# Serve tracker-linked artifacts (tailored CV snapshots, cover letter PDFs/md).
# Restricted to these two dirs and path-traversal guarded like /out.
_ARTIFACT_DIRS = {"versions": config.VERSIONS_DIR, "letters": config.LETTERS_DIR}


@app.get("/data/{kind}/{filename}")
def artifact_file(kind: str, filename: str):
    base = _ARTIFACT_DIRS.get(kind)
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
    return {"findings": analyzer.analyze(cv)}


@app.post("/api/analyze/grammar")
async def grammar_pass(request: Request):
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or {})
    text = analyzer.section_text(cv, data.get("section", "summary"))
    if not text.strip():
        return {"issues": [], "empty": True}
    try:
        return {"issues": optimizer.grammar_check(text, get_provider())}
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/bullets/optimize")
async def optimize_bullet(request: Request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Empty bullet"}, status_code=422)
    try:
        return optimizer.optimize(text, get_provider())
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# --- summary + headline generator (M4, §5.3) ------------------------------------

@app.post("/api/summary/generate")
async def summary_generate(request: Request):
    """3 summary variants from a deterministic digest of the posted CV state.
    Body may carry the live editor CV so unsaved edits feed the digest."""
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or cv_model.load_cv())
    try:
        return summary.generate_summaries(
            cv, get_provider(), target_title=str(data.get("target_title") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/api/headline/generate")
async def headline_generate(request: Request):
    """3 plain-text headline options for basics.title (same digest, tiny call)."""
    data = await request.json()
    cv = cv_model.normalize(data.get("cv") or cv_model.load_cv())
    try:
        return summary.generate_headlines(
            cv, get_provider(), target_title=str(data.get("target_title") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# --- job tailoring (M3) ----------------------------------------------------------

@app.get("/tailor")
def tailor_page(request: Request):
    cv = cv_model.load_cv()
    return templates.TemplateResponse("tailor.html", page_ctx(
        request, cv_empty=cv_model.cv_is_empty(cv),
        applications=tracker.list_applications(),
        skill_groups=[g["group"] for g in cv["skills"] if g["group"]],
        current_title=cv["basics"]["title"],
        ollama_ok=get_provider().is_up() if config.LLM_PROVIDER == "ollama" else True))


def _tailoring_context(app_id):
    """Load the application + its cached JD extraction, or a 4xx response."""
    entry = tracker.get_application(int(app_id)) if app_id else None
    if entry is None:
        return None, None, JSONResponse({"error": "Application not found"},
                                        status_code=404)
    if not entry["jd_extraction"]:
        return None, None, JSONResponse(
            {"error": "Run “Extract & match” first"}, status_code=422)
    return entry, json.loads(entry["jd_extraction"]), None


@app.get("/api/tailor/application/{app_id}")
def tailor_load_application(app_id: int):
    """Reload a saved application's cached JD + extraction so picking it from
    the dropdown restores its match report without re-running the model."""
    entry, extraction, err = _tailoring_context(app_id)
    if err:
        return err
    cv = cv_model.load_cv()
    return {"application_id": entry["id"], "company": entry["company"],
            "jd_text": entry["jd_text"] or "",
            "extraction": extraction, "match": tailor.match(cv, extraction),
            "current_title": cv["basics"]["title"],
            "skill_groups": [g["group"] for g in cv["skills"] if g["group"]]}


@app.post("/api/tailor/preview")
async def tailor_preview(request: Request):
    """Server-side render of the tailored CV for the live diff preview. Returns
    both the master and tailored YAML so the client can show a unified diff of
    exactly what a save would change. Reuses apply_tailoring + dump_yaml so the
    tailored side is byte-identical to a saved snapshot. No LLM, no typst."""
    data = await request.json()
    entry, extraction, err = _tailoring_context(data.get("application_id"))
    if err:
        return err
    master = cv_model.load_cv()
    tailored = tailor.apply_tailoring(
        master, extraction,
        accepted=data.get("accepted") or [],
        add_skills=data.get("add_skills") or [],
        skills_group=str(data.get("skills_group") or ""),
        new_title=str(data.get("new_title") or ""))
    return {"master_yaml": cv_model.dump_yaml(master),
            "tailored_yaml": cv_model.dump_yaml(tailored)}


@app.post("/api/tailor/extract")
async def tailor_extract(request: Request):
    data = await request.json()
    jd_text = (data.get("jd_text") or "").strip()
    if not jd_text:
        return JSONResponse({"error": "Paste the job description first"},
                            status_code=422)
    app_id = data.get("application_id")
    if app_id:
        entry = tracker.get_application(int(app_id))
        if entry is None:
            return JSONResponse({"error": "Application not found"}, status_code=404)
        company = entry["company"]
    else:
        company = (data.get("company") or "").strip()
        role = (data.get("role") or "").strip()
        if not company or not role:
            return JSONResponse({"error": "Company and role are required for a "
                                          "new application"}, status_code=422)
        app_id = tracker.create_application(company, role,
                                            (data.get("url") or "").strip())
    try:
        extraction = tailor.extract(jd_text, get_provider())
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    tracker.update_application(app_id, jd_text=jd_text,
                               jd_extraction=json.dumps(extraction))
    cv = cv_model.load_cv()
    return {"application_id": app_id, "company": company,
            "extraction": extraction, "match": tailor.match(cv, extraction),
            "current_title": cv["basics"]["title"],
            "skill_groups": [g["group"] for g in cv["skills"] if g["group"]]}


@app.post("/api/tailor/suggest")
async def tailor_suggest(request: Request):
    data = await request.json()
    entry, extraction, err = _tailoring_context(data.get("application_id"))
    if err:
        return err
    return tailor.suggest(cv_model.load_cv(), extraction,
                          entry["jd_text"] or "", get_provider(),
                          guidance=str(data.get("guidance") or ""))


@app.post("/api/tailor/apply")
async def tailor_apply(request: Request):
    data = await request.json()
    entry, extraction, err = _tailoring_context(data.get("application_id"))
    if err:
        return err
    cv = cv_model.load_cv()
    before = tailor.match(cv, extraction)["coverage"]
    tailored = tailor.apply_tailoring(
        cv, extraction,
        accepted=data.get("accepted") or [],
        add_skills=data.get("add_skills") or [],
        skills_group=str(data.get("skills_group") or ""),
        new_title=str(data.get("new_title") or ""))
    after = tailor.match(tailored, extraction)["coverage"]
    path = tailor.save_snapshot(tailored, entry["company"])
    rel = str(path.relative_to(config.PROJECT_ROOT))
    tracker.update_application(entry["id"], cv_version_path=rel, match_score=after)
    return {"snapshot": rel, "coverage_before": before, "coverage_after": after}


# --- cover letters (M4, §5.5) ---------------------------------------------------

@app.get("/letters/new")
def letters_new_page(request: Request):
    cv = cv_model.load_cv()
    # only applications with a cached JD extraction can seed a letter's requirements
    apps = [a for a in tracker.list_applications()
            if (tracker.get_application(a["id"]) or {}).get("jd_extraction")]
    return templates.TemplateResponse("letters.html", page_ctx(
        request, cv_empty=cv_model.cv_is_empty(cv), applications=apps,
        ollama_ok=get_provider().is_up() if config.LLM_PROVIDER == "ollama" else True))


@app.post("/api/letters/generate")
async def letters_generate(request: Request):
    data = await request.json()
    entry, extraction, err = _tailoring_context(data.get("application_id"))
    if err:
        return err
    cv = cv_model.load_cv()
    try:
        result = cover_letter.generate(
            cv, extraction, entry["company"], entry["role"], get_provider(),
            tone=str(data.get("tone") or "professional"),
            emphasize=str(data.get("emphasize") or ""))
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    result["company"] = entry["company"]
    return result


@app.post("/api/letters/export")
async def letters_export(request: Request):
    """Save the (edited) letter as .md + .pdf in data/letters/, linked to the
    application. Body: {application_id, body}."""
    data = await request.json()
    entry, _extraction, err = _tailoring_context(data.get("application_id"))
    if err:
        return err
    body = (data.get("body") or "").strip()
    if not body:
        return JSONResponse({"error": "Nothing to export — the letter is empty."},
                            status_code=422)
    cv = cv_model.load_cv()
    md_path = cover_letter.save_letter(body, entry["company"])
    try:
        pdf_tmp = render.render_letter_pdf(cv, body, entry["company"])
    except render.RenderError as e:
        # still keep the .md; the PDF is optional if typst is missing
        rel_md = str(md_path.relative_to(config.PROJECT_ROOT))
        tracker.update_application(entry["id"], cover_letter_path=rel_md)
        return JSONResponse({"error": str(e), "markdown": rel_md}, status_code=500)
    pdf_path = md_path.with_suffix(".pdf")
    shutil.copy(pdf_tmp, pdf_path)
    rel_pdf = str(pdf_path.relative_to(config.PROJECT_ROOT))
    tracker.update_application(entry["id"], cover_letter_path=rel_pdf)
    stamp = int(pdf_path.stat().st_mtime)
    return {"markdown": str(md_path.relative_to(config.PROJECT_ROOT)),
            "pdf": rel_pdf, "pdf_url": f"/out/letter.pdf?v={stamp}"}


# --- tracker (M5, §5.6) ---------------------------------------------------------

@app.get("/tracker")
def tracker_page(request: Request):
    return templates.TemplateResponse("tracker.html", page_ctx(
        request, dashboard=tracker.dashboard(), statuses=tracker.STATUSES))


@app.get("/tracker/{app_id}")
def tracker_detail_page(request: Request, app_id: int):
    entry = tracker.get_application(app_id)
    if entry is None:
        return RedirectResponse("/tracker")
    extraction = None
    if entry["jd_extraction"]:
        try:
            extraction = json.loads(entry["jd_extraction"])
        except (ValueError, TypeError):
            extraction = None
    return templates.TemplateResponse("tracker_detail.html", page_ctx(
        request, app=entry, extraction=extraction, statuses=tracker.STATUSES,
        cv_version_url=_artifact_url(entry["cv_version_path"]),
        cover_letter_url=_artifact_url(entry["cover_letter_path"]),
        history=tracker.get_status_history(app_id)))


def _artifact_url(rel_path):
    """Map a stored 'data/versions/...' or 'data/letters/...' path to its
    servable /data/<kind>/<file> URL, or None if it isn't one of those."""
    if not rel_path:
        return None
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "data" and parts[1] in _ARTIFACT_DIRS:
        return f"/data/{parts[1]}/{parts[-1]}"
    return None


@app.post("/api/applications")
async def create_application(request: Request):
    data = await request.json()
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    if not company or not role:
        return JSONResponse({"error": "Company and role are required"},
                            status_code=422)
    app_id = tracker.create_application(company, role, (data.get("url") or "").strip())
    return {"id": app_id}


@app.put("/api/applications/{app_id}")
async def update_application(app_id: int, request: Request):
    if tracker.get_application(app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    data = await request.json()
    fields = {k: v for k, v in data.items() if k in tracker._UPDATABLE}
    unknown = set(data) - tracker._UPDATABLE
    if unknown:
        return JSONResponse(
            {"error": f"Cannot update fields: {', '.join(sorted(unknown))}"},
            status_code=422)
    try:
        tracker.update_application(app_id, **fields)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"ok": True}


@app.put("/api/applications/{app_id}/status")
async def set_application_status(app_id: int, request: Request):
    if tracker.get_application(app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    status = (await request.json()).get("status", "")
    try:
        tracker.set_status(app_id, status)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"ok": True, "history": tracker.get_status_history(app_id)}


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: int):
    if tracker.get_application(app_id) is None:
        return JSONResponse({"error": "Application not found"}, status_code=404)
    tracker.delete_application(app_id)
    return {"ok": True}


# --- import --------------------------------------------------------------------

@app.post("/api/import")
async def import_cv(file: UploadFile = File(None), pasted: str = Form("")):
    if file is not None and file.filename:
        text = importer.extract_text(file.filename, await file.read())
    else:
        text = pasted
    if not text.strip():
        return JSONResponse({"error": "Nothing to import — upload a file or "
                                      "paste your resume text."}, status_code=422)
    try:
        parsed = importer.parse_resume(text, get_provider())
    except LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    errors = parsed.pop("_import_errors", [])
    existing = cv_model.load_cv()
    if not cv_model.cv_is_empty(existing):
        # never clobber a real CV without a trace
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config.VERSIONS_DIR / f"pre-import-{stamp}.yaml"
        config.VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(config.CV_PATH, backup)
    cv_model.save_cv(parsed)
    return {"ok": True, "warnings": errors, "redirect": "/editor"}
