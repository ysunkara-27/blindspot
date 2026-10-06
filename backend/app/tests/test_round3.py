"""Round 3 (user feedback + UX audit): session options, summary for every mode, per-case review (stored result,
lazy assessment debrief), facts-card copy, whole-number scores, first-run-safe database init.

Synthetic fixtures only; offline; no Anthropic calls."""

from __future__ import annotations

import json
import random
import subprocess
import sys
import threading
from collections import Counter

import pytest

from backend.app import config, db
from backend.app.adaptive.selector import CaseInfo, LearnerState, note_drawn, select_next
from backend.app.facts_card import build_facts_card, dwell_text
from backend.app.scoring.scores import ScoreParts, case_score, round_score, score_text
from backend.app.settings import REPO_ROOT
from backend.app.tests.conftest import chain, hover, make_submit, mark, resplit
from backend.app.tests.test_gt_leak import assert_no_ground_truth
from shared.contracts import FactsSearch, Outcome, SubmitResult

SEL = config.adaptive()["selection"]
CORE = list(config.core_labels())


def _session(c, mode="practice", **settings):
    r = c.post("/api/sessions", json={"display_name": "R3", "level": "other", "mode": mode, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()


def _body(**kw) -> dict:
    return json.loads(make_submit(**kw).model_dump_json())


def _play(c, sid: str, k: int, **kw) -> list[dict]:
    """Serve and submit up to k cases; returns [{attempt_id, case_id, result}]."""
    out = []
    for _ in range(k):
        n = c.get(f"/api/sessions/{sid}/next").json()
        if n["done"]:
            break
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(**(kw or {"declared_normal": True})))
        assert r.status_code == 200, r.text
        out.append({"attempt_id": n["attempt_id"], "case_id": n["case"]["case_id"], "result": r.json(), "next": n})
    return out


# ------------------------------------------------------------------ 1. session options
def test_case_count_sets_total_and_done_without_a_new_attempt(api_env):
    c = api_env()
    s = _session(c, case_count=5, selection="random")
    sid = s["session_id"]
    played = _play(c, sid, 9)
    assert len(played) == 5
    assert [p["next"]["index"] for p in played] == [1, 2, 3, 4, 5]
    assert all(p["next"]["total"] == 5 for p in played)
    done = c.get(f"/api/sessions/{sid}/next").json()
    assert done == {
        "attempt_id": "",
        "case": {"case_id": "", "image_url": "", "width": 0, "height": 0},
        "index": 5,
        "total": 5,
        "hints_enabled": False,
        "done": True,
    }
    with db.tx() as con:
        assert db.row(con, "SELECT COUNT(*) AS n FROM attempts WHERE session_id=?", sid)["n"] == 5
        assert db.row(con, "SELECT ended_at FROM sessions WHERE id=?", sid)["ended_at"]


def test_open_attempt_is_returned_before_done(api_env):
    c = api_env()
    sid = _session(c, case_count=3)["session_id"]
    _play(c, sid, 2)
    n = c.get(f"/api/sessions/{sid}/next").json()
    assert not n["done"] and n["index"] == 3
    assert c.get(f"/api/sessions/{sid}/next").json()["attempt_id"] == n["attempt_id"]  # still open, not "done"
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(declared_normal=True))
    assert c.get(f"/api/sessions/{sid}/next").json()["done"] is True


def test_no_case_count_means_open_ended(api_env):
    c = api_env()
    sid = _session(c)["session_id"]
    n = c.get(f"/api/sessions/{sid}/next").json()
    assert n["total"] is None and not n["done"]


@pytest.mark.parametrize("bad", [2, 51, 0, -1, "5", 4.5, True, [5]])
def test_case_count_out_of_contract_is_422(api_env, bad):
    c = api_env()
    r = c.post(
        "/api/sessions",
        json={"display_name": "R3", "level": "other", "mode": "practice", "settings": {"case_count": bad}},
    )
    assert r.status_code == 422, (bad, r.text)


def test_selection_out_of_contract_is_422_and_valid_values_pass(api_env):
    c = api_env()
    for sel in ("adaptive", "weak_areas", "random"):
        sid = _session(c, selection=sel, case_count=3)["session_id"]
        assert len(_play(c, sid, 5)) == 3
    r = c.post(
        "/api/sessions",
        json={"display_name": "R3", "level": "other", "mode": "practice", "settings": {"selection": "hardest"}},
    )
    assert r.status_code == 422


def test_prevalence_abnormal_is_clamped_and_legacy_key_still_read(api_env):
    c = api_env()
    for settings, want in (
        ({"prevalence_abnormal": 0.95}, 0.7),
        ({"prevalence_abnormal": 0.1}, 0.3),
        ({"prevalence": 0.6}, 0.6),
        ({"prevalence_abnormal": "x"}, None),
    ):
        sid = _session(c, **settings)["session_id"]
        with db.tx() as con:
            st = json.loads(db.row(con, "SELECT settings_json FROM sessions WHERE id=?", sid)["settings_json"])
        assert st.get("prevalence_abnormal") == want and "prevalence" not in st


def test_drill_with_case_count_and_label(api_env):
    c = api_env()
    sid = _session(c, mode="drill", label="effusion", case_count=4, selection="random")["session_id"]
    played = _play(c, sid, 6)
    assert len(played) == 4
    assert {p["case_id"] for p in played} <= {"syn_003", "syn_006", "syn_008", "syn_009", "syn_010"}


def test_level_is_not_an_engine_input(api_env):
    """The UI sends level "other" for everyone: scoring and selection are identical whatever the level says."""
    c = api_env()
    served = {}
    for level in ("other", "MS1", "resident"):
        s = c.post("/api/sessions", json={"display_name": f"L-{level}", "level": level, "mode": "practice"}).json()
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(marks=[mark("M1", 70, 150, "nodule")]))
        served[level] = (n["total"], n["hints_enabled"], set(r.json()))
    assert len({str(v) for v in served.values()}) == 1


def _pool() -> list[CaseInfo]:
    pool = [CaseInfo(f"n{i}", True, (), 0.0) for i in range(40)]
    for lab in CORE:
        pool += [CaseInfo(f"{lab}{i}", False, (lab,), 0.0) for i in range(40)]
    pool += [CaseInfo("assess", False, (CORE[0],), 0.0, "assess_A"), CaseInfo("bench", False, (CORE[0],), 0.0, "bench")]
    pool += [CaseInfo("flagged", False, (CORE[0],), 0.0, "practice", ("orientation_suspect",))]
    return pool


def test_weak_areas_always_targets_the_weakest_core_label():
    pool = _pool()
    weakest = CORE[2]
    abilities = {lab: (1.0, 5) for lab in CORE}
    abilities[weakest] = (-1.5, 5)
    for seed in range(5):
        rng = random.Random(seed)
        state = LearnerState(abilities=dict(abilities))
        labels = []
        for _ in range(30):
            pick = select_next(pool, state, SEL, rng, core=CORE, strategy="weak_areas")
            note_drawn(state, pick, CORE)
            if not pick.is_normal:
                labels.append(pick.labels[0])
        assert labels and set(labels) == {weakest}, (seed, Counter(labels))  # adaptive would mix in other labels


def test_random_selection_is_uniform_over_the_eligible_pool_at_the_prevalence():
    pool = _pool()
    picks: Counter = Counter()
    n_abn = 0
    for seed in range(40):
        rng = random.Random(seed)
        state = LearnerState(abilities={CORE[0]: (-2.0, 9)})  # a weak label must NOT attract random selection
        for _ in range(20):
            pick = select_next(pool, state, SEL, rng, core=CORE, strategy="random", prevalence=0.5)
            note_drawn(state, pick, CORE)
            assert pick.split == "practice" and not pick.qa_flags
            n_abn += not pick.is_normal
            if not pick.is_normal:
                picks[pick.labels[0]] += 1
    assert abs(n_abn / 800 - 0.5) <= 0.05
    share = picks[CORE[0]] / sum(picks.values())
    assert abs(share - 1 / len(CORE)) < 0.06, picks  # no label is favoured
    assert not {"assess", "bench", "flagged"} & set(picks)


# ------------------------------------------------------------------ 2. summary for every mode
ROW_KEYS = {
    "attempt_id",
    "case_id",
    "index",
    "score",
    "success",
    "is_normal",
    "labels",
    "label_displays",
    "miss_types",
    "n_findings",
    "n_found",
    "n_false_positives",
    "outcomes",
    "findings",
}


@pytest.mark.parametrize("mode", ["practice", "drill", "review"])
def test_summary_available_any_time_outside_assessment(api_env, mode):
    c = api_env()
    settings = {"label": "effusion"} if mode == "drill" else {}
    sid = _session(c, mode=mode, case_count=3, **settings)["session_id"]
    empty = c.get(f"/api/sessions/{sid}/summary")
    assert empty.status_code == 200
    e = empty.json()
    assert e["n_cases"] == 0 and e["cases"] == [] and e["total"] == 3 and e["complete"] is False
    assert e["sensitivity"] is None and e["specificity"] is None
    n = c.get(f"/api/sessions/{sid}/next").json()  # an open attempt is not part of the summary
    assert c.get(f"/api/sessions/{sid}/summary").json()["n_cases"] == 0
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(marks=[mark("M1", 128, 128, "nodule")]))
    mid = c.get(f"/api/sessions/{sid}/summary").json()
    assert mid["n_cases"] == 1 and mid["complete"] is False and mid["mode"] == mode
    played = _play(c, sid, 5)
    summ = c.get(f"/api/sessions/{sid}/summary").json()
    assert summ["n_cases"] == 3 and summ["complete"] is True
    assert [r["index"] for r in summ["cases"]] == [1, 2, 3]
    assert [r["attempt_id"] for r in summ["cases"]] == [n["attempt_id"], *[p["attempt_id"] for p in played]]
    for r in summ["cases"]:
        assert set(r) == ROW_KEYS
        assert set(r["miss_types"]) <= {"search", "recognition", "decision", "interpretation", "overcall"}
        assert r["is_normal"] == (r["labels"] == []) and len(r["labels"]) == len(r["label_displays"])


def test_summary_rows_carry_labels_and_miss_types(api_env):
    c = api_env()
    sid = _session(c)["session_id"]
    rows = {}
    for _ in range(10):  # the fixture pool has 10 cases; practice cycles through all of them
        n = c.get(f"/api/sessions/{sid}/next").json()
        cid = n["case"]["case_id"]
        if cid == "syn_005":  # mass F1 (found, called nodule) + nodule F2 (never looked) + one mark on nothing
            body = _body(
                marks=[mark("M1", 80, 95, "nodule"), mark("M2", 128, 20, "nodule")],
                telemetry=chain(hover(80, 95, 800)),
            )
        elif cid == "syn_008":
            body = _body(marks=[mark("M1", 100, 100, "nodule")])
        else:
            body = _body(declared_normal=True)
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body).json()
        rows[cid] = (n["attempt_id"], r)
    summ = c.get(f"/api/sessions/{sid}/summary").json()
    by_case = {r["case_id"]: r for r in summ["cases"]}
    r5 = by_case["syn_005"]
    assert r5["labels"] == ["mass", "nodule"] and r5["label_displays"] == ["Mass", "Nodule"]
    assert r5["miss_types"] == ["search", "interpretation", "overcall"]
    assert (r5["n_findings"], r5["n_found"], r5["n_false_positives"]) == (2, 1, 1)
    assert r5["attempt_id"] == rows["syn_005"][0] and r5["score"] == rows["syn_005"][1]["score"]
    r8 = by_case["syn_008"]
    assert r8["is_normal"] is True and r8["labels"] == [] and r8["miss_types"] == ["overcall"]
    assert by_case["syn_009"]["miss_types"] == [] and by_case["syn_009"]["success"] is True
    assert summ["total"] is None and summ["complete"] is False  # open-ended session


# ------------------------------------------------------------------ 3. per-case review
def test_result_returns_the_stored_submit_result(api_env):
    c = api_env()
    sid = _session(c)["session_id"]
    n = c.get(f"/api/sessions/{sid}/next").json()
    aid = n["attempt_id"]
    pre = c.get(f"/api/attempts/{aid}/result")
    assert pre.status_code == 409
    assert_no_ground_truth(pre.json(), n["case"]["case_id"])
    sub = c.post(
        f"/api/attempts/{aid}/submit",
        json=_body(
            marks=[mark("M1", 70, 150, "nodule"), mark("M2", 200, 40, "mass")], telemetry=chain(hover(70, 150, 900))
        ),
    ).json()
    got = c.get(f"/api/attempts/{aid}/result")
    assert got.status_code == 200
    body = got.json()
    assert set(body) == set(sub) | {"case", "submitted"}
    assert {k: body[k] for k in sub} == sub  # the SubmitResult part is identical: reveal, heatmap, facts card
    res = SubmitResult.model_validate({k: body[k] for k in sub})
    assert res.debrief_status == "pending" and res.facts_card.lines and res.reveal.search.heatmap_png_b64
    # plus which film it was and what the learner did, so the review page needs only the attempt id
    assert body["case"] == n["case"]
    assert body["submitted"] == {
        "marks": [
            {"mark_id": "M1", "x": 70.0, "y": 150.0, "label": "nodule", "confidence": 4},
            {"mark_id": "M2", "x": 200.0, "y": 40.0, "label": "mass", "confidence": 4},
        ],
        "patterns": [],
        "declared_normal": False,
        "normal_confidence": None,
    }
    assert c.get("/api/attempts/nope/result").status_code == 404


def test_result_is_rebuilt_for_attempts_stored_before_result_json(api_env):
    c = api_env()
    sid = _session(c)["session_id"]
    n = c.get(f"/api/sessions/{sid}/next").json()
    sub = c.post(
        f"/api/attempts/{n['attempt_id']}/submit",
        json=_body(marks=[mark("M1", 70, 150, "nodule")], telemetry=chain(hover(70, 150, 900))),
    ).json()
    with db.tx() as con:
        con.execute("UPDATE attempts SET result_json=NULL WHERE id=?", (n["attempt_id"],))
    got = c.get(f"/api/attempts/{n['attempt_id']}/result").json()
    assert got["score"] == sub["score"] and got["outcomes"] == sub["outcomes"]
    assert got["reveal"]["findings"] == sub["reveal"]["findings"] and got["reveal"]["marks"] == sub["reveal"]["marks"]
    assert got["facts_card"]["headline"] == sub["facts_card"]["headline"]


@pytest.fixture
def assess_root(processed_copy):
    resplit(processed_copy, {"syn_001": "assess_A", "syn_005": "assess_A", "syn_008": "assess_A"})
    return processed_copy


def test_assessment_result_and_debrief_only_after_completion(api_env, assess_root):
    c = api_env(assess_root)
    sid = _session(c, mode="assess_A")["session_id"]
    aids = []
    for i in range(3):
        n = c.get(f"/api/sessions/{sid}/next").json()
        aid = n["attempt_id"]
        for path in ("result", "debrief"):  # before submit
            r = c.get(f"/api/attempts/{aid}/{path}")
            assert_no_ground_truth(r.json(), n["case"]["case_id"])
            assert r.status_code == 409 if path == "result" else r.json() == {"status": "disabled"}
        rec = c.post(f"/api/attempts/{aid}/submit", json=_body(marks=[mark("M1", 70, 150, "nodule")]))
        assert set(rec.json()) == {"recorded", "index", "total"}
        aids.append((aid, n["case"]["case_id"]))
        if i < 2:  # submitted, session incomplete: every earlier attempt is still locked
            for a, cid in aids:
                r = c.get(f"/api/attempts/{a}/result")
                assert r.status_code == 409
                assert_no_ground_truth(r.json(), cid)
                d = c.get(f"/api/attempts/{a}/debrief")
                assert d.json() == {"status": "disabled"}
                assert c.post(f"/api/attempts/{a}/ask", json={"question": "what did I miss?"}).status_code == 403
            with db.tx() as con:
                assert db.rows(con, "SELECT id FROM debriefs") == []  # nothing generated while the assessment runs
    # complete: stored results open up, debriefs are generated lazily (offline here → template)
    for a, cid in aids:
        body = c.get(f"/api/attempts/{a}/result").json()
        assert body["case"]["case_id"] == cid and body["submitted"]["marks"][0]["mark_id"] == "M1"
        res = SubmitResult.model_validate({k: v for k, v in body.items() if k not in ("case", "submitted")})
        assert res.debrief_status == "pending" and res.facts_card.headline
        assert res.reveal.is_normal == (cid == "syn_008")
        first = c.get(f"/api/attempts/{a}/debrief").json()
        assert first == {"status": "pending"}
        ready = c.get(f"/api/attempts/{a}/debrief").json()
        assert ready["status"] == "ready" and ready["source"] == "template" and ready["debrief"]["headline"]
        c.get(f"/api/attempts/{a}/debrief")
    with db.tx() as con:
        n_rows = Counter(r["attempt_id"] for r in db.rows(con, "SELECT attempt_id FROM debriefs"))
        assert n_rows == {a: 1 for a, _ in aids}  # generated once per attempt, not once per request
        assert db.rows(con, "SELECT * FROM ability") == []  # reviewing an assessment never touches Elo
    a0 = aids[0][0]
    assert c.post(f"/api/attempts/{a0}/ask", json={"question": "Where was it?"}).status_code == 200
    assert c.post(f"/api/attempts/{a0}/hint", json={"marks": [], "telemetry": []}).status_code in (403, 409)


def test_drill_focus_label_reaches_the_tutor(api_env, monkeypatch):
    from backend.app import tutor_bridge

    seen = []
    real = tutor_bridge.generate_debrief

    def spy(facts, case, **kw):
        seen.append(kw.get("focus_label"))
        return real(facts, case, **kw)

    monkeypatch.setattr(tutor_bridge, "generate_debrief", spy)
    c = api_env()
    _play(c, _session(c, mode="drill", label="effusion", case_count=3)["session_id"], 1)
    _play(c, _session(c, mode="practice", label="effusion", case_count=3)["session_id"], 1)
    _play(c, _session(c, mode="drill", label="not_a_label", case_count=3)["session_id"], 1)
    assert seen == ["effusion", None, None]


# ------------------------------------------------------------------ 6. facts card copy + whole-number scores
def test_scores_are_whole_numbers_rounded_half_up():
    half = ScoreParts(4, 1, 1.0, 0, 0, 1, 0, 0)  # 70·¼ + 20·¼ + 10 − 10 = 22.5 (the audit's "22 vs 23" case)
    assert case_score(half, False, config.scoring()) == 23.0
    assert (round_score(22.5), round_score(23.5), round_score(22.49), round_score(-3), round_score(140)) == (
        23.0,
        24.0,
        22.0,
        0.0,
        100.0,
    )
    assert score_text(22.5) == "23" and score_text(100.0) == "100"


def test_facts_card_score_is_exactly_submit_result_score(api_env, repo):
    case = repo.get("syn_005")
    outs = [Outcome(target="F1", result="found"), Outcome(target="F2", result="missed_search", dwell_ms=0.0)]
    search = FactsSearch(lung_coverage_pct=62.5, unvisited_review_areas=[], first_visits=[])
    for raw in (22.5, 23.5, 0.5, 99.5, 55.0):
        card = build_facts_card(case, outs, raw, False, search, False)
        assert card.lines[-1] == f"Lung coverage 63%. Score {int(round_score(raw))}."
    c = api_env()
    sid = _session(c)["session_id"]
    scripts = [
        {"marks": [mark("M1", 70, 150, "mass")]},
        {"marks": [mark("M1", 80, 95, "nodule"), mark("M2", 128, 20, "nodule")]},
        {"marks": [mark("M1", 190, 170, "calcification"), mark("M2", 30, 30, "mass"), mark("M3", 220, 30, "mass")]},
        {"declared_normal": True},
    ]
    for i in range(10):
        n = c.get(f"/api/sessions/{sid}/next").json()
        res = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=_body(**scripts[i % len(scripts)])).json()
        assert res["score"] == int(res["score"])
        assert res["facts_card"]["lines"][-1].endswith(f"Score {int(res['score'])}.")
    summ = c.get(f"/api/sessions/{sid}/summary").json()
    assert all(r["score"] == int(r["score"]) for r in summ["cases"])


def test_dwell_is_said_in_words_never_as_milliseconds(repo):
    assert dwell_text(0) == dwell_text(None) == dwell_text(99.9) == "no time spent there"
    assert dwell_text(100) == "about 0.1 s there" and dwell_text(449) == "about 0.4 s there"
    assert dwell_text(450) == "about 0.5 s there" and dwell_text(2349) == "about 2.3 s there"
    assert dwell_text(9949) == "about 9.9 s there" and dwell_text(9950) == "about 10 s there"
    assert dwell_text(31400) == "about 31 s there"
    case = repo.get("syn_005")
    search = FactsSearch(lung_coverage_pct=10, unvisited_review_areas=["right_apex"], first_visits=[])
    outs = [
        Outcome(target="F2", result="missed_recognition", dwell_ms=412.0),
        Outcome(target="F1", result="missed_search", dwell_ms=0.0),
    ]
    card = build_facts_card(case, outs, 0, False, search, False)
    text = " ".join([card.headline, *card.lines])
    assert " ms" not in text and "dwell" not in text.lower()
    assert "Never looked there (no time spent there)." in card.lines[0]
    assert "Looked past it (about 0.4 s there)." in card.lines[1]


def test_facts_card_lists_findings_in_id_order_and_never_says_overcall(repo, tmp_path):
    from shared.contracts import Case

    base = repo.get("syn_005").model_dump()
    pat = repo.get("syn_007").findings[0].model_dump()
    # F1 pattern, F2 focal, F3 focal: the card must follow the ids, not "focal first"
    f_mass, f_nod = base["findings"]
    base["findings"] = [
        {**pat, "finding_id": "syn_005#F1"},
        {**f_mass, "finding_id": "syn_005#F2"},
        {**f_nod, "finding_id": "syn_005#F3"},
    ]
    case = Case.model_validate(base)
    search = FactsSearch(lung_coverage_pct=40, unvisited_review_areas=[], first_visits=[])
    outs = [  # deliberately shuffled, with two extra marks and one extra global tick
        Outcome(target="M2", result="false_positive", zone="left_apex"),
        Outcome(target="F3", result="missed_decision", dwell_ms=1500.0),
        Outcome(target="M1", result="false_positive", zone="right_apex"),
        Outcome(target="F2", result="found"),
        Outcome(target="F1", result="pattern_missed"),
        Outcome(target="emphysema", result="pattern_false"),
    ]
    card = build_facts_card(case, outs, 40, False, search, False)
    assert [ln.split()[0] for ln in card.lines[:5]] == ["F1", "F2", "F3", "M1", "M2"]
    assert card.headline == (
        "You found 1 of 3 findings — plus 2 marks where radiologists marked nothing and 1 ticked finding "
        "radiologists did not report"
    )
    normal = repo.get("syn_008")
    one = build_facts_card(
        normal, [Outcome(target="M1", result="false_positive", zone="right_apex")], 75, False, search, False
    )
    assert one.headline == "This film is normal — 1 mark where radiologists marked nothing"
    for cd in (card, one):
        assert "overcall" not in " ".join([cd.headline, *cd.lines]).lower()
    # nothing found: repeated labels are counted, not repeated ("Nodule, Nodule, Nodule" on a crowded film)
    missed = [Outcome(target=f"F{i}", result="missed_search", dwell_ms=0.0) for i in (1, 2, 3)]
    none = build_facts_card(case, missed, 0, False, search, False)
    assert none.headline == "Missed: Cardiomegaly, Mass, Nodule"
    base["findings"][1] = {**f_nod, "finding_id": "syn_005#F2"}
    twice = build_facts_card(Case.model_validate(base), missed, 0, False, search, False)
    assert twice.headline == "Missed: Cardiomegaly (1), Nodule (2)"


# ------------------------------------------------------------------ 9. first-run-safe database init
def test_eight_concurrent_first_requests_on_a_fresh_database(api_env, tmp_path):
    from fastapi.testclient import TestClient

    api_env()  # fresh temp DB path; nothing has touched it yet
    assert not db.db_path().exists()
    from backend.app.main import app

    barrier = threading.Barrier(8)
    results: list[tuple[int, str]] = []

    def first_request(i: int) -> None:
        client = TestClient(app)
        barrier.wait()
        r = client.post("/api/sessions", json={"display_name": f"first-{i}", "level": "other", "mode": "practice"})
        n = client.get(f"/api/sessions/{r.json().get('session_id')}/next") if r.status_code == 200 else r
        results.append((r.status_code, n.text if n.status_code != 200 else "ok"))

    threads = [threading.Thread(target=first_request, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert results == [(200, "ok")] * 8, results
    with db.tx() as con:
        assert db.row(con, "SELECT COUNT(*) AS n FROM learners")["n"] == 8
        assert db.row(con, "SELECT COUNT(*) AS n FROM attempts")["n"] == 8
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS


def test_eight_processes_initialise_one_fresh_database(tmp_path):
    p = tmp_path / "fresh.sqlite"
    code = (
        "import sys; from pathlib import Path; from backend.app import db\n"
        "p = Path(sys.argv[1])\n"
        "with db.tx(p, immediate=True) as con:\n"
        "    con.execute('INSERT INTO learners(id, display_name, created_at) VALUES (?,?,?)',"
        " (db.new_id(), sys.argv[2], db.now_iso()))\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(p), f"p{i}"], cwd=REPO_ROOT, stderr=subprocess.PIPE, text=True
        )
        for i in range(8)
    ]
    errs = [(pr.wait(timeout=120), pr.stderr.read()) for pr in procs]
    assert all(rc == 0 for rc, _ in errs), [e for rc, e in errs if rc]
    with db.tx(p) as con:
        assert db.row(con, "SELECT COUNT(*) AS n FROM learners")["n"] == 8
        cols = {r[1] for r in con.execute("PRAGMA table_info(attempts)").fetchall()}
    assert "result_json" in cols


def test_init_db_migrates_a_database_created_before_result_json(tmp_path):
    import sqlite3

    p = tmp_path / "old.sqlite"
    con = sqlite3.connect(p)
    con.executescript(db.SCHEMA.replace(", result_json TEXT", ""))
    con.execute("INSERT INTO learners(id, display_name, created_at) VALUES ('a','b','c')")
    con.commit()
    con.close()
    db.init_db(p, force=True)
    with db.tx(p) as con:
        assert "result_json" in {r[1] for r in con.execute("PRAGMA table_info(attempts)").fetchall()}
        assert db.row(con, "SELECT COUNT(*) AS n FROM learners")["n"] == 1  # data kept


def test_two_concurrent_next_calls_share_one_attempt(api_env):
    from fastapi.testclient import TestClient

    c = api_env()
    sid = _session(c, case_count=3)["session_id"]
    from backend.app.main import app

    barrier = threading.Barrier(6)
    got: list[str] = []

    def call() -> None:
        client = TestClient(app)
        barrier.wait()
        got.append(client.get(f"/api/sessions/{sid}/next").json()["attempt_id"])

    ts = [threading.Thread(target=call) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert len(got) == 6 and len(set(got)) == 1
    with db.tx() as con:
        assert db.row(con, "SELECT COUNT(*) AS n FROM attempts WHERE session_id=?", sid)["n"] == 1
