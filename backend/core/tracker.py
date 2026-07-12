"""SQLite data-access layer for the job application tracker (SPEC §5.6).

M1 created the schema; M3 added the minimal DAO the tailoring flow needs to
create/link applications. M5 completes it: full CRUD, status transitions with
history, and the dashboard grouping/overdue helpers the /tracker pages use.
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


# status values, in workflow order — drives the dashboard grouping (§5.6).
STATUSES = ["saved", "applied", "screening", "interview", "offer",
            "rejected", "withdrawn"]


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def list_applications(db_path: Path) -> List[Dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, company, role, url, status, match_score, applied_date, "
            "next_action, next_action_date, cv_version_path, cover_letter_path, "
            "updated_at FROM applications ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_application(db_path: Path, app_id: int) -> Optional[Dict[str, Any]]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?",
                           (app_id,)).fetchone()
    return dict(row) if row else None


def create_application(db_path: Path, company: str, role: str, url: str = "") -> int:
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO applications (company, role, url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)", (company, role, url, now, now))
        conn.execute(
            "INSERT INTO status_history (application_id, status, changed_at) "
            "VALUES (?, 'saved', ?)", (cur.lastrowid, now))
    return cur.lastrowid


# `status` is deliberately excluded: transitions go through set_status() so
# status_history stays authoritative. applied_date is auto-set on first "applied".
_UPDATABLE = {"company", "role", "url", "jd_text", "jd_extraction",
              "applied_date", "cv_version_path", "cover_letter_path", "notes",
              "next_action", "next_action_date", "match_score", "interview_prep"}


def update_application(db_path: Path, app_id: int, **fields: Any) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"Unknown application fields: {bad}")
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE applications SET {cols} WHERE id = ?",
                     (*fields.values(), app_id))


def set_status(db_path: Path, app_id: int, status: str) -> None:
    """Transition an application's status and log it to status_history.
    No-op if the status is unchanged (avoids duplicate history rows). Stamps
    applied_date on the first move into 'applied' if not already set."""
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    now = _now()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, applied_date FROM applications WHERE id = ?",
            (app_id,)).fetchone()
        if row is None:
            raise ValueError(f"No application {app_id}")
        if row["status"] == status:
            return
        if status == "applied" and not row["applied_date"]:
            conn.execute(
                "UPDATE applications SET status = ?, applied_date = ?, "
                "updated_at = ? WHERE id = ?",
                (status, now[:10], now, app_id))
        else:
            conn.execute(
                "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, app_id))
        conn.execute(
            "INSERT INTO status_history (application_id, status, changed_at) "
            "VALUES (?, ?, ?)", (app_id, status, now))


def get_status_history(db_path: Path, app_id: int) -> List[Dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, changed_at FROM status_history "
            "WHERE application_id = ? ORDER BY changed_at, id", (app_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_application(db_path: Path, app_id: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM status_history WHERE application_id = ?",
                     (app_id,))
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))


def dashboard(db_path: Path) -> Dict[str, Any]:
    """Applications grouped by status (in workflow order) with per-group counts
    and today's date, so the template can flag overdue next_action_date rows."""
    apps = list_applications(db_path)
    today = datetime.date.today().isoformat()
    for a in apps:
        a["overdue"] = bool(a["next_action_date"]
                            and a["next_action_date"] < today
                            and a["status"] not in ("offer", "rejected", "withdrawn"))
    groups = [{"status": s, "apps": [a for a in apps if a["status"] == s]}
              for s in STATUSES]
    return {"groups": [g for g in groups if g["apps"]],
            "counts": {s: sum(a["status"] == s for a in apps) for s in STATUSES},
            "total": len(apps), "today": today}
