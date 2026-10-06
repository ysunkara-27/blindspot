"""SPEC §7: dwell (exact algorithm), miss types on scripted telemetry, coverage, heatmap, spatial relations."""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from backend.app import config
from backend.app.engine import evaluate
from backend.app.search.coverage import lung_coverage_pct, review_coverage
from backend.app.search.dwell import dwell_in, dwell_ms, dwell_samples
from backend.app.search.heatmap import heatmap_png_b64
from backend.app.search.misstype import miss_type
from backend.app.search.spatial import direction_words, relation_text
from backend.app.tests.conftest import _ev, chain, hover, make_submit, mark, sweep

DW = config.scoring()["dwell"]
MT = config.scoring()["miss_types"]


def square(x0, y0, x1, y1, shape=(256, 256)):
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    return m


def test_dwell_counts_time_inside_region():
    region = square(100, 100, 120, 120)
    ev = hover(110, 110, 1000)
    d = dwell_ms(ev, region, DW)
    assert 900 <= d <= 1000


def test_dwell_caps_interval_and_skips_offimage():
    region = square(0, 0, 256, 256)
    ev = [_ev(0, 10, 10), _ev(5000, 12, 10), _ev(5100, None, None), _ev(9000, 20, 20), _ev(9033, 22, 20)]
    # 0→5000 capped at max_dt (250); 5000→5100 = 100 (next is off-image → "moved"); off-image interval skipped;
    # 9000→9033 = 33
    assert dwell_ms(ev, region, DW) == pytest.approx(DW["max_dt_ms"] + 100 + 33)


def test_dwell_idle_cap_for_stationary_pointer():
    region = square(0, 0, 256, 256)
    ev = [_ev(i * 100.0, 50, 50) for i in range(60)]  # 5.9 s perfectly still
    d = dwell_ms(ev, region, DW)
    assert d == pytest.approx(DW["max_still_ms"])  # only the first 1500 ms of stillness count


def test_dwell_zoomed_viewport_centre():
    region = square(100, 100, 140, 140)
    ev = [_ev(i * 33.0, 10 + (i % 2) * 3, 10, zoom=3.0, vp=(90, 90, 150, 150)) for i in range(31)]
    d = dwell_ms(ev, region, DW)
    assert d == pytest.approx(DW["zoom_dwell_weight"] * 33 * 30)


def test_vectorised_matches_literal():
    rng = np.random.default_rng(0)
    ev, t = [], 0.0
    for _ in range(800):
        t += float(rng.integers(5, 400))
        off = rng.random() < 0.05
        z = float(rng.choice([1.0, 2.5]))
        ev.append(
            _ev(
                t,
                None if off else float(rng.uniform(0, 256)),
                None if off else float(rng.uniform(0, 256)),
                zoom=z,
                vp=(60, 60, 160, 160),
            )
        )
    region = square(40, 80, 140, 200)
    assert dwell_in(dwell_samples(ev, DW), region) == pytest.approx(dwell_ms(ev, region, DW))


@pytest.mark.parametrize(
    "d,expected",
    [
        (0, "missed_search"),
        (299, "missed_search"),
        (300, "missed_recognition"),
        (999, "missed_recognition"),
        (1000, "missed_decision"),
        (5000, "missed_decision"),
    ],
)
def test_miss_type_thresholds(d, expected):
    assert miss_type(d, MT) == expected


# --- scripted behaviours on syn_001 (nodule at (70, 150), right mid zone); the learner marks the other lung
def _classify(repo, telemetry):
    case = repo.get("syn_001")
    ev = evaluate(case, make_submit([mark("M1", 185, 150, "nodule")], telemetry=telemetry), repo)
    o = next(o for o in ev.outcomes if o.target == "F1")
    return o.result, o.dwell_ms


def test_scripted_search_error(repo):
    res, d = _classify(repo, chain(hover(185, 150, 3000), hover(185, 60, 1000)))
    assert res == "missed_search" and d < MT["recognition_ms"]


def test_scripted_recognition_error(repo):
    # a sweep across the right lung that passes through the nodule ROI for ~500 ms
    res, d = _classify(repo, chain(hover(185, 150, 1500), sweep((30, 150), (115, 150), 1300)))
    assert res == "missed_recognition", d
    assert 300 <= d < 1000


def test_scripted_decision_error(repo):
    res, d = _classify(repo, chain(hover(185, 150, 1000), hover(70, 150, 2000)))
    assert res == "missed_decision" and d >= 1000


def test_coverage_visits_and_order(repo):
    zones, _ = repo.zones("syn_001")
    # right apex first, then retrocardiac; nothing else
    ry, rx = np.argwhere(zones["right_apex"]).mean(axis=0)
    cy, cx = np.argwhere(zones["retrocardiac"]).mean(axis=0)
    ev = chain(hover(rx, ry, 600), hover(cx, cy, 600), hover(rx, ry, 100))
    cov = review_coverage(dwell_samples(ev, DW), zones, config.review_area_ids(), DW["visit_ms"], config.zone_ids())
    assert {"right_apex", "retrocardiac"} <= set(cov.visited)
    assert "left_apex" in cov.unvisited and "right_apex" not in cov.unvisited
    assert cov.first_visits.index("right_apex") < cov.first_visits.index("retrocardiac")
    assert "lungs" not in cov.first_visits


def test_coverage_short_glance_not_visited(repo):
    zones, _ = repo.zones("syn_001")
    ry, rx = np.argwhere(zones["left_apex"]).mean(axis=0)
    cov = review_coverage(dwell_samples(hover(rx, ry, 200), DW), zones, config.review_area_ids(), DW["visit_ms"])
    assert "left_apex" in cov.unvisited


def test_lung_coverage_pct(repo):
    zones, _ = repo.zones("syn_001")
    rho = config.scoring()["roi"]["roi_frac"] * 256
    assert lung_coverage_pct(dwell_samples([], DW), zones["lungs"], rho) == 0
    # a raster over both lungs → near 100 %
    ev = []
    for y in range(35, 240, 12):
        ev += sweep((20, y), (236, y), 600)
    ev = chain(ev)
    pct = lung_coverage_pct(dwell_samples(ev, DW), zones["lungs"], rho)
    assert pct > 95
    half = chain(*[sweep((20, y), (120, y), 300) for y in range(35, 240, 12)])
    assert 35 < lung_coverage_pct(dwell_samples(half, DW), zones["lungs"], rho) < 65


def test_heatmap_png_256(repo):
    s = dwell_samples(chain(hover(70, 150, 1000)), DW)
    b64 = heatmap_png_b64(s, 256, 256, 9.0)
    img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape == (256, 256, 4)
    assert img[150, 70, 3] > 200 and img[20, 230, 3] == 0  # dense where the cursor dwelled


def test_heatmap_scales_from_1024():
    s = dwell_samples(chain(hover(800, 200, 500)), DW)
    img = cv2.imdecode(
        np.frombuffer(base64.b64decode(heatmap_png_b64(s, 1024, 1024, 36)), np.uint8), cv2.IMREAD_UNCHANGED
    )
    assert img.shape[:2] == (256, 256) and img[50, 200, 3] > 200


def test_direction_patient_side():
    box = (24, 35, 120, 235)
    # right lung (image left): target at smaller x is MORE LATERAL
    assert direction_words((100, 100), (40, 200), "right", box) == ["lower", "more lateral"]
    # left lung (image right): target at larger x is more lateral
    assert direction_words((150, 200), (220, 100), "left", (136, 35, 232, 235)) == ["higher", "more lateral"]


def test_relation_texts(repo):
    zones, _ = repo.zones("syn_001")
    t = relation_text("nodule", "right_lower_zone", "right", (55, 215), "left_mid_zone", (185, 150), zones)
    assert t.startswith("The nodule is in the other lung") and "left mid zone" in t and "right lower zone" in t
    t2 = relation_text("nodule", "right_lower_zone", "right", (40, 215), "right_mid_zone", (90, 150), zones)
    assert "one zone lower" in t2 and "more lateral" in t2
    t3 = relation_text("nodule", "right_upper_zone", "right", (70, 50), "right_lower_zone", (70, 210), zones)
    assert "two zones higher" in t3
    for s in (t, t2, t3):
        assert " cm" not in s and " mm" not in s
