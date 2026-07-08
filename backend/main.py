"""FastAPI app — all routes. Pages are server-rendered Jinja2 (frontend/
templates); JSON endpoints exist only where the editor needs structured data.
Run: .venv/bin/uvicorn backend.main:app --port 8877 --reload
"""
import datetime
import shutil

import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend import config
from backend.core import cv_model, importer, render, tracker
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
    return RedirectResponse("/import" if cv_model.cv_is_empty(cv) else "/editor")


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
