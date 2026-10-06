"""SQLite schema (SPEC §13.1): reset is idempotent; WAL mode; all tables present."""

from __future__ import annotations

import subprocess
import sys

from backend.app import db
from backend.app.settings import REPO_ROOT


def _tables(path):
    con = db.connect(path)
    try:
        return {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_reset_idempotent(tmp_path):
    p = tmp_path / "x.sqlite"
    db.reset(p)
    db.reset(p)
    assert set(db.TABLES) <= _tables(p)
    with db.tx(p) as con:
        con.execute("INSERT INTO learners(id, display_name, created_at) VALUES ('a','b','c')")
    db.reset(p)
    with db.tx(p) as con:
        assert db.rows(con, "SELECT * FROM learners") == []
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_cli_reset(tmp_path):
    p = tmp_path / "cli.sqlite"
    for _ in range(2):
        r = subprocess.run(
            [sys.executable, "-m", "backend.app.db", "--reset", "--path", str(p)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
    assert {"attempts", "debriefs", "ability", "case_difficulty", "sus", "reviews"} <= _tables(p)
