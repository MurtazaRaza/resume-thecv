#!/bin/zsh
# Start Resume the CV on http://localhost:8877 using the project-local venv.
cd "$(dirname "$0")"
exec .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8877 --reload
