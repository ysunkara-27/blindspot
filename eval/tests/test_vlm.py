"""VLM localization: grid math, scoring, baselines, selection, and an end-to-end dry run (mocks, no API)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from eval import render
from eval import vlm_localization as vlm
from eval.common import load_cases, resolve_source
from eval.scenarios import distance_from


def test_grid_cells() -> None:
    assert render.cell_of(0, 0, 1024, 1024) == "A1"
    assert render.cell_of(1023, 1023, 1024, 1024) == "H8"
    assert render.cell_of(130, 260, 1024, 1024) == "B3"
    assert render.cell_bbox("B3", 1024, 1024) == (128, 256, 256, 384)
    for c in render.all_cells():
        x0, y0, x1, y1 = render.cell_bbox(c, 1024, 1024)
        assert render.cell_of((x0 + x1) / 2, (y0 + y1) / 2, 1024, 1024) == c
    assert len(render.all_cells()) == 64
    with pytest.raises(ValueError):
        render.cell_bbox("Z9", 1024, 1024)


def _repo():  # noqa: ANN202
    from eval import adapters

    return adapters.repo_for(resolve_source("fixtures").root)


def _geom(side: str = "right") -> vlm.CaseGeom:
    src = resolve_source("fixtures")
    case = next(c for c in load_cases(src) if c.case_id == "syn_001")
    from eval import adapters

    return vlm.geom(case, adapters.repo_for(src.root))


def test_score_point_hit_tau_cell_and_side() -> None:
    g = _geom()
    f = g.finding
    cx, cy = f.centroid
    s = vlm.score_point(g, cx, cy, render.cell_of(cx, cy, 256, 256), "right")
    assert s.point_hit == 1.0 and s.cell_hit == 1.0 and s.side_correct == 1.0 and s.point_side_correct == 1.0
    assert s.cell_consistent == 1.0 and s.dist_norm == pytest.approx(0.0, abs=1e-6)
    # just outside the mask but within τ (0.02·256 ≈ 5.1 px) still hits; 3τ away does not
    x0 = f.geometry.bbox[0]
    assert vlm.score_point(g, x0 - 3, cy, None, "right").point_hit == 1.0
    assert vlm.score_point(g, x0 - 15, cy, None, "right").point_hit == 0.0
    # image-left = patient right: stating "left" for this right-sided finding is a laterality error
    assert vlm.score_point(g, cx, cy, None, "left").side_correct == 0.0
    assert vlm.score_point(g, 2 * 128 - cx, cy, None, "right").point_side_correct == 0.0
    # off-image coordinates never hit
    assert vlm.score_point(g, -50, cy, None, "right").point_hit == 0.0


def test_invalid_answers_score_as_misses() -> None:
    from eval.llm import LLMResult

    g = _geom()
    bad = LLMResult(key="k", parsed=None, text=None, stop_reason="refusal", usage={}, model="m", error="refusal")
    s = vlm.score_vlm(g, bad)
    assert not s.valid and s.point_hit == 0.0 and s.side_correct == 0.0
    weird = LLMResult(
        key="k",
        parsed={"cell": "Q1", "x": 1, "y": 1, "patient_side": "left"},
        text="",
        stop_reason="",
        usage={},
        model="m",
    )
    assert not vlm.score_vlm(g, weird).valid


def test_selection_strict_and_single_label_on_fixtures() -> None:
    src = resolve_source("fixtures")
    cases = load_cases(src)
    strict = {c.case_id for c, _ in vlm.select_cases(cases, src, selection="strict")}
    assert strict == {"syn_001", "syn_002", "syn_003", "syn_004"}  # exactly one focal core finding
    single = {c.case_id for c, _ in vlm.select_cases(cases, src, selection="single-label")}
    assert "syn_006" in single and "syn_005" not in single  # 2× effusion qualifies; nodule+mass does not
    assert len(vlm.select_cases(cases, src, per_label=1, max_total=2, selection="strict")) == 2
    labeled = vlm.select_cases(cases, src, selection="labeled")
    assert ("syn_005" in {c.case_id for c, _ in labeled}) and len({c.case_id for c, _ in labeled}) == len(labeled)
    g = vlm.geom(next(c for c in cases if c.case_id == "syn_005"), _repo(), "nodule")
    assert [f.label for f in g.findings] == ["nodule"]  # only the asked-about label is scored


def test_baselines_deterministic() -> None:
    src = resolve_source("fixtures")
    cases = load_cases(src)
    pri, note = vlm.label_priors(cases, src)
    assert "fixture" in note
    assert pri["nodule"][2] == 2  # syn_001 + syn_005 nodules
    g = _geom()
    a = vlm.score_random_lungs(g, 100, seed=3)
    b = vlm.score_random_lungs(g, 100, seed=3)
    assert a.point_hit == b.point_hit and 0.0 <= a.point_hit <= 1.0
    assert a.side_correct is not None and 0.2 < a.side_correct < 0.8  # random lungs ≈ coin flip on side


def test_mask_distance_helper() -> None:
    m = np.zeros((20, 20), bool)
    m[10, 10] = True
    d = distance_from(m)
    assert d[10, 10] == 0 and d[10, 13] == pytest.approx(3, abs=0.1)


def test_dry_run_end_to_end(fixture_args, tmp_path) -> None:  # noqa: ANN001
    assert vlm.main(fixture_args) == 0
    out = tmp_path / "reports"
    md = (out / "vlm_localization.md").read_text()
    assert md.splitlines()[0].startswith(
        "# VLM localization benchmark — DRY RUN — mock model outputs, synthetic fixtures"
    )
    assert (out / "vlm_localization.png").exists()
    j = json.loads((out / "vlm_localization.json").read_text())
    assert j["dry_run"] is True and j["synthetic"] is True and j["n"] == 4
    assert j["spend_usd"] == 0.0
    assert not list((tmp_path / "reports").glob("*.jpg"))
    # resumable: a second run is served from the (mock) cache
    assert vlm.main(fixture_args) == 0
    assert any((tmp_path / "cache" / "vlm" / "mock").rglob("*.json"))


def test_live_mode_refuses_over_budget_before_any_call(tmp_path) -> None:  # noqa: ANN001
    args = ["--source", "fixtures", "--max-cost", "0.0", "--out-dir", str(tmp_path), "--cache-dir", str(tmp_path)]
    with pytest.raises(SystemExit) as e:
        vlm.main(args)
    assert "REFUSING" in str(e.value)
