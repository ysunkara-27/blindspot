"""SPEC §6: hit test, Hungarian matching (duplicates, related labels), outcomes and scores."""

from __future__ import annotations

import numpy as np

from backend.app import config
from backend.app.engine import evaluate
from backend.app.scoring.hit import hits, tolerance_px
from backend.app.scoring.matching import label_cost, match
from backend.app.scoring.scores import case_score, case_success, parts
from backend.app.tests.conftest import make_submit, mark
from shared.contracts import Outcome, PatternSelection

COSTS = config.scoring()["matching_costs"]
GROUPS = config.related_groups()


def test_tolerance_from_config():
    assert tolerance_px(1024, config.scoring()) == config.scoring()["hit"]["tolerance_frac"] * 1024


def test_hit_mask_dilated_and_bbox_fallback(repo):
    case = repo.get("syn_001")
    f = case.findings[0]  # nodule at (70, 150), r = 7
    tau = tolerance_px(case.width, config.scoring())  # 5.12 px
    dm = repo.dilated_mask(case.case_id, f.finding_id, int(round(tau)))
    assert hits(70, 150, f, tau, dm)
    assert hits(70 + 7 + 4, 150, f, tau, dm)  # inside tolerance ring
    assert not hits(70 + 7 + 8, 150, f, tau, dm)
    assert not hits(-5, 300, f, tau, dm)  # out of image
    # bbox fallback
    x0, y0, x1, y1 = f.geometry.bbox
    assert hits(x1 + tau - 0.1, y0, f, tau, None)
    assert not hits(x1 + tau + 0.5, y0, f, tau, None)


def test_dilated_mask_is_cached(repo):
    a = repo.dilated_mask("syn_001", "syn_001#F1", 5)
    b = repo.dilated_mask("syn_001", "syn_001#F1", 5)
    assert a is b


def test_label_costs():
    assert label_cost("nodule", "nodule", GROUPS, COSTS) == COSTS["exact"]
    assert label_cost("mass", "nodule", GROUPS, COSTS) == COSTS["related"]
    assert label_cost("atelectasis", "consolidation", GROUPS, COSTS) == COSTS["related"]
    assert label_cost("effusion", "nodule", GROUPS, COSTS) == COSTS["other"]
    assert label_cost("not_sure", "nodule", GROUPS, COSTS) == COSTS["other"]


def test_matching_prefers_exact_label_and_flags_duplicates():
    # M1 (mass) and M2 (nodule) both hit F1 (nodule); M3 hits nothing
    hit = np.array([[True], [True], [False]])
    r = match(["M1", "M2", "M3"], ["mass", "nodule", "nodule"], ["F1"], ["nodule"], hit, GROUPS, COSTS)
    assert r.pairs == {"M2": "F1"}
    assert r.duplicates == {"M1": "F1"}
    assert r.false_positives == ["M3"]


def test_matching_global_optimum():
    # M1 hits F1 and F2, M2 hits only F1 → Hungarian must give M1→F2, M2→F1
    hit = np.array([[True, True], [True, False]])
    r = match(["M1", "M2"], ["nodule", "nodule"], ["F1", "F2"], ["nodule", "nodule"], hit, GROUPS, COSTS)
    assert r.pairs == {"M1": "F2", "M2": "F1"}
    assert not r.duplicates and not r.false_positives


def test_matching_related_beats_other():
    hit = np.array([[True, True]])
    r = match(["M1"], ["mass"], ["F1", "F2"], ["effusion", "nodule"], hit, GROUPS, COSTS)
    assert r.pairs == {"M1": "F2"} and r.pair_cost["M1"] == COSTS["related"]


def test_matching_no_findings_all_fp():
    r = match(["M1"], ["nodule"], [], [], np.zeros((1, 0), bool), GROUPS, COSTS)
    assert r.false_positives == ["M1"]


def test_evaluate_found_exact(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 70, 150, "nodule")]), repo)
    res = {o.target: o.result for o in ev.outcomes}
    assert res == {"F1": "found", "M1": "true_positive"}
    assert ev.score == 100 and ev.success


def test_evaluate_related_label_partial_credit(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 70, 150, "mass")]), repo)
    o = {o.target: o for o in ev.outcomes}
    assert o["F1"].result == "mislabeled" and o["F1"].learner_label == "mass"
    w = config.scoring()["score_weights"]["abnormal"]
    expected = w["localization"] + w["label"] * (1 - COSTS["related"]) + w["pattern"]
    assert ev.score == round(expected, 1)
    assert ev.success  # localized, no FP


def test_evaluate_duplicate_no_penalty(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 70, 150, "nodule"), mark("M2", 72, 151, "nodule")]), repo)
    res = {o.target: o.result for o in ev.outcomes}
    assert res["M2"] == "duplicate" and ev.score == 100


def test_evaluate_fp_and_missed(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 185, 150, "nodule")]), repo)
    res = {o.target: o for o in ev.outcomes}
    assert res["F1"].result == "missed_search"
    assert res["M1"].result == "false_positive" and res["M1"].zone == "left_mid_zone"
    w = config.scoring()["score_weights"]["abnormal"]
    assert ev.score == max(0, w["pattern"] + w["false_positive"])
    assert not ev.success
    # arrow from the wrong mark to the missed finding, other-lung relation
    assert ev.reveal.arrows[0].from_mark == "M1" and "other lung" in ev.reveal.arrows[0].text
    assert "cm" not in ev.reveal.arrows[0].text


def test_two_findings_bilateral(repo):
    case = repo.get("syn_006")  # bilateral effusion
    ev = evaluate(case, make_submit([mark("M1", 55, 215, "effusion")]), repo)
    res = {o.target: o.result for o in ev.outcomes}
    assert res["F1"] == "found" and res["F2"].startswith("missed_")
    assert ev.score == 35 + 10 + 10 and not ev.success  # 70·½ + 20·½ + 10


def test_pattern_only_case(repo):
    case = repo.get("syn_007")
    ev = evaluate(case, make_submit(patterns=[PatternSelection(label="cardiomegaly", confidence=4)]), repo)
    assert [o.result for o in ev.outcomes] == ["pattern_found"]
    assert ev.score == 100 and ev.success and ev.reveal.ctr == case.cardiothoracic_ratio
    ev2 = evaluate(case, make_submit(patterns=[PatternSelection(label="emphysema", confidence=2)]), repo)
    assert {o.result for o in ev2.outcomes} == {"pattern_missed", "pattern_false"}
    assert ev2.score == 0 and not ev2.success


def test_normal_case_scores(repo):
    case = repo.get("syn_008")
    ev = evaluate(case, make_submit(declared_normal=True, normal_confidence=4), repo)
    assert [o.result for o in ev.outcomes] == ["true_negative"] and ev.score == 100 and ev.success
    ev2 = evaluate(case, make_submit([mark("M1", 70, 150, "nodule")], hints=1), repo)
    n = config.scoring()["score_weights"]["normal"]
    assert ev2.score == n["base"] + n["false_positive"] + n["hint"]
    assert not ev2.success


def test_hints_cost_points(repo):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 70, 150, "nodule")], hints=2), repo)
    assert ev.score == 100 + 2 * config.scoring()["score_weights"]["abnormal"]["hint"]


def test_success_allows_one_fp():
    outs = [Outcome(target="F1", result="found"), Outcome(target="M2", result="false_positive")]
    p = parts(outs, 1.0, 0)
    assert case_success(p, False, config.scoring())
    outs.append(Outcome(target="M3", result="false_positive"))
    assert not case_success(parts(outs, 1.0, 0), False, config.scoring())
    assert case_score(parts(outs, 1.0, 0), False, config.scoring()) == 80


def test_score_floor_zero():
    outs = [Outcome(target="F1", result="missed_search")] + [
        Outcome(target=f"M{i}", result="false_positive") for i in range(5)
    ]
    assert case_score(parts(outs, 0.0, 3), False, config.scoring()) == 0
