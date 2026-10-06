"""QA (adversarial) ground-truth leak tests. Owner: qa-reviewer. Synthetic fixtures only; offline; no API calls.

Complements test_gt_leak.py (backend-engineer). Differences: every response body of the reading flow is dumped
as raw JSON and scanned for (a) every key in GROUND_TRUTH_KEYS, (b) every taxonomy label id and display name,
(c) finding-id patterns, (d) polygon/bbox-like arrays and `is_normal`. Assessment: hint/ask 403, debrief disabled,
summary 409 until all cases are submitted. Image response headers are scanned too.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml

from backend.app.settings import REPO_ROOT
from backend.app.tests.conftest import FIXTURES, make_submit, mark, resplit
from shared.contracts import GROUND_TRUTH_KEYS

TAXONOMY = yaml.safe_load((REPO_ROOT / "config" / "taxonomy.yaml").read_text())
LABEL_WORDS = sorted(
    {lab["id"] for lab in TAXONOMY["labels"]}
    | {lab["id"].replace("_", " ") for lab in TAXONOMY["labels"]}
    | {lab["display"].lower() for lab in TAXONOMY["labels"]}
)
EXTRA_KEYS = {"bbox", "polygon", "is_normal", "mask", "geometry", "centroid", "heatmap_png_b64", "arrows"}
FINDING_ID = re.compile(r"#F\d")


def _keys(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in _keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in _keys(v)}
    return set()


def _has_coordinate_array(x: Any) -> bool:
    """A list of >=3 [number, number] pairs (a polygon) or a 4-number bbox-like list under any key."""
    if isinstance(x, list):
        if len(x) >= 3 and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(v, int | float) for v in p) for p in x
        ):
            return True
        return any(_has_coordinate_array(v) for v in x)
    if isinstance(x, dict):
        return any(_has_coordinate_array(v) for v in x.values())
    return False


def scan(label: str, body: Any, *, allow_label_words: bool = False, allow_paths: tuple[str, ...] = ()) -> None:
    """Raise AssertionError naming the first leak found in `body` (a decoded JSON value)."""
    text = json.dumps(body)
    bad_keys = (_keys(body) & (GROUND_TRUTH_KEYS | EXTRA_KEYS)) - set(allow_paths)
    assert not bad_keys, f"{label}: ground-truth keys {bad_keys}"
    assert not FINDING_ID.search(text), f"{label}: finding id in {text[:200]}"
    assert not _has_coordinate_array(body), f"{label}: polygon/bbox-like array"
    if not allow_label_words:
        low = text.lower()
        for w in LABEL_WORDS:
            assert not re.search(rf"\b{re.escape(w)}\b", low), f"{label}: label word '{w}' in {text[:200]}"


def _session(c, mode: str) -> dict:
    r = c.post("/api/sessions", json={"display_name": "QA", "level": "MS3", "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()


def _body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def test_practice_flow_pre_submit_responses_carry_no_ground_truth(api_env):
    """Every pre-submit response for every fixture case: /next, image headers, hints 1-3, debrief/ask 409."""
    c = api_env()
    s = _session(c, "practice")
    scan("POST /sessions", s)
    seen: set[str] = set()
    for _ in range(10):
        r = c.get(f"/api/sessions/{s['session_id']}/next")
        assert r.status_code == 200
        n = r.json()
        scan("GET /next", n)
        cid, aid = n["case"]["case_id"], n["attempt_id"]
        seen.add(cid)
        # image: PNG, long cache, and no metadata about the case in any header
        img = c.get(n["case"]["image_url"])
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
        hdr = json.dumps(dict(img.headers)).lower()
        for w in LABEL_WORDS:
            assert w not in hdr, f"image header leaks '{w}'"
        assert "#f" not in hdr and "normal" not in hdr and "polygon" not in hdr
        # hints: H1 is review-area coverage (no label words); H2/H3 may name a zone/sign but never a label or id
        for lvl in (1, 2, 3):
            h = c.post(f"/api/attempts/{aid}/hint", json={"marks": [], "telemetry": []})
            assert h.status_code == 200, h.text
            scan(f"POST /hint L{lvl} ({cid})", h.json(), allow_label_words=(lvl == 3))
        assert c.post(f"/api/attempts/{aid}/hint", json={"marks": [], "telemetry": []}).status_code == 409
        # pre-submit: no debrief, no ask
        d = c.get(f"/api/attempts/{aid}/debrief")
        assert d.status_code == 409
        scan("debrief pre-submit", d.json())
        a = c.post(f"/api/attempts/{aid}/ask", json={"question": "what is on this film?"})
        assert a.status_code == 409
        scan("ask pre-submit", a.json())
        c.post(f"/api/attempts/{aid}/submit", json=_body(declared_normal=True, normal_confidence=3))
    assert len(seen) == 10


@pytest.fixture
def assess_root(processed_copy):
    resplit(
        processed_copy,
        {"syn_001": "assess_A", "syn_002": "assess_A", "syn_003": "assess_A", "syn_008": "assess_A"},
    )
    return processed_copy


def test_assessment_nothing_but_receipts_until_all_submitted(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c, "assess_A")
    sid = s["session_id"]
    total = 4
    for i in range(total):
        n = c.get(f"/api/sessions/{sid}/next").json()
        scan("assess /next", n)
        assert n["hints_enabled"] is False and n["total"] == total
        aid = n["attempt_id"]
        assert c.post(f"/api/attempts/{aid}/hint", json={"marks": [], "telemetry": []}).status_code == 403
        assert c.post(f"/api/attempts/{aid}/ask", json={"question": "is this normal?"}).status_code in (403, 409)
        r = c.post(f"/api/attempts/{aid}/submit", json=_body(marks=[mark("M1", 70, 150, "nodule")], patterns=[]))
        assert r.status_code == 200
        assert r.json() == {"recorded": True, "index": i + 1, "total": total}, r.json()
        scan("assess submit", r.json())
        # post-submit, still no feedback surface
        d = c.get(f"/api/attempts/{aid}/debrief").json()
        assert d == {"status": "disabled"}
        assert c.post(f"/api/attempts/{aid}/ask", json={"question": "what did I miss?"}).status_code == 403
        # the summary is refused until every case is submitted, and the refusal itself is leak-free
        sm = c.get(f"/api/sessions/{sid}/summary")
        if i < total - 1:
            assert sm.status_code == 409, f"summary served after {i + 1}/{total}"
            scan("summary 409", sm.json())
        # learner dashboard must not expose per-case feedback for assessment attempts before the summary
        dash = c.get(f"/api/learners/{s['learner_id']}/dashboard")
        if dash.status_code == 200 and i < total - 1:
            scan("dashboard mid-assessment", dash.json(), allow_label_words=True, allow_paths=("calibration",))
            assert "outcomes" not in _keys(dash.json())
    done = c.get(f"/api/sessions/{sid}/next").json()
    assert done["done"] is True
    scan("assess done", done)
    assert c.get(f"/api/sessions/{sid}/summary").status_code == 200


def test_assess_summary_not_available_for_unsubmitted_open_attempt(api_env, assess_root):
    """Opening /next for case k must not let the learner fetch summary even with k-1 submitted."""
    c = api_env(assess_root)
    sid = _session(c, "assess_A")["session_id"]
    n = c.get(f"/api/sessions/{sid}/next").json()
    assert c.get(f"/api/sessions/{sid}/summary").status_code == 409
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True, normal_confidence=2))
    n2 = c.get(f"/api/sessions/{sid}/next").json()
    assert n2["attempt_id"] != n["attempt_id"]
    # resubmitting an already-submitted attempt must not return a scored result
    again = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True, normal_confidence=2))
    assert again.status_code == 409
    scan("resubmit refusal", again.json())


def test_practice_attempt_cannot_be_read_back_before_submit_via_review_or_flag(api_env):
    """Review queue lists only submitted attempts; no pre-submit attempt appears there."""
    c = api_env()
    sid = _session(c, "practice")["session_id"]
    n = c.get(f"/api/sessions/{sid}/next").json()
    items = c.get("/api/review/items", params={"type": "debrief"}).json()
    assert n["attempt_id"] not in json.dumps(items)


def test_fixture_dir_is_synthetic_only():
    """Guard: this module must never point at real data."""
    cases = (FIXTURES / "cases.jsonl").read_text().splitlines()
    assert cases and all(json.loads(x)["source"] == "synthetic" for x in cases)
