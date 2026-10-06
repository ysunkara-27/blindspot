"""QA spot checks through the HTTP API on SYNTHETIC fixtures (owner: qa-reviewer; no real data, no API calls).

1. Patient-side convention: patient RIGHT is displayed on the image LEFT.
2. Scripted-telemetry miss types, label partial credit, normal-case scoring, all through POST /submit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.tests.conftest import FIXTURES, chain, hover, make_submit, mark, sweep
from shared.contracts import Case, SubmitResult


def _cases() -> dict[str, Case]:
    return {
        c.case_id: c for c in (Case.model_validate_json(x) for x in (FIXTURES / "cases.jsonl").read_text().splitlines())
    }


def _play(c, target: str, **submit_kw) -> SubmitResult:
    """Walk a practice session (which cycles every fixture case) until `target` is served; submit it with the script."""
    sid = c.post("/api/sessions", json={"display_name": "QA", "level": "MS3", "mode": "practice"}).json()["session_id"]
    for _ in range(12):
        n = c.get(f"/api/sessions/{sid}/next").json()
        aid = n["attempt_id"]
        if n["case"]["case_id"] == target:
            body = json.loads(make_submit(**submit_kw).model_dump_json())
            r = c.post(f"/api/attempts/{aid}/submit", json=body)
            assert r.status_code == 200, r.text
            return SubmitResult.model_validate(r.json())
        c.post(
            f"/api/attempts/{aid}/submit",
            json=json.loads(make_submit(declared_normal=True, normal_confidence=3).model_dump_json()),
        )
    raise AssertionError(f"{target} never served")


# --------------------------------------------------------------------------- patient-side convention
def test_fixture_finding_side_follows_patient_side_convention():
    """Centroid at image-left (x < W/2) => the patient's RIGHT; image-right => LEFT. Zone ids carry the same side."""
    n = 0
    for case in _cases().values():
        for f in case.findings:
            if f.side in ("midline", "bilateral", None):
                continue
            n += 1
            cx = f.centroid[0]
            want = "right" if cx < case.width / 2 else "left"
            assert f.side == want, f"{f.finding_id}: centroid x={cx} W={case.width} side={f.side}"
            if f.primary_zone and f.primary_zone.split("_")[0] in ("right", "left"):
                assert f.primary_zone.startswith(want + "_"), (f.finding_id, f.primary_zone)
    assert n >= 8


def test_mark_at_image_left_is_reported_in_a_right_zone(api_env):
    c = api_env()
    # syn_001: nodule at image-left (70,150). A mark there is a hit; its zone must be a right_* zone.
    res = _play(c, "syn_001", marks=[mark("M1", 70, 150, "nodule")], telemetry=chain(hover(70, 150, 800)))
    z = {m.mark_id: m.zone for m in res.reveal.marks}["M1"]
    assert z is not None and z.startswith("right_"), z
    # syn_002: pneumothorax at image-right; a stray mark on image-left in the same film is a false positive in a right_* zone
    res = _play(c, "syn_002", marks=[mark("M1", 60, 100, "pneumothorax")])
    fp = [m for m in res.reveal.marks if m.result == "false_positive"]
    assert fp and fp[0].zone and fp[0].zone.startswith("right_"), fp
    # and a mark at image-right is a left_* zone
    res = _play(c, "syn_001", marks=[mark("M1", 200, 120, "nodule")])
    fp = [m for m in res.reveal.marks if m.result == "false_positive"]
    assert fp and fp[0].zone and fp[0].zone.startswith("left_"), fp
    # the reveal reports finding sides consistently with centroids
    for f in res.reveal.findings:
        assert f.side == ("right" if f.centroid[0] < 128 else "left")


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[3] / "data" / "processed" / "cases.jsonl").exists(), reason="no real data"
)
def test_real_data_side_matches_centroid_where_assigned():
    """Real cases (M2 may still be filling zones): lateral findings with a side must agree with the centroid for >= 97%."""
    import itertools

    root = Path(__file__).resolve().parents[3] / "data" / "processed" / "cases.jsonl"
    ok = bad = 0
    bad_ids = []
    for line in itertools.islice(root.open(), None):
        c = json.loads(line)
        if "orientation_suspect" in c.get("qa_flags", []):
            continue
        for f in c["findings"]:
            if f.get("side") in ("right", "left"):
                want = "right" if f["centroid"][0] < c["width"] / 2 else "left"
                if f["side"] == want:
                    ok += 1
                else:
                    bad += 1
                    bad_ids.append(f["finding_id"])
    assert ok + bad == 0 or bad / (ok + bad) < 0.03, (ok, bad, bad_ids[:10])


# --------------------------------------------------------------------------- miss types and scoring
def _outcome(res: SubmitResult, target_suffix: str):
    return next(o for o in res.outcomes if o.target.endswith(target_suffix))


def test_telemetry_never_entering_roi_is_missed_search(api_env):
    c = api_env()
    # syn_002 pneumothorax at (185,40). Pointer wanders the opposite corner for 3 s.
    tel = chain(sweep((20, 230), (60, 240), 3000))
    res = _play(c, "syn_002", telemetry=tel, declared_normal=True, normal_confidence=3)
    o = _outcome(res, "F1")
    assert o.result == "missed_search" and (o.dwell_ms or 0) < 300


def test_dwell_about_two_seconds_in_roi_is_missed_decision(api_env):
    c = api_env()
    # syn_003 effusion at (55,215); learner hovers there ~2 s and declares the film normal.
    res = _play(c, "syn_003", telemetry=chain(hover(55, 215, 2000)), declared_normal=True, normal_confidence=4)
    o = _outcome(res, "F1")
    assert o.result == "missed_decision" and (o.dwell_ms or 0) >= 1000, o


def test_brief_dwell_is_missed_recognition(api_env):
    c = api_env()
    res = _play(c, "syn_003", telemetry=chain(hover(55, 215, 600)), declared_normal=True, normal_confidence=3)
    o = _outcome(res, "F1")
    assert o.result == "missed_recognition", o


def test_mark_in_mask_with_related_label_is_mislabeled_with_partial_credit(api_env):
    c = api_env()
    # syn_004 consolidation at (175,120); atelectasis is in the same related group.
    exact = _play(c, "syn_004", marks=[mark("M1", 175, 120, "consolidation")], telemetry=chain(hover(175, 120, 800)))
    related = _play(c, "syn_004", marks=[mark("M1", 175, 120, "atelectasis")], telemetry=chain(hover(175, 120, 800)))
    other = _play(c, "syn_004", marks=[mark("M1", 175, 120, "effusion")], telemetry=chain(hover(175, 120, 800)))
    assert _outcome(exact, "F1").result == "found"
    assert _outcome(related, "F1").result == "mislabeled"
    assert _outcome(other, "F1").result == "mislabeled"
    assert other.score < related.score < exact.score, (other.score, related.score, exact.score)
    assert related.score >= 70  # localization credit is kept


def test_normal_case_called_normal_scores_100_true_negative(api_env):
    c = api_env()
    res = _play(
        c, "syn_008", declared_normal=True, normal_confidence=5, telemetry=chain(sweep((20, 20), (230, 230), 2000))
    )
    assert res.score == 100 and res.success
    assert any(o.result == "true_negative" for o in res.outcomes)
    assert res.reveal.is_normal is True


def test_normal_case_with_a_mark_is_overcall_and_penalized(api_env):
    c = api_env()
    res = _play(c, "syn_008", marks=[mark("M1", 100, 100, "nodule")])
    assert res.score < 100 and not res.success
    assert any(o.result == "false_positive" for o in res.outcomes)


def test_hints_cost_points_on_normal_case(api_env):
    c = api_env()
    res = _play(c, "syn_009", declared_normal=True, normal_confidence=3, hints=2)
    assert res.score == 100 - 2 * 5
