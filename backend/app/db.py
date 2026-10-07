"""SQLite storage (SPEC §13.1). stdlib sqlite3, WAL mode, uuid4 string ids.

`python -m backend.app.db --reset` drops and recreates every table (idempotent).
Extensions to §13.1 (logged in PROGRESS.md): attempts.idx / attempts.hint_log_json / attempts.result_json (the stored
SubmitResult, served by GET /attempts/{id}/result); debriefs.status/error/provenance; a `flags` table for "This seems
wrong" reports; token columns on debriefs/asks (cache_read_tokens, asks.input/output_tokens) for the spend estimate
(backend/app/tutor/spend.py); `tutor_state` key/value rows for the tutor guard's pause (backend/app/tutor/guard.py).

First-run safety: the schema is created ONCE per database file by `init_db` (called from the app lifespan and lazily by
`connect`), under a cross-process file lock and inside one `BEGIN IMMEDIATE` transaction, so several first requests (or
several processes) hitting a fresh database never see "database is locked" or a half-created schema. Every connection
sets `busy_timeout`; write paths that read before they write use `tx(immediate=True)`.
"""

from __future__ import annotations

import argparse
import json
import os
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
  outcomes_json TEXT, search_json TEXT, elo_json TEXT, result_json TEXT, measurements_json TEXT);
CREATE INDEX IF NOT EXISTS attempts_session ON attempts(session_id);
CREATE INDEX IF NOT EXISTS attempts_learner ON attempts(learner_id);
CREATE TABLE IF NOT EXISTS telemetry (attempt_id TEXT PRIMARY KEY, events_json TEXT NOT NULL, n_events INTEGER);
CREATE TABLE IF NOT EXISTS debriefs (
  id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, cache_key TEXT, model TEXT, prompt_version TEXT, facts_json TEXT,
  output_json TEXT, validator_json TEXT, source TEXT, latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER,
  created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT, provenance TEXT,
  cache_read_tokens INTEGER);
CREATE INDEX IF NOT EXISTS debriefs_attempt ON debriefs(attempt_id);
CREATE INDEX IF NOT EXISTS debriefs_cache ON debriefs(cache_key);
CREATE INDEX IF NOT EXISTS debriefs_created ON debriefs(created_at);
CREATE TABLE IF NOT EXISTS asks (
  id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL,
  source TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER);
CREATE INDEX IF NOT EXISTS asks_created ON asks(created_at);
CREATE TABLE IF NOT EXISTS tutor_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
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
    "tutor_state",
)

# Columns added after the first release: (table, column, DDL type). Applied by init_db to databases created earlier.
MIGRATIONS = (
    ("attempts", "result_json", "TEXT"),
    ("debriefs", "cache_read_tokens", "INTEGER"),
    ("asks", "source", "TEXT"),
    ("asks", "input_tokens", "INTEGER"),
    ("asks", "output_tokens", "INTEGER"),
    ("asks", "cache_read_tokens", "INTEGER"),
    ("attempts", "measurements_json", "TEXT"),  # volumetric size measurements (CT / MR)
)
BUSY_TIMEOUT_MS = 30_000

_lock = threading.Lock()
_initialised: set[str] = set()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def db_path() -> Path:
    return get_settings().db_path


def _statements(script: str) -> list[str]:
    return [st.strip() for st in script.split(";") if st.strip()]


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock on `path` (cross-process). No-op where fcntl is unavailable; BEGIN IMMEDIATE and the
    busy timeout still serialise schema creation there."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-POSIX
        yield
        return
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _create_schema(con: sqlite3.Connection) -> None:
    """All CREATEs and column migrations in ONE write transaction (con must be in autocommit mode)."""
    con.execute("BEGIN IMMEDIATE")
    try:
        for st in _statements(SCHEMA):
            con.execute(st)
        for table, col, ddl in MIGRATIONS:
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def init_db(path: Path | None = None, *, force: bool = False) -> Path:
    """Create the schema once per database file. Safe to call from many threads and many processes at once."""
    p = Path(path or db_path())
    key = str(p.resolve())
    if not force and key in _initialised and p.exists():
        return p
    with _lock:
        if not force and key in _initialised and p.exists():
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        with _file_lock(p.with_name(p.name + ".init.lock")):
            con = sqlite3.connect(p, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
            try:
                con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
                con.execute("PRAGMA journal_mode=WAL")  # persistent in the file; set once, under the lock
                _create_schema(con)
            finally:
                con.close()
        _initialised.add(key)
    return p


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = init_db(path)
    con = sqlite3.connect(p, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx(path: Path | None = None, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """One connection, one transaction. `immediate=True` takes the write lock up front (BEGIN IMMEDIATE) so a
    read-then-write sequence (next case, submit, lazy debrief row) cannot interleave with another writer."""
    con = connect(path)
    try:
        if immediate:
            con.execute("BEGIN IMMEDIATE")
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
    with _lock, _file_lock(p.with_name(p.name + ".init.lock")):
        con = sqlite3.connect(p, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        try:
            con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            con.execute("PRAGMA journal_mode=WAL")
            for t in TABLES:
                con.execute(f"DROP TABLE IF EXISTS {t}")
            _create_schema(con)
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
        init_db(p, force=True)
        print(f"schema ensured at {p}")


if __name__ == "__main__":
    main()
