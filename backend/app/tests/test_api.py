"""API flows on the SYNTHETIC fixtures, offline, temp DB. The tutor is mocked (no Anthropic calls)."""

from __future__ import annotations

import json

import pytest

from backend.app import tutor_bridge
from backend.app.tests.conftest import chain, hover, make_submit, mark, resplit
from shared.contracts import DebriefFacts, DebriefOutput, DebriefResponse, SubmitResult


def _session(client, mode="practice", **kw):
    r = client.post("/api/sessions", json={"display_name": "Test", "level": "MS2", "mode": mode, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _submit_body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def test_health_counts_fixture_cases(api_env):
    c = api_env()
    body = c.get("/api/health").json()
    assert body == {"ok": True, "offline": True, "cases": 10, "version": body["version"]}


def test_practice_flow_submit_reveal_and_next(api_env):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    assert n["index"] == 1 and n["hints_enabled"] and not n["done"]
    # idempotent while unsubmitted
    assert c.get(f"/api/sessions/{s['session_id']}/next").json()["attempt_id"] == n["attempt_id"]
    img = c.get(n["case"]["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert "max-age=31536000" in img.headers["cache-control"]
    r = c.post(
        f"/api/attempts/{n['attempt_id']}/submit",
        json=_submit_body(marks=[mark("M1", 70, 150, "nodule")], telemetry=chain(hover(70, 150, 800))),
    )
    assert r.status_code == 200, r.text
    res = SubmitResult.model_validate(r.json())
    assert res.debrief_status == "pending" and res.facts_card.headline
    assert res.reveal.search.heatmap_png_b64
    # resubmit refused
    assert c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body()).status_code == 409
    n2 = c.get(f"/api/sessions/{s['session_id']}/next").json()
    assert n2["index"] == 2 and n2["case"]["case_id"] != n["case"]["case_id"]


def test_practice_session_cycles_all_cases(api_env):
    c = api_env()
    s = _session(c)
    seen = []
    for _ in range(10):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        seen.append(n["case"]["case_id"])
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=3))
    assert len(set(seen)) == 10  # no repeats while unseen cases remain
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    assert not n["done"]  # practice keeps going once the pool is exhausted


def test_elo_updated_on_practice(api_env):
    from backend.app.db import rows, tx

    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=3))
    with tx() as con:
        assert rows(con, "SELECT * FROM ability WHERE learner_id=?", s["learner_id"])
        assert rows(con, "SELECT * FROM case_difficulty WHERE case_id=?", n["case"]["case_id"])


def test_hints_ladder_and_limits(api_env):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    body = {"marks": [], "telemetry": [e.model_dump() for e in chain(hover(70, 150, 500))]}
    levels = []
    for k in range(3):
        r = c.post(f"/api/attempts/{n['attempt_id']}/hint", json=body)
        assert r.status_code == 200, r.text
        levels.append(r.json()["level"])
        assert r.json()["remaining"] == 2 - k and r.json()["text"]
    assert levels == [1, 2, 3]
    assert c.post(f"/api/attempts/{n['attempt_id']}/hint", json=body).status_code == 409
    r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=2))
    assert r.json()["score"] <= 100 - 15  # server-side hint count applies even if the client says 0


def test_first_hint_lists_unvisited_review_areas(api_env):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    r = c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []}).json()
    assert r["text"].startswith("You haven't looked at:") and "right apex" in r["text"]


# ---------------------------------------------------------------- tutor wiring (mocked)
class FakeTutor:
    """Stands in for backend.app.tutor (no network)."""

    def __init__(self):
        self.calls = []

    def build_facts(self, **kw):
        self.calls.append(("facts", kw))
        case = kw["case"]
        return DebriefFacts.model_validate(
            {
                "schema": "debrief_facts.v1",
                "case": {
                    "case_id": case.case_id,
                    "is_normal": case.is_normal,
                    "projection": "frontal; PA vs AP not recorded",
                    "findings": [
                        {"id": f.short_id, "label": f.label, "display": f.label, "kind": f.kind} for f in case.findings
                    ],
                },
                "learner": {
                    "level": kw["level"],
                    "declared_normal": kw["submit"].declared_normal,
                    "hints_used": 0,
                    "time_to_submit_s": 30,
                    "marks": [],
                    "pattern_selections": [],
                },
                "outcomes": [o.model_dump() for o in kw["outcomes"]],
                "spatial_relations": [r.model_dump(by_alias=True) for r in kw["spatial_relations"]],
                "search": kw["search"].model_dump(),
                "history": kw["history"],
                "teaching_cards": [],
            }
        )

    def generate_debrief(self, facts, case, **kw):
        self.calls.append(("debrief", kw))
        assert kw["offline"] is True and "cache_get" in kw
        out = DebriefOutput(
            headline="Good look",
            verdict="all_found",
            findings=[],
            overcalls=[],
            search_coaching="x",
            calibration_note="",
            next_step="y",
            fact_ids=[],
        )
        return {
            "debrief": out,
            "source": "template",
            "provenance": "ai_draft",
            "validator": {"ok": True},
            "latency_ms": 3.0,
            "model": None,
            "prompt_version": "v1",
            "cache_key": "k1",
            "input_tokens": None,
            "output_tokens": None,
        }

    def hint(self, level, case, marks, telemetry, zones, *, previous=None):
        return f"tutor hint {level}"

    def ask(self, question, facts, case, *, previous, offline):
        return {"answer": f"answer {len(previous) + 1}", "source": "template"}


@pytest.fixture
def fake_tutor(monkeypatch):
    t = FakeTutor()
    monkeypatch.setattr(tutor_bridge, "build_facts", t.build_facts)
    monkeypatch.setattr(tutor_bridge, "generate_debrief", t.generate_debrief)
    monkeypatch.setattr(tutor_bridge, "hint", t.hint)
    monkeypatch.setattr(tutor_bridge, "ask", t.ask)
    return t


def test_debrief_job_and_ask_with_mocked_tutor(api_env, fake_tutor):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    aid = n["attempt_id"]
    assert c.post(f"/api/attempts/{aid}/ask", json={"question": "why?"}).status_code == 409  # before submit
    c.post(f"/api/attempts/{aid}/submit", json=_submit_body(declared_normal=True, normal_confidence=4))
    d = DebriefResponse.model_validate(c.get(f"/api/attempts/{aid}/debrief").json())
    assert d.status == "ready" and d.source == "template" and d.provenance == "ai_draft"
    assert d.debrief.headline == "Good look"
    assert [k for k, _ in fake_tutor.calls] == ["facts", "debrief"]
    for i in range(3):
        r = c.post(f"/api/attempts/{aid}/ask", json={"question": f"q{i}"}).json()
        assert r["answer"] == f"answer {i + 1}" and r["remaining"] == 2 - i
    assert c.post(f"/api/attempts/{aid}/ask", json={"question": "q4"}).status_code == 409
    nxt = c.get(f"/api/sessions/{s['session_id']}/next").json()["attempt_id"]
    h = c.post(f"/api/attempts/{nxt}/hint", json={"marks": [], "telemetry": []}).json()
    assert h["text"] == "tutor hint 1"


def test_debrief_fails_gracefully_without_tutor(api_env, monkeypatch):
    monkeypatch.setattr(tutor_bridge, "_mod", lambda name: None)
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=4))
    assert r.json()["debrief_status"] == "pending"
    d = c.get(f"/api/attempts/{n['attempt_id']}/debrief").json()
    assert d["status"] == "failed" and "offline" in d["error"]
    a = c.post(f"/api/attempts/{n['attempt_id']}/ask", json={"question": "why?"}).json()
    assert a == {"answer": "The tutor is offline.", "remaining": 2, "source": "template"}


def test_debrief_job_survives_tutor_exception(api_env, fake_tutor, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(tutor_bridge, "generate_debrief", boom)
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=4))
    assert r.status_code == 200
    assert c.get(f"/api/attempts/{n['attempt_id']}/debrief").json()["status"] == "failed"


# ---------------------------------------------------------------- assessment
@pytest.fixture
def assess_root(processed_copy):
    resplit(
        processed_copy,
        {
            "syn_001": "assess_A",
            "syn_002": "assess_A",
            "syn_008": "assess_A",
            "syn_003": "assess_B",
            "syn_009": "bench",
            "syn_010": "holdout",
        },
    )
    return processed_copy


def test_assessment_flow_hides_feedback_until_summary(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c, mode="assess_A")
    sid = s["session_id"]
    for i in range(3):
        n = c.get(f"/api/sessions/{sid}/next").json()
        assert n["total"] == 3 and n["index"] == i + 1 and n["hints_enabled"] is False
        assert c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": []}).status_code == 403
        if i < 2:
            assert c.get(f"/api/sessions/{sid}/summary").status_code == 409
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(marks=[mark("M1", 70, 150, "nodule")]))
        assert r.status_code == 200
        assert r.json() == {"recorded": True, "index": i + 1, "total": 3}
        assert c.get(f"/api/attempts/{n['attempt_id']}/debrief").json()["status"] == "disabled"
        assert c.post(f"/api/attempts/{n['attempt_id']}/ask", json={"question": "?"}).status_code == 403
    assert c.get(f"/api/sessions/{sid}/next").json()["done"] is True
    summ = c.get(f"/api/sessions/{sid}/summary").json()
    assert summ["n_cases"] == 3 and summ["cases"] and "sensitivity" in summ
    assert set(summ["miss_type_mix"]) == {"search", "recognition", "decision", "interpretation", "overcall"}


def test_assessment_does_not_update_elo(api_env, assess_root):
    from backend.app.db import rows, tx

    c = api_env(assess_root)
    s = _session(c, mode="assess_B")
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=3))
    with tx() as con:
        assert not rows(con, "SELECT * FROM ability")
        assert not rows(con, "SELECT * FROM case_difficulty")


def test_practice_never_serves_assessment_or_bench(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c)
    served = set()
    for _ in range(12):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        served.add(n["case"]["case_id"])
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=3))
    assert served <= {"syn_004", "syn_005", "syn_006", "syn_007"}


def test_drill_mode_label(api_env):
    c = api_env()
    s = _session(c, mode="drill", settings={"label": "effusion", "prevalence": 0.7})
    for _ in range(6):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        assert n["case"]["case_id"] in {"syn_003", "syn_006", "syn_008", "syn_009", "syn_010"}
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=3))


def test_learner_reuse_by_participant_code(api_env):
    c = api_env()
    a = _session(c, mode="practice", participant_code="P01")
    b = _session(c, mode="practice", participant_code="P01")
    assert a["learner_id"] == b["learner_id"] and a["session_id"] != b["session_id"]


# ---------------------------------------------------------------- dashboards, review, pilot, about, dev
def test_dashboards(api_env):
    c = api_env()
    s = _session(c)
    for _ in range(6):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        c.post(
            f"/api/attempts/{n['attempt_id']}/submit",
            json=_submit_body(marks=[mark("M1", 70, 150, "nodule", 5)], telemetry=chain(hover(70, 150, 400))),
        )
    d = c.get(f"/api/learners/{s['learner_id']}/dashboard").json()
    assert d["n_attempts"] == 6
    for k in (
        "learning_curve",
        "miss_type_mix",
        "calibration",
        "froc",
        "blindspot_map",
        "review_area_habit",
        "summary",
    ):
        assert "n" in d[k] or "n_images" in d[k], k
    assert len(d["froc"]["points"]) == 5
    co = c.get("/api/cohort/dashboard", params={"level": "MS2"}).json()
    assert co["n_learners"] == 1 and co["n_attempts"] == 6 and co["label_difficulty"]
    assert c.get("/api/cohort/dashboard", params={"level": "MS4"}).json()["n_attempts"] == 0
    assert c.get("/api/learners/nope/dashboard").status_code == 404


def test_review_ratings_export_and_card_writeback(api_env, tmp_path, fake_tutor):
    import yaml

    c = api_env()
    cards = tmp_path / "cards"
    cards.mkdir()
    card = {
        "label": "nodule",
        "display_name": "Nodule",
        "kind": "focal",
        "one_liner": "A small round opacity.",
        "key_signs": ["Round, well-defined opacity"],
        "where_it_hides": ["right_apex"],
        "mimics": ["Nipple shadow"],
        "commonly_confused_with": ["mass"],
        "search_tip": "Check the apices.",
        "radiopaedia_url": None,
        "review": {"status": "ai_draft", "reviewer": None, "date": None, "notes": None},
    }
    (cards / "nodule.yaml").write_text(yaml.safe_dump(card))
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_submit_body(declared_normal=True, normal_confidence=4))
    assert c.post(f"/api/attempts/{n['attempt_id']}/flag", json={"comment": "seems wrong"}).json() == {"ok": True}
    items = c.get("/api/review/items", params={"type": "debrief"}).json()
    live = [i for i in items["items"] if i["origin"] == "live"]
    assert live and live[0]["flags"] == 1 and live[0]["debrief"]["headline"]
    assert c.get("/api/review/items", params={"type": "card"}).json()["items"][0]["item_id"] == "nodule"
    rating = {
        "reviewer": "Sri",
        "role": "student",
        "item_type": "card",
        "item_id": "nodule",
        "accuracy": 5,
        "teaching": 4,
        "safety_flag": False,
        "comment": "ok",
        "card_edits": {"status": "student_reviewed", "search_tip": "Check both apices."},
    }
    assert c.post("/api/review/ratings", json=rating).json() == {"ok": True}
    doc = yaml.safe_load((cards / "nodule.yaml").read_text())
    assert doc["review"]["status"] == "student_reviewed" and doc["search_tip"] == "Check both apices."
    bad = {**rating, "card_edits": {"label": "mass"}}
    assert c.post("/api/review/ratings", json=bad).status_code == 422
    csv_text = c.get("/api/review/export.csv").text
    assert csv_text.splitlines()[0].startswith("id,reviewer") and len(csv_text.splitlines()) == 2


@pytest.mark.parametrize("answers,score", [([5, 1] * 5, 100.0), ([1, 5] * 5, 0.0), ([3] * 10, 50.0)])
def test_sus(api_env, answers, score):
    c = api_env()
    assert c.post("/api/sus", json={"learner_id": "l1", "answers": answers}).json() == {"score": score}


def test_sus_rejects_out_of_range(api_env):
    c = api_env()
    assert c.post("/api/sus", json={"learner_id": "l1", "answers": [6] * 10}).status_code == 422


def test_about(api_env):
    body = api_env().get("/api/about").json()
    assert body["disclaimer"] == "For education. Not for clinical use."
    names = {d["name"] for d in body["datasets"]}
    assert {"ChestX-Det", "NIH ChestX-ray14"} <= names and body["limitations"]


def test_dev_overlay_png(api_env, monkeypatch):
    monkeypatch.setenv("BLINDSPOT_DEV", "1")  # /api/dev is 404 unless BLINDSPOT_DEV=1
    r = api_env().get("/api/dev/cases/syn_005/overlay", params={"layers": "zones,findings"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_404s(api_env):
    c = api_env()
    assert c.get("/api/sessions/nope/next").status_code == 404
    assert c.get("/api/cases/nope/image").status_code == 404
    assert c.post("/api/attempts/nope/submit", json=_submit_body()).status_code == 404
