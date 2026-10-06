"""Scripted behaviours produce the intended outcomes when run through the PRODUCTION scoring + search engines.

Fixtures are synthetic (256×256, labeled synthetic). If the backend engines are missing, these xfail with a reason.
"""

from __future__ import annotations

import importlib.util

import pytest

from eval import scenarios
from eval.common import load_cases, resolve_source

ENGINES = all(
    importlib.util.find_spec(m) is not None for m in ("backend.app.scoring.matching", "backend.app.search.dwell")
)
needs_engines = pytest.mark.xfail(not ENGINES, reason="backend scoring/search engines not available yet", strict=False)


@pytest.fixture(scope="module")
def env():  # noqa: ANN201
    from eval import adapters

    src = resolve_source("fixtures")
    cases = load_cases(src)
    repo = adapters.repo_for(src.root)
    return cases, repo, adapters.cfg_scoring()


@needs_engines
@pytest.mark.parametrize("behaviour", scenarios.BEHAVIOURS)
def test_behaviour_classified_as_intended(env, behaviour) -> None:  # noqa: ANN001
    from eval import adapters

    cases, repo, cfg = env
    built = [
        scenarios.build_scenario(c, repo, cfg, behaviour)
        for c in cases
        if (behaviour == "overcall_normal") == c.is_normal
    ]
    scs = [s for s in built if isinstance(s, scenarios.Scenario)]
    assert scs, f"no scenario could be built for {behaviour}"
    for sc in scs:
        case = next(c for c in cases if c.case_id == sc.case_id)
        res = adapters.score_attempt(case, sc.submit, repo, cfg)
        cmp = scenarios.compare(sc.intended, res.result_by_target())
        bad = {k: v[:2] for k, v in cmp.items() if not v[2]}
        assert not bad, f"{sc.scenario_id}: intended vs actual {bad} (dwell {res.dwell_by_finding})"


@needs_engines
def test_scripted_dwell_bands(env) -> None:  # noqa: ANN001
    """search → 0 ms, recognition ≈ 500 ms, decision ≈ 2,000 ms inside the target ROI."""
    from eval import adapters

    cases, repo, cfg = env
    case = next(c for c in cases if c.case_id == "syn_001")
    got = {}
    for b in ("missed_search", "missed_recognition", "missed_decision"):
        sc = scenarios.build_scenario(case, repo, cfg, b)
        got[b] = adapters.score_attempt(case, sc.submit, repo, cfg).dwell_by_finding["F1"]
    assert got["missed_search"] == 0
    assert 300 <= got["missed_recognition"] < 700
    assert 1500 <= got["missed_decision"] < 2500


def test_telemetry_contract_and_patient_side(env) -> None:  # noqa: ANN001
    cases, repo, cfg = env
    case = next(c for c in cases if c.case_id == "syn_001")  # nodule on the patient's RIGHT = image LEFT
    sc = scenarios.build_scenario(case, repo, cfg, "wrong_side")
    assert isinstance(sc, scenarios.Scenario)
    ts = [e.t for e in sc.submit.telemetry]
    assert ts == sorted(ts) and len(ts) < 20000
    assert all((e.x is None) == (e.y is None) for e in sc.submit.telemetry)
    mark = sc.submit.marks[0]
    assert mark.x > case.width / 2  # the wrong-side mark lands on the image right = patient left
    assert sc.intended == {"F1": "missed_search", "M1": "false_positive"}


def test_skips_are_reported(env) -> None:  # noqa: ANN001
    cases, repo, cfg = env
    syn006 = next(c for c in cases if c.case_id == "syn_006")  # bilateral effusions: mirror hits the other one
    r = scenarios.build_scenario(syn006, repo, cfg, "wrong_side")
    assert isinstance(r, scenarios.Skip) and "mirror" in r.reason
    normal = next(c for c in cases if c.is_normal)
    assert isinstance(scenarios.build_scenario(normal, repo, cfg, "missed_search"), scenarios.Skip)
