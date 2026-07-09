"""SQLite data-access layer for the job application tracker (SPEC §5.6).

M1 created the schema; M3 adds the minimal DAO the tailoring flow needs to
create/link applications. The dashboard and full CRUD arrive in M5.
"""
import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  company TEXT NOT NULL,
  role TEXT NOT NULL,
  url TEXT,
  jd_text TEXT,
  jd_extraction TEXT,          -- cached JSON from tailoring step 1
  status TEXT NOT NULL DEFAULT 'saved',
      -- saved | applied | screening | interview | offer | rejected | withdrawn
  applied_date TEXT,
  cv_version_path TEXT,
  cover_letter_path TEXT,
  notes TEXT,
  next_action TEXT,
  next_action_date TEXT,
  match_score INTEGER,
  interview_prep TEXT,         -- JSON blob from the interview prep kit
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS status_history (
  id INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES applications(id),
  status TEXT,
  changed_at TEXT
);
"""


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or config.TRACKER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    (db_path or config.TRACKER_DB).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def list_applications() -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, company, role, status, match_score, updated_at "
            "FROM applications ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_application(app_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?",
                           (app_id,)).fetchone()
    return dict(row) if row else None


def create_application(company: str, role: str, url: str = "") -> int:
    now = _now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO applications (company, role, url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (company, role, url, now, now))
        conn.execute(
            "INSERT INTO status_history (application_id, status, changed_at) "
            "VALUES (?, 'saved', ?)", (cur.lastrowid, now))
    return cur.lastrowid


_UPDATABLE = {"company", "role", "url", "jd_text", "jd_extraction", "status",
              "applied_date", "cv_version_path", "cover_letter_path", "notes",
              "next_action", "next_action_date", "match_score", "interview_prep"}


def update_application(app_id: int, **fields: Any) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"Unknown application fields: {bad}")
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE applications SET {cols} WHERE id = ?",
                     (*fields.values(), app_id))
