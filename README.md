# Resume the CV

Resume the CV is a local first resume workspace. It helps you import, edit, analyze, and tailor a resume for specific jobs while keeping you in control of every final change.

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
│   └── llm/               # provider abstraction + prompts
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

- `CVE_PROVIDER` (default: `ollama`)
- `CVE_OLLAMA_URL` (default: `http://localhost:11434`)
- `CVE_MODEL` (default: `qwen2.5:3b-instruct`)

Example:

```bash
export CVE_MODEL=llama3.2:3b
./run.sh
```

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
