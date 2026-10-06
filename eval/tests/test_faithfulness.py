"""Faithfulness eval: deterministic checks, the U-condition leak test, judge schema, end-to-end dry run."""

from __future__ import annotations

import json

import jsonschema
import numpy as np
import pytest

from eval import checks
from eval import faithfulness as fa
from eval.common import load_cases, resolve_source
from shared.contracts import DebriefFacts


@pytest.fixture(scope="module")
def scenario_facts():  # noqa: ANN201
    from eval import adapters, scenarios

    src = resolve_source("fixtures")
    cases = load_cases(src)
    repo = adapters.repo_for(src.root)
    cfg = adapters.cfg_scoring()
    case = next(c for c in cases if c.case_id == "syn_001")  # right-sided nodule
    sc = scenarios.build_scenario(case, repo, cfg, "wrong_side")
    res = adapters.score_attempt(case, sc.submit, repo, cfg)
    facts = adapters.build_facts(case, sc.submit, res)
    return src, case, sc, facts


def _out(facts: DebriefFacts, where: str = "right mid zone", extra: str = "") -> dict:
    res = {o.target: o.result for o in facts.outcomes}
    return {
        "headline": "Look again.",
        "verdict": "missed",
        "findings": [
            {
                "finding_id": f.id,
                "result": res[f.id],
                "where_to_look": where,
                "what_it_looks_like": ["A small round opacity."],
                "why": "You never looked there." + extra,
            }
            for f in facts.case.findings
        ],
        "overcalls": [
            {"mark_id": o.target, "explanation": "Nothing was there.", "possible_mimics": []}
            for o in facts.outcomes
            if o.result == "false_positive"
        ],
        "search_coaching": "Check both lungs.",
        "calibration_note": "",
        "next_step": "Next case.",
        "fact_ids": ["F1"],
    }


def test_checks_pass_a_correct_debrief(scenario_facts) -> None:  # noqa: ANN001
    *_, facts = scenario_facts
    r = checks.check_debrief(_out(facts), facts)
    assert r.ok, r.errors


def test_checks_catch_laterality_but_not_display_convention(scenario_facts) -> None:  # noqa: ANN001
    *_, facts = scenario_facts
    assert checks.check_debrief(_out(facts, where="left mid zone"), facts).laterality_errors
    conv = "right mid zone (the patient's right appears on the left of the image)"
    assert not checks.check_debrief(_out(facts, where=conv), facts).laterality_errors


def test_checks_catch_results_labels_banned_and_zones(scenario_facts) -> None:  # noqa: ANN001
    *_, facts = scenario_facts
    o = _out(facts)
    o["findings"][0]["result"] = "found"
    assert not checks.check_debrief(o, facts).results_ok
    r = checks.check_debrief(_out(facts, extra=" There is also a pneumothorax."), facts)
    assert "pneumothorax" in r.out_of_scope_labels
    r = checks.check_debrief(_out(facts, extra=" This needs a chest tube and is about 2 cm."), facts)
    assert r.management and r.banned.get("measurement")
    assert checks.check_debrief(_out(facts, where="right apex"), facts).zone_errors
    assert not checks.check_debrief(_out(facts, extra=" It can mimic a mass."), facts).out_of_scope_labels  # related
    assert not checks.check_debrief(None, facts).schema_ok


def test_u_condition_sees_no_location_or_outcome(scenario_facts) -> None:  # noqa: ANN001
    src, case, sc, facts = scenario_facts
    system, content = fa.u_request(facts, sc.submit, case, src.root)
    text = content[-1]["text"]
    info = json.loads(text.split("CASE INFO:\n", 1)[1])
    leaked = {
        "zones",
        "primary_zone",
        "side",
        "relative_location",
        "outcomes",
        "result",
        "dwell_ms",
        "search",
        "spatial_relations",
        "size",
        "difficulty",
    }
    keys = set()

    def walk(o):  # noqa: ANN001, ANN202
        if isinstance(o, dict):
            keys.update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(info)
    assert not keys & leaked
    f = facts.case.findings[0]
    for s in (f.primary_zone, f.relative_location, "missed_search", "false_positive"):
        assert s and s not in text
    # the U image has learner marks (amber) but no expert outline (cyan)
    import base64

    import cv2

    img = cv2.imdecode(np.frombuffer(base64.b64decode(content[0]["source"]["data"]), np.uint8), cv2.IMREAD_COLOR)
    cyan = (np.abs(img.astype(int) - np.array([221, 201, 53])).sum(axis=2) < 40).sum()
    amber = (np.abs(img.astype(int) - np.array([46, 169, 240])).sum(axis=2) < 40).sum()
    assert cyan == 0 and amber > 0
    assert "TEACHING CARDS" in system[1]["text"] and system[1]["cache_control"] == {"type": "ephemeral"}


def test_judge_schema_and_mock_judge(scenario_facts) -> None:  # noqa: ANN001
    *_, facts = scenario_facts
    jsonschema.Draft202012Validator.check_schema(fa.JUDGE_SCHEMA)
    out = fa.mock_judge({}, (facts, _out(facts, where="left mid zone")))
    jsonschema.validate(out, fa.JUDGE_SCHEMA)
    assert out["laterality_correct"] is False and out["grounded"] is False
    assert fa.mock_judge({}, (facts, _out(facts)))["grounded"] is True
    assert "FACTS" in fa.JUDGE_PROMPT_PATH.read_text()


def test_dry_run_end_to_end(fixture_args, tmp_path) -> None:  # noqa: ANN001
    args = fixture_args + ["--samples-dir", str(tmp_path / "samples"), "--limit", "21"]
    assert fa.main(args) == 0
    out = tmp_path / "reports"
    md = (out / "faithfulness.md").read_text()
    assert md.splitlines()[0].startswith(
        "# Debrief faithfulness and grounding ablation — DRY RUN — mock model outputs, synthetic fixtures"
    )
    assert (out / "faithfulness.png").exists()
    j = json.loads((out / "faithfulness.json").read_text())
    assert j["dry_run"] and j["n"] == 21 and j["engine_ok"] == 21 and j["spend_usd"] == 0.0
    q = [json.loads(line) for line in (tmp_path / "samples" / "review_queue.dryrun.jsonl").read_text().splitlines()]
    assert 0 < len(q) <= 20
    assert all(it["dry_run"] is True and it["condition"] == "G" for it in q)
    assert len({it["behaviour"] for it in q}) >= 3  # stratified
    assert not (tmp_path / "samples" / "review_queue.jsonl").exists()  # dry runs never overwrite the live queue
