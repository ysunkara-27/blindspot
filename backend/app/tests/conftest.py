"""Shared fixtures. Uses the SYNTHETIC fixture cases (pipeline/tests/fixtures/synthetic); never real data,
never the Anthropic API (BLINDSPOT_OFFLINE=1, no key)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.app.cases import CaseRepository, reset_repos
from backend.app.settings import REPO_ROOT, get_settings
from shared.contracts import AttemptSubmit, ClientTiming, Mark, TelemetryEvent

FIXTURES = REPO_ROOT / "pipeline" / "tests" / "fixtures" / "synthetic"


@pytest.fixture
def repo() -> CaseRepository:
    return CaseRepository(FIXTURES)


def _ev(
    t: float, x: float | None, y: float | None, zoom: float = 1.0, vp=(0, 0, 256, 256), kind="move", loupe=True
) -> TelemetryEvent:
    return TelemetryEvent(t=t, kind=kind, x=x, y=y, zoom=zoom, vp=vp, loupe=loupe)


def hover(
    x: float, y: float, ms: float, t0: float = 0.0, step: float = 33.0, jitter: float = 2.0
) -> list[TelemetryEvent]:
    """Pointer hovering at (x, y) for `ms`, jittering ±jitter px so it counts as moving."""
    out, t, k = [], t0, 0
    while t < t0 + ms:
        dx = jitter if k % 2 else -jitter
        out.append(_ev(t, x + dx, y))
        t += step
        k += 1
    return out


def sweep(
    p0: tuple[float, float], p1: tuple[float, float], ms: float, t0: float = 0.0, step: float = 33.0
) -> list[TelemetryEvent]:
    n = max(2, int(ms / step))
    return [
        _ev(t0 + i * step, p0[0] + (p1[0] - p0[0]) * i / (n - 1), p0[1] + (p1[1] - p0[1]) * i / (n - 1))
        for i in range(n)
    ]


def chain(*segments: list[TelemetryEvent]) -> list[TelemetryEvent]:
    """Concatenate segments, re-timing each to follow the previous one."""
    out: list[TelemetryEvent] = []
    for seg in segments:
        if not seg:
            continue
        off = (out[-1].t + 33.0 - seg[0].t) if out else -seg[0].t
        out += [e.model_copy(update={"t": e.t + off}) for e in seg]
    if out:
        out.append(_ev(out[-1].t + 33.0, None, None, kind="leave"))
    return out


def make_submit(
    marks=(), patterns=(), declared_normal=False, telemetry=None, hints=0, normal_confidence=None
) -> AttemptSubmit:
    return AttemptSubmit(
        marks=[m if isinstance(m, Mark) else Mark(**m) for m in marks],
        patterns=list(patterns),
        declared_normal=declared_normal,
        normal_confidence=normal_confidence,
        telemetry=telemetry or [],
        hints_used=hints,
        client_timing=ClientTiming(shown_at="2026-10-05T21:00:00Z", submitted_at="2026-10-05T21:00:30Z"),
    )


def mark(mid: str, x: float, y: float, label: str, conf: int = 4) -> Mark:
    return Mark(mark_id=mid, x=x, y=y, label=label, confidence=conf)


@pytest.fixture
def processed_copy(tmp_path: Path) -> Path:
    """Copy of the fixture dir whose cases.jsonl can be edited (e.g. to add assess/bench splits)."""
    dst = tmp_path / "processed"
    shutil.copytree(FIXTURES, dst)
    return dst


def resplit(root: Path, mapping: dict[str, str]) -> None:
    p = root / "cases.jsonl"
    lines = []
    for line in p.read_text().splitlines():
        c = json.loads(line)
        if c["case_id"] in mapping:
            c["split"] = mapping[c["case_id"]]
        lines.append(json.dumps(c))
    p.write_text("\n".join(lines) + "\n")


@pytest.fixture
def api_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a temp DB + a given processed dir, offline. Returns a function(root) -> TestClient."""
    from fastapi.testclient import TestClient

    def _make(root: Path = FIXTURES) -> TestClient:
        monkeypatch.setenv("BLINDSPOT_PROCESSED_DIR", str(root))
        monkeypatch.setenv("BLINDSPOT_DB_PATH", str(tmp_path / "test.sqlite"))
        monkeypatch.setenv("BLINDSPOT_OFFLINE", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("BLINDSPOT_CARDS_DIR", str(tmp_path / "cards"))
        get_settings.cache_clear()
        reset_repos()
        from backend.app.main import app

        return TestClient(app)

    yield _make
    get_settings.cache_clear()
    reset_repos()


@pytest.fixture(autouse=True)
def _fresh_tutor_guard():
    """Every test starts with a live, non-persisting tutor guard and an empty spend cache."""
    from backend.app.tutor import guard, spend

    guard.set_guard(guard.TutorGuard(persist=False, credit_retry_s=900.0))
    spend.reset_cache()
    yield
    guard.set_guard(None)
    spend.reset_cache()
