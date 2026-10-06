"""Debrief cache keys (SPEC §8.7) and small key-value stores.

Key = sha256(case_id, model, prompt_version, learner level, sorted (target, result) pairs, sorted FP zones,
sorted unvisited review areas). The backend persists debriefs in its `debriefs` table and passes `cache_get`;
MemoryStore / SqliteStore are for eval scripts and tests.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from shared.contracts import DebriefFacts, Outcome


def _pair(o: Any) -> tuple[str, str]:
    if isinstance(o, Outcome):
        t, r = o.target, o.result
    elif isinstance(o, Mapping):
        t, r = o["target"], o["result"]
    else:
        t, r = o
    t = str(t)
    return (t.split("#", 1)[1] if "#" in t else t, str(r))


def cache_key(
    case_id: str,
    model: str | None,
    prompt_version: str,
    level: str,
    outcomes: Iterable[Any],
    fp_zones: Iterable[str | None],
    unvisited: Iterable[str],
    focus_label: str | None = None,
) -> str:
    """`focus_label` (drill sessions) is appended only when set, so keys of ordinary debriefs are unchanged."""
    payload: list[Any] = [
        case_id,
        model or "",
        prompt_version,
        level,
        sorted(_pair(o) for o in outcomes),
        sorted(z or "" for z in fp_zones),
        sorted(unvisited),
    ]
    if focus_label:
        payload.append({"focus": focus_label})
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def cache_key_for_facts(
    facts: DebriefFacts, model: str | None, prompt_version: str, *, focus_label: str | None = None
) -> str:
    fp_zones = [o.zone for o in facts.outcomes if o.result == "false_positive"]
    return cache_key(
        facts.case.case_id,
        model,
        prompt_version,
        facts.learner.level,
        facts.outcomes,
        fp_zones,
        facts.search.unvisited_review_areas,
        focus_label,
    )


class MemoryStore:
    def __init__(self) -> None:
        self._d: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._d.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._d[key] = value

    def __len__(self) -> int:
        return len(self._d)


class SqliteStore:
    """Tiny persistent store: table tutor_cache(key PRIMARY KEY, value JSON)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS tutor_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT value FROM tutor_cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO tutor_cache (key, value) VALUES (?, ?)", (key, json.dumps(value)))
