"""SQLite data-access layer for the job application tracker (SPEC §5.6).

M1 only creates the schema so later milestones can link artifacts to
applications; the dashboard/DAO functions arrive in M5.
"""
import sqlite3
from pathlib import Path
from typing import Optional

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
