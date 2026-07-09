# Resume the CV

> Local-first resume workspace to import, edit, analyze, and tailor your CV for jobs — with ATS-friendly PDF output and reviewable LLM suggestions.

Resume the CV helps you import, edit, analyze, and tailor a resume for specific jobs while keeping you in control of every final change.

The app is built for a practical workflow:

- Keep one canonical CV in structured YAML
- Get ATS friendly PDF and plain text output
- Run quality checks on wording, consistency, and resume signals
- Tailor your CV to a pasted job description with reviewable suggestions
- Track applications and keep tailored snapshots tied to each one

Nothing is auto applied without your approval.

## What This Project Is Meant To Do

This project is designed for personal, local usage and low friction iteration:

- **Edit with structure**: your CV is stored as structured YAML, then edited through a UI.
- **Render reliably**: generate an ATS friendly PDF plus a plain text export from the same source data.
- **Improve quality**: run deterministic checks and optional LLM assisted wording improvements.
- **Tailor by role**: extract requirements from a job description, compare them with your current CV, and accept or reject targeted suggestions.
- **Preserve history**: save tailored snapshots per application so you can track what version was used where.

## Current Stack

- **Backend**: FastAPI
- **Frontend**: Jinja2 templates + vanilla JS + static CSS
- **Storage**: YAML files and SQLite
- **Local LLM**: Ollama (default model: `qwen2.5:3b-instruct`)
- **Document rendering**: Typst

## Repository Layout

```text
cv-enhancer/
├── backend/
│   ├── main.py            # FastAPI routes and app wiring
│   ├── config.py          # Paths, model, provider, runtime config
│   ├── core/              # CV model, analyzer, tailoring, tracker, rendering
│   └── llm/               # provider abstraction, ollama/gemini backends, prompts
├── frontend/
│   ├── templates/         # Server-rendered HTML
│   └── static/            # CSS and JS
├── typst/
│   └── cv.typ             # Resume template used for PDF render
├── data/                  # Runtime data (created at startup if missing)
├── run.sh                 # Local dev launch script
├── requirements.txt
└── SPEC.md                # Full product and implementation spec
```

## Prerequisites

- macOS, Linux, or Windows with Python 3.10+
- [Ollama](https://ollama.com/)
- Typst binary available either:
  - at `tools/typst` (project local), or
  - on your `PATH`

## Setup

1. Clone and enter the project:

   ```bash
   git clone <your-repo-url>
   cd cv-enhancer
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Pull the default local model:

   ```bash
   ollama pull qwen2.5:3b-instruct
   ```

5. Ensure Typst is installed:

   - If you prefer project local tooling, place the executable at `tools/typst`
   - Or install globally and ensure `typst` is on `PATH`

## Run The App

You can run with the included script:

```bash
./run.sh
```

This starts Uvicorn at:

- `http://127.0.0.1:8877`

Or run directly:

```bash
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8877 --reload
```

## Environment Variables

You can override defaults from `backend/config.py`:

- `CVE_PROVIDER` (default: `ollama`) — `ollama`, `gemini`, or `anthropic` (stub)
- `CVE_OLLAMA_URL` (default: `http://localhost:11434`)
- `CVE_MODEL` (default: `qwen2.5:3b-instruct`) — Ollama model name
- `GEMINI_API_KEY` — required when `CVE_PROVIDER=gemini`
- `CVE_GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `CVE_TASK_MODEL_<task>` — optional per-task model override (see below)

Example:

```bash
export CVE_MODEL=llama3.2:3b
./run.sh
```

## LLM Providers

All LLM features go through a small provider abstraction in `backend/llm/`. Prompts live in `backend/llm/prompts.py` and are shared across providers — switching backends is a config change, not a rewrite.

### Built-in providers

| Provider | `CVE_PROVIDER` | Notes |
|----------|----------------|-------|
| Ollama (default) | `ollama` | Local, free. Requires `ollama serve` and a pulled model. |
| Gemini | `gemini` | Google Generative Language API. Requires `GEMINI_API_KEY`. |
| Anthropic | `anthropic` | Stub only — raises `NotImplementedError` until implemented. |

**Use Gemini instead of Ollama**

1. Copy `.env.example` to `.env` if you have not already.
2. Set your API key and switch the provider:

   ```bash
   CVE_PROVIDER=gemini
   GEMINI_API_KEY=your-key-here
   CVE_GEMINI_MODEL=gemini-2.5-flash
   ```

3. Restart the app. The editor health indicator checks whether the active provider is reachable.

**Per-task model overrides**

Route specific features to a different model without changing code. The env var suffix must match the task name passed to `get_provider()` in `backend/main.py`:

```bash
# Use a stronger model only for job tailoring suggestions
CVE_TASK_MODEL_tailor_suggest=gemini-2.5-pro
```

Available task names: `import`, `bullet_optimize`, `grammar`, `letters`, `jd_extract`, `tailor_suggest`, `summary`, `headline`.

### Add a new provider (e.g. OpenAI, Anthropic)

1. **Subclass `LLMProvider`** in a new file under `backend/llm/` (see `ollama.py` or `gemini.py` for reference). Implement:
   - `complete(system, user, *, json_mode=False, temperature=0.3, max_tokens=800) -> str` — return the model's text response.
   - `is_up() -> bool` (optional but recommended) — lightweight health check used by the UI.

   `complete_json()` is inherited from the base class; it calls `complete()` with `json_mode=True` and parses JSON, retrying once on failure.

2. **Add config** in `backend/config.py` for any API keys, base URLs, or default model names your provider needs.

3. **Wire it in `get_provider()`** in `backend/llm/provider.py`:

   ```python
   if config.LLM_PROVIDER == "your_provider":
       from backend.llm.your_module import YourProvider
       return YourProvider(model=model)
   ```

4. **Document env vars** in `.env.example` (e.g. `CVE_PROVIDER=your_provider`, API key, model name).

5. **Handle errors with `LLMError`** — raise `LLMError("friendly message")` for unreachable services or bad responses so routes surface a clear error instead of crashing.

No changes are needed in feature code (`tailor.py`, `optimizer.py`, etc.) as long as your provider implements the `LLMProvider` interface. Prompts stay in `prompts.py`.

## Core Workflow

1. **Import** your existing resume text, PDF, or DOCX
2. **Review and edit** structured sections in the editor
3. **Analyze** content quality and consistency
4. **Optimize** selected bullets if you want suggested rewrites
5. **Tailor** to a specific job description and approve only what is truthful and useful
6. **Render** to PDF and plain text output

## Main Routes

- `/` redirects to import or editor based on whether a CV exists
- `/import` resume import page
- `/editor` main editing page
- `/tailor` job tailoring page
- `/api/cv` load and save CV JSON
- `/api/cv/render` render PDF and text output

## Data And Output

The app stores data under `data/`:

- `data/cv.yaml` canonical CV
- `data/versions/` tailored snapshots
- `data/out/` rendered files such as `cv.pdf` and `cv.txt`
- `data/tracker.db` job application tracking database

## Notes For Development

- The frontend is server rendered, so no node build pipeline is required.
- The project is intentionally local first and cost aware.
- Prompt templates for LLM features are centralized in `backend/llm/prompts.py`.

## License

GNU General Public License v3.0 (GPL-3.0).
