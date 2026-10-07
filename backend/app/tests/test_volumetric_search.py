"""Volumetric search analysis: slice dwell from scripted telemetry, miss types, coverage, hints (synthetic fixtures).

vol_001: pancreatic tumour on axial slices 6–10 (measure slice 8), centroid (x24, y36); pancreas r 18 mm around (30, 36)
on slices 2–14; review areas for the abdomen = pancreas, liver (absent here → dropped), the three slab thirds.
"""

from __future__ import annotations

import pytest

from backend.app import config, hints_volume, tutor_bridge
from backend.app.engine import evaluate
from backend.app.search.volume import (
    coverage,
    finding_slice_ms,
    miss_type_volume,
    near_ms,
    slice_trace,
    slices_viewed_pct,
)
from backend.app.tests.conftest import make_submit
from shared.contracts import Mark, TelemetryEvent

SC = config.scoring()
VC = SC["volumetric"]
VOL_SHAPE = (16, 64, 64)
SPACING = (3.0, 1.5, 1.5)


def ev(t: float, slice_: int | None, x: float | None = 5.0, y: float | None = 5.0, plane: str = "axial", kind="move"):
    return TelemetryEvent(t=t, kind=kind, x=x, y=y, zoom=1.0, vp=(0, 0, 64, 64), loupe=False, plane=plane, slice=slice_)


def scroll(slices, ms_each: float, x=5.0, y=5.0, step: float = 50.0, t0: float = 0.0, plane="axial"):
    """Hover on each slice for `ms_each` (events every `step` ms), then move on."""
    out, t = [], t0
    for s in slices:
        n = max(1, int(ms_each / step))
        for k in range(n):
            out.append(ev(t, s, x + (k % 2) * 0.5, y, plane))
            t += step
    out.append(ev(t, slices[-1] if slices else None, x, y, plane))  # closing event
    return out


def box(repo, case_id="vol_001", fid="vol_001#F1"):
    from backend.app.search.volume import box_of

    c = repo.get(case_id)
    return box_of(repo.finding(c, fid), VOL_SHAPE)


# ------------------------------------------------------------------ slice dwell
def test_interval_goes_to_the_slice_on_screen_capped_at_250ms_and_gaps_over_5s_ignored():
    tr = slice_trace([ev(0, 3), ev(100, 3), ev(400, 4), ev(6400, 4), ev(6500, 5), ev(6600, 5)], SC["dwell"])
    assert tr.dwell == {("axial", 3): 100.0 + 250.0, ("axial", 4): 100.0, ("axial", 5): 100.0}
    # 0→100 on slice 3; 100→400 on slice 3 (capped 250); 400→6400 is a 6 s gap (ignored); 6400→6500 slice 4


def test_events_without_a_slice_or_with_a_bad_plane_are_skipped():
    bad = {"t": 100, "x": 5, "y": 5, "plane": "oblique", "slice": 2}  # the engine also accepts raw dicts
    tr = slice_trace([ev(0, None), ev(50, 2), bad, ev(150, 2)], SC["dwell"])
    assert tr.dwell == {("axial", 2): 50.0}


def test_finding_slices_in_each_plane(repo):
    b = box(repo)  # z 6..10, y 32..41, x 20..29
    assert b == (6, 11, 32, 41, 20, 29)
    tr = slice_trace(scroll([5, 6, 10, 11], 300), SC["dwell"])
    assert finding_slice_ms(tr, b) == 600.0  # slices 6 and 10 hold it; 5 and 11 do not
    tr = slice_trace(scroll([31, 32, 40, 41], 300, plane="coronal"), SC["dwell"])
    assert finding_slice_ms(tr, b) == 600.0
    tr = slice_trace(scroll([19, 20, 28, 29], 300, plane="sagittal"), SC["dwell"])
    assert finding_slice_ms(tr, b) == 600.0


def test_slices_viewed_pct_counts_axial_slices_seen_at_least_visit_ms():
    tr = slice_trace(scroll(list(range(8)), 300) + scroll([8, 9], 100, t0=10_000), SC["dwell"])
    assert slices_viewed_pct(tr, 16, VC["dwell"]["visit_ms"]) == 50.0


def test_cursor_near_uses_in_plane_distance_in_mm_on_finding_slices(repo):
    b = box(repo)
    near_mm = VC["dwell"]["near_mm"]
    on = slice_trace(scroll([8], 1000, x=24, y=36), SC["dwell"])
    assert near_ms(on, b, SPACING, near_mm) == pytest.approx(1000.0)
    off_plane = slice_trace(scroll([8], 1000, x=5, y=5), SC["dwell"])  # 22 mm away in-plane
    assert near_ms(off_plane, b, SPACING, near_mm) == 0.0
    edge = slice_trace(scroll([8], 1000, x=20 - 9, y=36), SC["dwell"])  # 9 voxels = 13.5 mm from the box edge
    assert near_ms(edge, b, SPACING, near_mm) == pytest.approx(1000.0)
    wrong_slice = slice_trace(scroll([2], 1000, x=24, y=36), SC["dwell"])
    assert near_ms(wrong_slice, b, SPACING, near_mm) == 0.0


# ------------------------------------------------------------------ miss types
@pytest.mark.parametrize(
    "slice_ms, near, want",
    [
        (0, 0, "missed_search"),
        (799, 799, "missed_search"),
        (800, 0, "missed_recognition"),
        (1999, 1999, "missed_recognition"),  # long enough to see, not to decide
        (2500, 0, "missed_recognition"),  # scrolled past, never put the cursor on it
        (2000, 50, "missed_decision"),
    ],
)
def test_miss_type_thresholds(slice_ms, near, want):
    assert miss_type_volume(slice_ms, near, VC["dwell"]) == want


def _missed(repo, telemetry):
    case = repo.get("vol_001")
    e = evaluate(case, make_submit(telemetry=telemetry), repo)
    o = {x.target: x for x in e.outcomes}["F1"]
    return e, o


def test_never_on_the_slices_is_missed_search(repo):
    e, o = _missed(repo, scroll([0, 1, 2, 3], 1000, x=24, y=36))
    assert o.result == "missed_search" and o.dwell_ms == 0.0 and o.slices_viewed is False
    assert e.reveal.search.finding_slices_viewed == {"F1": False}
    assert e.facts_card.lines[1] == "The slices holding F1 were never on screen long enough to see."
    assert "slices 7–11 of 16 (you viewed 0 of them): Never looked there (no time spent there)" in e.facts_card.lines[0]


def test_fast_scroll_through_the_slices_is_search_and_not_viewed_per_slice_rule(repo):
    # 100 ms on each of the 5 finding slices: 500 ms on screen (< 800 → search) and no slice reached 300 ms, so the
    # viewer's caption rule (finding_slices_viewed: some finding slice ≥ 300 ms) says "not viewed" as well
    e, o = _missed(repo, scroll([6, 7, 8, 9, 10], 100, x=24, y=36))
    assert o.result == "missed_search" and o.dwell_ms == 500.0 and o.slices_viewed is False
    assert e.facts_card.lines[1] == "The slices holding F1 were never on screen long enough to see."


def test_recognition_wording_says_on_screen_and_passed_over(repo):
    e, o = _missed(repo, scroll([7, 8], 600, x=24, y=36))  # 1.2 s on its slices, cursor over it, < 2 s
    assert o.result == "missed_recognition" and o.slices_viewed is True
    assert (
        e.facts_card.lines[1]
        == "The slices holding F1 were on screen for about 1.2 s; your cursor passed over it without stopping."
    )
    e, o = _missed(repo, scroll([6, 7, 8, 9, 10], 600, x=60, y=60))  # 3 s on its slices, cursor never near
    assert o.result == "missed_recognition"
    assert (
        e.facts_card.lines[1] == "The slices holding F1 were on screen for about 3.0 s; your cursor never came near it."
    )


def test_decision_wording_says_how_long_the_cursor_paused(repo):
    e, o = _missed(repo, scroll([6, 7, 8, 9, 10], 600, x=24, y=36))
    assert o.result == "missed_decision"
    assert (
        e.facts_card.lines[1]
        == "The slices holding F1 were on screen for about 3.0 s; you paused on it for about 3.0 s."
    )
    assert "long enough to see" not in " ".join(e.facts_card.lines)


def test_brief_on_the_slices_is_missed_search_then_recognition(repo):
    _, o = _missed(repo, scroll([7, 8], 300, x=24, y=36))
    assert o.result == "missed_search" and o.dwell_ms == 600.0 and o.slices_viewed is True
    _, o = _missed(repo, scroll([7, 8], 600, x=24, y=36))
    assert o.result == "missed_recognition" and o.dwell_ms == 1200.0


def test_long_with_cursor_near_is_missed_decision_but_far_is_recognition(repo):
    e, o = _missed(repo, scroll([6, 7, 8, 9, 10], 600, x=24, y=36))
    assert o.result == "missed_decision" and o.dwell_ms == 3000.0
    assert "you viewed all of them" in e.facts_card.lines[0] and "about 3.0 s there" in e.facts_card.lines[0]
    _, o = _missed(repo, scroll([6, 7, 8, 9, 10], 600, x=60, y=60))
    assert o.result == "missed_recognition"


# ------------------------------------------------------------------ coverage
def test_coverage_drops_absent_organs_and_tracks_thirds_and_organ_dwell(repo):
    zones = repo.volume_zones("vol_001")
    areas = config.volumetric_review_areas("abdomen")
    assert areas == ["pancreas", "liver", "superior_slab", "mid_slab", "inferior_slab"]
    tr = slice_trace(scroll(list(range(16)), 400, x=5, y=5), SC["dwell"])  # every slice, cursor in a corner
    cov = coverage(tr, zones, VOL_SHAPE, areas, VC["dwell"]["visit_ms"])
    assert cov.visited == ["superior_slab", "mid_slab", "inferior_slab"] and cov.unvisited == ["pancreas"]
    assert "liver" not in cov.unvisited  # this mask does not label a liver
    assert cov.first_visits[:3] == ["superior_slab", "mid_slab", "inferior_slab"]
    tr = slice_trace(scroll([8], 1000, x=34, y=36), SC["dwell"])  # cursor inside the pancreas on one slice
    cov = coverage(tr, zones, VOL_SHAPE, areas, VC["dwell"]["visit_ms"])
    assert cov.visited == ["pancreas", "mid_slab"] and cov.dwell_by_zone["pancreas"] == pytest.approx(1000.0)


def test_reveal_search_summary_and_slice_dwell_list(repo):
    case = repo.get("vol_001")
    e = evaluate(case, make_submit(telemetry=scroll([5, 6, 7], 400, x=24, y=36)), repo)
    s = e.reveal.search
    assert s.slices_viewed_pct == round(100 * 3 / 16, 1) and s.lung_coverage_pct == s.slices_viewed_pct
    assert [(d.plane, d.slice, d.has_finding, d.finding_ids) for d in s.slice_dwell] == [
        ("axial", 5, False, None),
        ("axial", 6, True, ["F1"]),
        ("axial", 7, True, ["F1"]),
    ]
    assert all(d.ms == 400.0 for d in s.slice_dwell)
    # cursor (24, 36) lies inside the pancreas on slices 5–7, all in the middle third (nz//3 = 5 → mid = 5..10)
    assert s.heatmap_png_b64 is None and s.unvisited_review_areas == ["superior_slab", "inferior_slab"]
    assert s.visited_review_areas == ["pancreas", "mid_slab"]
    assert e.search_json["dwell_by_finding"] == {"F1": 800.0} and e.search_json["tau_voxels"][0] == 2


def test_brain_review_areas_use_hemisphere_halves(repo):
    zones = repo.volume_zones("vol_003")
    assert {"brain_left", "brain_right", "brain_midline"} <= set(zones)
    assert zones["brain_right"][8, 28, 10] and zones["brain_left"][8, 28, 50]  # patient right = low x
    tr = slice_trace(scroll([8], 1000, x=50, y=28), SC["dwell"])
    cov = coverage(tr, zones, VOL_SHAPE, config.volumetric_review_areas("brain"), VC["dwell"]["visit_ms"])
    assert cov.visited == ["brain_left", "mid_slab"] and cov.unvisited == [
        "brain_right",
        "superior_slab",
        "inferior_slab",
    ]


# ------------------------------------------------------------------ hints (deterministic ladder)
def test_hint_data_and_fallback_ladder_on_an_abnormal_scan(repo):
    case = repo.get("vol_001")
    data = hints_volume.hint_data(case, [], scroll([8], 1000, x=5, y=5), repo)
    assert data["unvisited_review_areas"] == ["pancreas", "superior_slab", "inferior_slab"]
    assert data["hardest_unmarked"]["finding_id"] == "F1" and data["hardest_unmarked"]["side"] == "right"
    assert hints_volume.fallback_hint(1, case, data) == (
        "You haven't looked at the pancreas, the upper slices of the volume or the lower slices of the volume yet."
    )
    assert (
        hints_volume.fallback_hint(2, case, data)
        == "Look again at the patient's right side, in the middle slices of the volume."
    )
    h3 = hints_volume.fallback_hint(3, case, data)
    assert h3.startswith("In the middle slices of the volume, check for this sign: ") and "mm" not in h3
    # once the tumour is marked, H2 falls back to the least-dwelt review area (a search cue, not truth)
    marked = [Mark(mark_id="M1", x=24, y=36, label="pancreatic_tumour", confidence=4, plane="axial", slice=8)]
    data2 = hints_volume.hint_data(case, marked, scroll(list(range(16)), 400, x=34, y=36), repo)
    assert data2["hardest_unmarked"] is None and data2["unvisited_review_areas"] == []
    assert hints_volume.fallback_hint(1, case, data2) == hints_volume.H1_ALL
    assert hints_volume.fallback_hint(2, case, data2).startswith("Look again at the ")


def test_hint_wording_is_symmetric_for_a_normal_scan(repo):
    normal = repo.get("vol_004")
    tel = scroll([8], 1000, x=5, y=5)
    for level in (1, 2, 3):
        a = tutor_bridge.hint_volume(level, repo.get("vol_001"), [], tel, repo)
        n = tutor_bridge.hint_volume(level, normal, [], tel, repo)
        assert a.split(" ")[:2] == n.split(" ")[:2], (a, n)  # same template at every level
        assert "normal" not in n.lower() and "tumour" not in n.lower()
