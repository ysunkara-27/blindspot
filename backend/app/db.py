"""SQLite storage (SPEC §13.1). stdlib sqlite3, WAL mode, uuid4 string ids.

`python -m backend.app.db --reset` drops and recreates every table (idempotent).
Extensions to §13.1 (logged in PROGRESS.md): attempts.idx / attempts.hint_log_json; debriefs.status/error/provenance;
a `flags` table for "This seems wrong" reports.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.settings import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
  id TEXT PRIMARY KEY, display_name TEXT NOT NULL, level TEXT, participant_code TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, learner_id TEXT NOT NULL REFERENCES learners(id), mode TEXT NOT NULL,
  settings_json TEXT NOT NULL DEFAULT '{}', started_at TEXT NOT NULL, ended_at TEXT);
CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id), learner_id TEXT NOT NULL,
  case_id TEXT NOT NULL, mode TEXT NOT NULL, idx INTEGER NOT NULL DEFAULT 0, shown_at TEXT NOT NULL,
  submitted_at TEXT, declared_normal INTEGER, normal_confidence INTEGER, marks_json TEXT, patterns_json TEXT,
  hints_used INTEGER NOT NULL DEFAULT 0, hint_log_json TEXT NOT NULL DEFAULT '[]', score REAL, success INTEGER,
  outcomes_json TEXT, search_json TEXT, elo_json TEXT);
CREATE INDEX IF NOT EXISTS attempts_session ON attempts(session_id);
CREATE INDEX IF NOT EXISTS attempts_learner ON attempts(learner_id);
CREATE TABLE IF NOT EXISTS telemetry (attempt_id TEXT PRIMARY KEY, events_json TEXT NOT NULL, n_events INTEGER);
CREATE TABLE IF NOT EXISTS debriefs (
  id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, cache_key TEXT, model TEXT, prompt_version TEXT, facts_json TEXT,
  output_json TEXT, validator_json TEXT, source TEXT, latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER,
  created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT, provenance TEXT);
CREATE INDEX IF NOT EXISTS debriefs_attempt ON debriefs(attempt_id);
CREATE INDEX IF NOT EXISTS debriefs_cache ON debriefs(cache_key);
CREATE TABLE IF NOT EXISTS asks (
  id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ability (
  learner_id TEXT NOT NULL, label TEXT NOT NULL, theta REAL NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (learner_id, label));
CREATE TABLE IF NOT EXISTS case_difficulty (case_id TEXT PRIMARY KEY, b REAL NOT NULL, n INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, reviewer TEXT, role TEXT, item_type TEXT, item_id TEXT, accuracy INTEGER, teaching INTEGER,
  safety_flag INTEGER, comment TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sus (
  learner_id TEXT NOT NULL, answers_json TEXT NOT NULL, score REAL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flags (
  id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL);
"""
TABLES = (
    "learners",
    "sessions",
    "attempts",
    "telemetry",
    "debriefs",
    "asks",
    "ability",
    "case_difficulty",
    "reviews",
    "sus",
    "flags",
)

_lock = threading.Lock()
_initialised: set[str] = set()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def db_path() -> Path:
    return get_settings().db_path


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    key = str(p.resolve())
    if key not in _initialised:
        with _lock:
            con.executescript(SCHEMA)
            _initialised.add(key)
    return con


@contextmanager
def tx(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    con = connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def reset(path: Path | None = None) -> None:
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        for t in TABLES:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()
    _initialised.add(str(p.resolve()))


def row(con: sqlite3.Connection, sql: str, *args: Any) -> dict[str, Any] | None:
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(con: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def jload(s: str | None, default: Any = None) -> Any:
    return json.loads(s) if s else default


def main() -> None:
    ap = argparse.ArgumentParser(description="Blindspot SQLite schema")
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables")
    ap.add_argument("--path", type=Path, default=None)
    a = ap.parse_args()
    p = a.path or db_path()
    if a.reset:
        reset(p)
        print(f"reset {p}")
    else:
        connect(p).close()
        print(f"schema ensured at {p}")


if __name__ == "__main__":
    main()
