"""QA gate W1 fixes (docs/REVIEW_NOTES.md issues 1, 4, 7, 11), demo playlist ordering, rate-limit surfacing.

SYNTHETIC fixtures only; offline; the Anthropic SDK constructor is patched to fail (no live calls).
"""

from __future__ import annotations

import json
import math

import pytest

from backend.app import tutor_bridge
from backend.app.adaptive.selector import CaseInfo, LearnerState, eligible, qa_ok, select_next
from backend.app.services import submit_problems
from backend.app.tests.conftest import hover, make_submit, mark, resplit
from backend.app.tutor.client import LiveCallError, MockClient


@pytest.fixture(autouse=True)
def _no_live_api(monkeypatch):
    import anthropic

    def boom(*a, **k):
        raise AssertionError("test attempted to construct a live Anthropic client")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    yield
    tutor_bridge.set_client(None)


def _session(c, mode="practice", **kw):
    r = c.post("/api/sessions", json={"display_name": "Test", "level": "MS2", "mode": mode, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def _flag(root, case_id: str, flags: list[str]) -> None:
    p = root / "cases.jsonl"
    out = []
    for line in p.read_text().splitlines():
        c = json.loads(line)
        if c["case_id"] == case_id:
            c["qa_flags"] = flags
        out.append(json.dumps(c))
    p.write_text("\n".join(out) + "\n")


# ------------------------------------------------------------------ issue 1: /api/dev gated
DEV_PATHS = [
    "/api/dev/cases",
    "/api/dev/cases?split=assess_A",
    "/api/dev/cases/syn_005",
    "/api/dev/cases/syn_005/overlay",
]


def test_dev_routes_404_by_default(api_env, monkeypatch):
    monkeypatch.delenv("BLINDSPOT_DEV", raising=False)
    c = api_env()
    for p in DEV_PATHS:
        r = c.get(p)
        assert r.status_code == 404, p
        assert "syn_005" not in r.text and "nodule" not in r.text
    assert not any(k.startswith("/api/dev") for k in c.get("/api/openapi.json").json()["paths"])


def test_dev_routes_on_with_flag(api_env, monkeypatch):
    monkeypatch.setenv("BLINDSPOT_DEV", "1")
    c = api_env()
    assert c.get("/api/dev/cases").json()["n"] == 10
    assert c.get("/api/dev/cases/syn_005").json()["case_id"] == "syn_005"
    r = c.get("/api/dev/cases/syn_005/overlay", params={"layers": "zones,findings"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ issue 4: /about licences
def test_about_licenses_disclaimer_limitations(api_env):
    body = api_env().get("/api/about").json()
    assert body["disclaimer"] == "For education. Not for clinical use."
    lic = {d["name"]: d for d in body["licenses"]}
    nih = lic["NIH ChestX-ray14"]
    assert nih["url"] == "https://nihcc.app.box.com/v/ChestXray-NIHCC"
    assert nih["citation"].startswith("Wang X, Peng Y, Lu L, Lu Z, Bagheri M, Summers RM. ChestX-ray8")
    assert "CVPR 2017" in nih["citation"] and nih["acknowledgement"] == "NIH Clinical Center"
    det = lic["ChestX-Det instance annotations"]
    assert det["license"] == "Apache-2.0" and det["provider"] == "Deepwise AI Lab"
    assert (
        det["url"] == "https://github.com/Deepwise-AILab/ChestX-Det-Dataset" and "MedOtter/ChestX-Det" in det["mirror"]
    )
    assert lic["TorchXRayVision"]["license"] == "Apache-2.0"
    assert "link" in lic["Radiopaedia"]["license"].lower()
    lim = " ".join(body["limitations"]).lower()
    for needle in (
        "single us centre",
        "label noise",
        "proxy for gaze",
        "ctr",
        "projection",
        "pixel spacing",
        "centimetres",
    ):
        assert needle in lim, needle
    # existing fields kept
    assert {"ChestX-Det", "NIH ChestX-ray14", "TorchXRayVision"} <= {d["name"] for d in body["datasets"]}
    assert body["name"] == "Blindspot" and body["tutor"] and body["privacy"]


# ------------------------------------------------------------------ issue 7: submit validation
def test_submit_problems_pure():
    ok = make_submit(marks=[mark("M1", 0, 0, "nodule"), mark("M2", 256, 256, "mass")])
    assert submit_problems(ok, 256, 256, 50) == []
    assert submit_problems(make_submit(marks=[mark("M1", -1, 10, "nodule")]), 256, 256, 50)
    assert submit_problems(make_submit(marks=[mark("M1", 10, 256.5, "nodule")]), 256, 256, 50)
    assert submit_problems(make_submit(marks=[mark("M1", math.nan, 10, "nodule")]), 256, 256, 50)
    assert submit_problems(make_submit(marks=[mark("M1", math.inf, 10, "nodule")]), 256, 256, 50)
    assert submit_problems(make_submit(marks=[mark("M1", 1, 1, "nodule"), mark("M1", 2, 2, "nodule")]), 256, 256, 50)
    many = [mark(f"M{i}", 10, 10, "nodule") for i in range(51)]
    assert submit_problems(make_submit(marks=many), 256, 256, 50)
    assert submit_problems(make_submit(marks=many[:50]), 256, 256, 50) == []


def _post_raw(c, aid: str, body: dict):
    # json.dumps writes NaN/Infinity literals (allow_nan=True), which Python's JSON parser accepts server-side
    return c.post(f"/api/attempts/{aid}/submit", content=json.dumps(body), headers={"content-type": "application/json"})


@pytest.mark.parametrize(
    "marks",
    [
        [{"mark_id": "M1", "x": -50, "y": 99, "label": "nodule", "confidence": 3}],
        [{"mark_id": "M1", "x": 10, "y": 99999, "label": "nodule", "confidence": 3}],
        [{"mark_id": "M1", "x": float("nan"), "y": 10, "label": "nodule", "confidence": 3}],
        [{"mark_id": "M1", "x": 10, "y": float("inf"), "label": "nodule", "confidence": 3}],
        [{"mark_id": "M1", "x": 10 + i, "y": 10, "label": "nodule", "confidence": 3} for i in range(3)],
        [{"mark_id": f"M{i}", "x": 10, "y": 10, "label": "nodule", "confidence": 3} for i in range(51)],
    ],
    ids=["x<0", "y>H", "nan", "inf", "dup-ids", "51-marks"],
)
def test_submit_rejects_bad_marks(api_env, marks):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    body = _body()
    body["marks"] = marks
    r = _post_raw(c, n["attempt_id"], body)
    assert r.status_code == 422, r.text
    # nothing was recorded: a valid submit still goes through afterwards
    r2 = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(marks=[mark("M1", 256, 0, "nodule")]))
    assert r2.status_code == 200, r2.text


def test_submit_rejects_nonfinite_telemetry(api_env):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    body = _body(telemetry=hover(100, 100, 200))
    body["telemetry"][1]["x"] = float("nan")
    assert _post_raw(c, n["attempt_id"], body).status_code == 422


# ------------------------------------------------------------------ issue 11: qa-flag allowlist
def test_qa_ok_allowlist():
    assert qa_ok([]) and qa_ok(["synthetic", "anatomy_missing", "zones_approximate", "approximate_zones"])
    assert not qa_ok(["orientation_suspect"]) and not qa_ok(["synthetic", "merged_duplicate_instances"])
    info = CaseInfo("x", False, ("nodule",), 0.0, "practice", ("orientation_suspect",))
    assert not eligible(info, ["nodule"])


def test_selector_fallback_never_serves_flagged():
    import random

    pool = [CaseInfo("bad", False, ("nodule",), 0.0, "practice", ("orientation_suspect",))]
    cfg = {
        "prevalence_abnormal": 0.5,
        "recent_window": 5,
        "weakest_label_prob": 0.5,
        "epsilon": 0.1,
        "target_p": 0.7,
        "repeat_label_penalty": 0.1,
        "noise_sd": 0.0,
    }
    assert select_next(pool, LearnerState(), cfg, random.Random(0), core=["nodule"]) is None


def test_flagged_case_excluded_from_practice_drill_and_assessment(api_env, processed_copy):
    resplit(processed_copy, {"syn_001": "assess_A", "syn_008": "assess_A", "syn_002": "assess_A"})
    _flag(processed_copy, "syn_002", ["synthetic", "orientation_suspect"])  # assessment case
    _flag(processed_copy, "syn_003", ["synthetic", "orientation_suspect"])  # practice case
    _flag(processed_copy, "syn_009", ["synthetic", "anatomy_missing"])  # allowlisted: still served
    c = api_env(processed_copy)

    # assessment: syn_002 dropped, total 2
    s = _session(c, mode="assess_A")
    served = []
    while True:
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        if n["done"]:
            break
        assert n["total"] == 2
        served.append(n["case"]["case_id"])
        assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True)).status_code == 200
    assert sorted(served) == ["syn_001", "syn_008"]
    assert c.get(f"/api/sessions/{s['session_id']}/summary").status_code == 200

    # practice + drill (effusion: syn_003 is the effusion case that is flagged) never serve flagged cases
    seen: set[str] = set()
    for mode, extra in (("practice", {}), ("drill", {"settings": {"label": "effusion"}})):
        for _ in range(3):
            s = _session(c, mode=mode, **extra)
            for _ in range(6):
                n = c.get(f"/api/sessions/{s['session_id']}/next").json()
                if n["done"]:
                    break
                seen.add(n["case"]["case_id"])
                c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True))
    assert "syn_003" not in seen and "syn_002" not in seen and "syn_001" not in seen
    assert "syn_009" in seen or len(seen) >= 4


def test_review_mode_skips_flagged_past_miss(api_env, processed_copy, monkeypatch):
    c = api_env(processed_copy)
    s = _session(c)
    lid = s["learner_id"]
    # miss every case once (declared normal on abnormal = miss)
    for _ in range(7):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True))
    _flag(processed_copy, "syn_002", ["orientation_suspect"])
    c = api_env(processed_copy)  # reload repo with the new flag
    for _ in range(4):
        r = _session(c, mode="review", settings={"learner_id": lid})
        n = c.get(f"/api/sessions/{r['session_id']}/next").json()
        assert n["case"]["case_id"] != "syn_002"


# ------------------------------------------------------------------ demo playlist
def _run(c, sid: str, k: int) -> list[str]:
    out = []
    for _ in range(k):
        n = c.get(f"/api/sessions/{sid}/next").json()
        if n["done"]:
            break
        out.append(n["case"]["case_id"])
        assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True)).status_code == 200
    return out


def test_playlist_served_in_order_then_adaptive(api_env, processed_copy):
    _flag(processed_copy, "syn_004", ["orientation_suspect"])
    c = api_env(processed_copy)
    pl = ["syn_007", "syn_002", "syn_004", "nope_999", "syn_009", "syn_005"]
    s = _session(c, settings={"playlist": pl})
    got = _run(c, s["session_id"], 7)
    assert got[:4] == ["syn_007", "syn_002", "syn_009", "syn_005"]  # flagged + missing skipped, order kept
    assert len(got) == 7 and len(set(got)) == 7 and "syn_004" not in got  # then adaptive, no repeats


def test_playlist_ignores_non_practice_cases(api_env, processed_copy):
    resplit(processed_copy, {"syn_001": "assess_A"})
    c = api_env(processed_copy)
    s = _session(c, settings={"playlist": ["syn_001", "syn_006"]})
    assert _run(c, s["session_id"], 1) == ["syn_006"]


def test_demo_learner_sessions_inherit_playlist(api_env):
    c = api_env()
    seed = c.post(
        "/api/sessions",
        json={
            "display_name": "Demo",
            "level": "MS3",
            "participant_code": "DEMO",
            "mode": "practice",
            "settings": {"playlist": ["syn_006", "syn_010"]},
        },
    ).json()
    # the onboarding page sends display_name only (no participant code)
    s = c.post("/api/sessions", json={"display_name": "demo", "level": "MS3", "mode": "practice"}).json()
    assert s["learner_id"] == seed["learner_id"]
    assert _run(c, s["session_id"], 2) == ["syn_006", "syn_010"]
    other = _session(c)
    assert other["learner_id"] != seed["learner_id"]


def test_demo_seed_offline_on_fixtures(api_env, tmp_path, capsys):
    import yaml

    from backend.app import demo_seed

    api_env()
    pl = tmp_path / "pl.yaml"
    pl.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {"slot": 1, "case_id": "syn_002", "story": "pneumothorax — search error"},
                    {"slot": 2, "case_id": "syn_001", "story": "decision error"},
                    {"slot": 3, "case_id": "syn_003", "story": "easy win"},
                    {"slot": 4, "case_id": "syn_008", "story": "Normal film"},
                    {"slot": 5, "case_id": "syn_005", "story": "satisfaction of search"},
                    {"slot": 6, "case_id": "syn_007", "story": "Cardiomegaly"},
                ]
            }
        )
    )
    assert demo_seed.main(["--playlist", str(pl), "--reset-db"]) == 0
    out = capsys.readouterr().out
    assert "syn_002" in out and "template: offline" in out
    rows = {ln.split()[0]: ln for ln in out.splitlines() if ln[:1].isdigit()}
    assert "F1:missed_search" in rows["1"] and "F1:missed_decision" in rows["2"]
    assert "F1:found" in rows["3"] and "case:true_negative" in rows["4"] and "F1:pattern_found" in rows["6"]
    # no attempts written (dashboards stay real-only)
    from backend.app.db import row, tx

    with tx() as con:
        assert row(con, "SELECT COUNT(*) AS n FROM attempts")["n"] == 0


def test_demo_seed_rejects_flagged_playlist(api_env, processed_copy, tmp_path, capsys):
    from backend.app import demo_seed

    _flag(processed_copy, "syn_002", ["orientation_suspect"])
    api_env(processed_copy)
    pl = tmp_path / "pl.yaml"
    pl.write_text("cases:\n  - {slot: 1, case_id: syn_002, story: x}\n  - {slot: 2, case_id: nope, story: y}\n")
    assert demo_seed.main(["--playlist", str(pl)]) == 1
    out = capsys.readouterr().out
    assert "orientation_suspect" in out and "nope not found" in out


# ------------------------------------------------------------------ rate limit → source template + error
def test_fallback_error_mapping():
    assert tutor_bridge.fallback_error(
        {"source": "template", "validator": {"fallback_reason": "live_rate_limited"}}
    ) == ("rate_limited")
    assert tutor_bridge.fallback_error({"source": "template", "validator": {"fallback_reason": "offline"}}) is None
    assert tutor_bridge.fallback_error({"source": "live", "validator": {}}) is None


def test_rate_limited_debrief_surfaces_error(api_env, monkeypatch):
    c = api_env()
    monkeypatch.setenv("BLINDSPOT_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    from backend.app.settings import get_settings

    get_settings.cache_clear()
    assert not get_settings().offline
    tutor_bridge.set_client(MockClient(responses=[LiveCallError("rate_limited", "cap reached")]))
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True)).status_code == 200
    d = c.get(f"/api/attempts/{n['attempt_id']}/debrief").json()
    assert d["status"] == "ready" and d["source"] == "template" and d["error"] == "rate_limited", d
    assert d["debrief"]["headline"]
