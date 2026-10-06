"""GROUND-TRUTH INVARIANT (CLAUDE.md non-negotiable #2): nothing derived from the annotations reaches the client
before that attempt is submitted, and assessment responses carry no feedback until the session summary."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.cases import CaseRepository
from backend.app.tests.conftest import FIXTURES, make_submit, mark, resplit
from backend.app.tests.routes_util import iter_api_routes
from shared.contracts import GROUND_TRUTH_KEYS

REPO = CaseRepository(FIXTURES)


def all_keys(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in all_keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in all_keys(v)}
    return set()


def assert_no_ground_truth(body: Any, case_id: str | None = None) -> None:
    keys = all_keys(body)
    assert not (keys & GROUND_TRUTH_KEYS), keys & GROUND_TRUTH_KEYS
    text = json.dumps(body)
    assert "#F" not in text  # no finding ids
    if case_id:
        case = REPO.get(case_id)
        for f in case.findings:
            for leak in (f.label, f.short_id, f.primary_zone or "\0", f.relative_location or "\0"):
                assert f'"{leak}"' not in text, leak
        assert "is_normal" not in text and "difficulty" not in text


def _session(c, mode):
    return c.post("/api/sessions", json={"display_name": "Leak", "level": "MS3", "mode": mode}).json()


def _body(**kw):
    return json.loads(make_submit(**kw).model_dump_json())


def test_session_create_has_no_ground_truth(api_env):
    c = api_env()
    assert_no_ground_truth(_session(c, "practice"))


def test_next_never_leaks_ground_truth_practice(api_env):
    c = api_env()
    s = _session(c, "practice")
    for _ in range(12):
        r = c.get(f"/api/sessions/{s['session_id']}/next")
        body = r.json()
        assert set(body) == {"attempt_id", "case", "index", "total", "hints_enabled", "done"}
        assert set(body["case"]) == {"case_id", "image_url", "width", "height"}
        assert_no_ground_truth(body, body["case"]["case_id"])
        # no debrief before submit either
        assert c.get(f"/api/attempts/{body['attempt_id']}/debrief").status_code == 409
        c.post(f"/api/attempts/{body['attempt_id']}/submit", json=_body(declared_normal=True, normal_confidence=3))


@pytest.fixture
def assess_root(processed_copy):
    resplit(processed_copy, {"syn_001": "assess_A", "syn_005": "assess_A", "syn_008": "assess_A"})
    return processed_copy


def test_assessment_submit_returns_only_receipt(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c, "assess_A")
    sid = s["session_id"]
    for i in range(3):
        n = c.get(f"/api/sessions/{sid}/next").json()
        assert_no_ground_truth(n, n["case"]["case_id"])
        r = c.post(
            f"/api/attempts/{n['attempt_id']}/submit", json=_body(marks=[mark("M1", 70, 150, "nodule")], patterns=[])
        )
        assert r.json() == {"recorded": True, "index": i + 1, "total": 3}
        for path in (f"/api/attempts/{n['attempt_id']}/debrief",):
            body = c.get(path).json()
            assert body == {"status": "disabled"}
        if i < 2:
            r = c.get(f"/api/sessions/{sid}/summary")
            assert r.status_code == 409
            assert_no_ground_truth(r.json())
    assert_no_ground_truth(c.get(f"/api/sessions/{sid}/next").json())
    assert "cases" in c.get(f"/api/sessions/{sid}/summary").json()  # revealed only at the end


def test_hint_and_ask_blocked_in_assessment(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c, "assess_A")
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    r = c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []})
    assert r.status_code == 403
    assert_no_ground_truth(r.json(), n["case"]["case_id"])


def test_no_public_case_metadata_route(api_env):
    c = api_env()
    # the only public per-case route is the image; JSON metadata lives under /api/dev (QA only)
    paths = {p for p, _ in iter_api_routes(c.app)}
    case_routes = {p for p in paths if p.startswith("/api/cases/")}
    assert case_routes == {"/api/cases/{case_id}/image"}
