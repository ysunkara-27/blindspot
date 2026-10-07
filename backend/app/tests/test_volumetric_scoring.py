"""Volumetric (CT / MR) hit test, cross-label rule, matching outcomes and size verdicts on the synthetic fixtures.

Fixture geometry (pipeline/tests/fixtures/make_volumetric_fixtures.py): 16 × 64 × 64 voxels, spacing (3, 1.5, 1.5) mm,
so τ = 0.02 · 96 mm = 1.92 mm ≈ 1.28 in-plane voxels and the slice window is ±2 slices.
vol_001 pancreas sphere r 18 mm at (x30, y36, z8) with a tumour r 6 mm at (x24, y36, z8) (value 2, inside the organ);
vol_002 hepatic vessels + two liver tumours (both value 2); vol_003 brain tumour with three components, no organ;
vol_004 a normal slab (pancreas only).
"""

from __future__ import annotations

import pytest

from backend.app import config
from backend.app.engine import evaluate
from backend.app.scoring.volume import (
    hits_volume,
    mark_voxel,
    size_verdict,
    structure_at,
    tolerance_mm,
    tolerance_voxels,
)
from backend.app.tests.conftest import make_submit
from shared.contracts import Mark, Measurement

VC = config.scoring()["volumetric"]


def vmark(mid: str, voxel: tuple[float, float, float], label: str = "pancreatic_tumour", conf: int = 4, **kw) -> Mark:
    x, y, z = voxel
    return Mark(
        mark_id=mid, x=x, y=y, label=label, confidence=conf, plane="axial", slice=int(round(z)), voxel=voxel, **kw
    )


def outcomes_of(repo, case_id: str, marks, declared_normal=False, measurements=(), telemetry=None):
    case = repo.get(case_id)
    sub = make_submit(marks=marks, declared_normal=declared_normal, telemetry=telemetry)
    sub = sub.model_copy(update={"measurements": list(measurements)})
    ev = evaluate(case, sub, repo)
    return ev, {o.target: o for o in ev.outcomes}


# ------------------------------------------------------------------ tolerance + voxel helpers
def test_tolerance_is_two_percent_of_the_larger_inplane_fov_in_mm():
    assert tolerance_mm((16, 64, 64), (3.0, 1.5, 1.5), VC) == pytest.approx(1.92)
    sw, ty, tx = tolerance_voxels((16, 64, 64), (3.0, 1.5, 1.5), VC)
    assert sw == 2 and ty == pytest.approx(1.28) and tx == pytest.approx(1.28)
    _, ty, tx = tolerance_voxels((10, 100, 50), (1.0, 1.0, 2.0), VC)  # FOV 100 × 100 mm → τ 2 mm → 2 vox / 1 vox
    assert ty == pytest.approx(2.0) and tx == pytest.approx(1.0)


def test_mark_voxel_from_plane_and_slice_in_all_three_planes():
    assert mark_voxel(Mark(mark_id="M", x=10, y=20, label="not_sure", confidence=3, plane="axial", slice=5)) == (
        10,
        20,
        5,
    )
    assert mark_voxel(Mark(mark_id="M", x=10, y=7, label="not_sure", confidence=3, plane="coronal", slice=20)) == (
        10,
        20,
        7,
    )
    assert mark_voxel(Mark(mark_id="M", x=20, y=7, label="not_sure", confidence=3, plane="sagittal", slice=10)) == (
        10,
        20,
        7,
    )
    assert mark_voxel(Mark(mark_id="M", x=1, y=1, label="not_sure", confidence=3)) is None  # no slice: ungradable
    assert mark_voxel(Mark(mark_id="M", x=1, y=1, label="not_sure", confidence=3, voxel=(3, 4, 5))) == (3, 4, 5)


# ------------------------------------------------------------------ hit test
def test_hit_inside_the_finding_component(repo):
    mv = repo.maskvol("vol_001")
    fm = repo.finding_volmask("vol_001", "vol_001#F1")
    assert hits_volume((24, 36, 8), fm, mv, 2, 1.28, 1.28)
    assert (
        structure_at(mv, (24, 36, 8)) == 2 and structure_at(mv, (30, 36, 8)) == 1 and structure_at(mv, (2, 2, 0)) == 0
    )


def test_cross_label_rule_mark_inside_the_organ_next_to_the_tumour_is_never_rescued(repo):
    mv = repo.maskvol("vol_001")
    fm = repo.finding_volmask("vol_001", "vol_001#F1")
    assert mv[8, 36, 29] == 1 and fm[8, 36, 28]  # x=29 is pancreas, one voxel from the tumour edge (within τ)
    assert not hits_volume((29, 36, 8), fm, mv, 2, 1.28, 1.28)
    assert hits_volume((29, 36, 8), fm, mv, 2, 1.28, 1.28, cross_label_rescue=True)  # the config switch
    assert mv[12, 36, 24] == 1 and not hits_volume((24, 36, 12), fm, mv, 2, 1.28, 1.28)  # 4 slices off, in the organ


def test_tolerance_rescues_a_mark_in_unlabelled_tissue_within_tau(repo):
    mv = repo.maskvol("vol_003")  # brain: no organ labels, so the tissue around the tumour is unlabelled
    fm = repo.finding_volmask("vol_003", "vol_003#F1")
    assert fm[8, 28, 49] and not fm[8, 28, 50] and mv[8, 28, 50] == 0
    assert hits_volume((50, 28, 8), fm, mv, 2, 1.28, 1.28)  # 1 voxel (1.5 mm) from the edge: within τ 1.92 mm
    assert not hits_volume((52, 28, 8), fm, mv, 2, 1.28, 1.28)  # 3 voxels away: unmatched


def test_slice_window_rescues_within_two_slices_only(repo):
    mv = repo.maskvol("vol_003")
    fm = repo.finding_volmask("vol_003", "vol_003#F1")
    assert fm[12, 28, 40] and not fm[13].any()
    assert hits_volume((40, 28, 13), fm, mv, 2, 1.28, 1.28)
    assert hits_volume((40, 28, 14), fm, mv, 2, 1.28, 1.28)
    assert not hits_volume((40, 28, 15), fm, mv, 2, 1.28, 1.28)


@pytest.mark.parametrize(
    "mark",
    [
        Mark(mark_id="M1", x=40, y=28, label="brain_tumour", confidence=4, plane="axial", slice=8),
        Mark(mark_id="M1", x=40, y=8, label="brain_tumour", confidence=4, plane="coronal", slice=28),
        Mark(mark_id="M1", x=28, y=8, label="brain_tumour", confidence=4, plane="sagittal", slice=40),
    ],
)
def test_marks_in_all_three_planes_hit_the_brain_tumour(repo, mark):
    ev, outs = outcomes_of(repo, "vol_003", [mark])
    assert outs["F1"].result == "found" and outs["M1"].result == "true_positive"
    rm = ev.reveal.marks[0]
    assert rm.voxel == [40.0, 28.0, 8.0] and rm.plane == mark.plane and rm.slice == mark.slice


# ------------------------------------------------------------------ outcomes through the engine
def test_found_with_label_credit_and_unmatched_marks_do_not_penalise(repo):
    far = vmark("M2", (50, 10, 3), label="liver_tumour")  # unlabelled tissue, nowhere near anything
    ev, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8)), far])
    assert outs["F1"].result == "found" and outs["M1"].result == "true_positive" and outs["M1"].matched == "F1"
    assert outs["M2"].result == "unmatched" and outs["M2"].zone == "superior_slab"
    assert ev.score == 100.0 and ev.success  # unmatched: no false-positive deduction
    assert "false_positive" not in {o.result for o in ev.outcomes}
    assert [m.result for m in ev.reveal.marks] == ["true_positive", "unmatched"]


def test_mark_inside_the_organ_is_unmatched_and_the_tumour_is_missed(repo):
    ev, outs = outcomes_of(repo, "vol_001", [vmark("M1", (29, 36, 8))])
    assert outs["M1"].result == "unmatched" and outs["M1"].zone == "pancreas"
    assert outs["F1"].result == "missed_search"  # no telemetry: never on its slices
    assert ev.score == 0.0 and not ev.success
    (arrow,) = ev.reveal.arrows
    assert arrow.from_mark == "M1" and arrow.to_finding == "F1" and arrow.from_xy == (29.0, 36.0)
    assert "mm" not in arrow.text and "mm" not in (arrow.label or "")
    assert "on slices 7–11" in arrow.text  # 1-based in text (contract slice_range is [6, 10])
    far = vmark("M2", (50, 10, 3))
    ev2, _ = outcomes_of(repo, "vol_001", [far])
    assert "on slice 4;" in ev2.reveal.arrows[0].text and "5 slices lower" in ev2.reveal.arrows[0].label  # index 3


def test_mislabeled_and_related_credit_follow_the_xray_rules(repo):
    _, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8), label="liver_tumour")])
    assert outs["F1"].result == "mislabeled" and outs["F1"].learner_label == "liver_tumour"
    _, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8), label="not_sure")])
    assert outs["F1"].result == "mislabeled" and outs["F1"].learner_label == "not_sure"


def test_two_findings_sharing_a_label_value_are_separated_by_component(repo):
    marks = [
        vmark("M1", (18, 24, 5), label="liver_tumour"),
        vmark("M2", (22, 40, 11), label="liver_tumour"),
        vmark("M3", (19, 24, 5), label="liver_tumour"),  # second mark on the first tumour
        vmark("M4", (20, 30, 7), label="liver_tumour"),  # inside the hepatic vessels: unmatched (anatomy)
    ]
    ev, outs = outcomes_of(repo, "vol_002", marks)
    assert outs["F1"].result == "found" and outs["F1"].matched == "M1"
    assert outs["F2"].result == "found" and outs["F2"].matched == "M2"
    assert outs["M3"].result == "duplicate" and outs["M3"].matched == "F1"
    assert outs["M4"].result == "unmatched" and outs["M4"].zone == "hepatic_vessels"
    assert ev.score == 100.0 and ev.success


def test_normal_slab_mark_in_the_organ_is_unmatched_and_a_normal_call_is_true_negative(repo):
    ev, outs = outcomes_of(repo, "vol_004", [vmark("M1", (30, 36, 8))])
    assert outs["M1"].result == "unmatched" and outs["M1"].zone == "pancreas"
    assert "case" not in outs and ev.score == 100.0  # no penalty: the reference labels no lesion
    ev, outs = outcomes_of(repo, "vol_004", [], declared_normal=True)
    assert outs["case"].result == "true_negative" and ev.score == 100.0 and ev.success
    assert ev.facts_card.headline == "Correct: this scan is normal"


def test_mark_without_voxel_or_slice_is_unmatched_not_an_error(repo):
    _, outs = outcomes_of(repo, "vol_001", [Mark(mark_id="M1", x=24, y=36, label="pancreatic_tumour", confidence=4)])
    assert outs["M1"].result == "unmatched" and outs["F1"].result == "missed_search"


# ------------------------------------------------------------------ size verdicts
@pytest.mark.parametrize(
    "your, ref, ok, diff, pct",
    [
        (12.0, 13.5, True, -1.5, 11.1),  # within 3 mm (20 % of 13.5 is 2.7 → the 3 mm floor applies)
        (16.5, 13.5, True, 3.0, 22.2),  # exactly 3 mm
        (17.0, 13.5, False, 3.5, 25.9),
        (35.0, 30.0, True, 5.0, 16.7),  # 20 % of 30 = 6 mm beats the 3 mm floor
        (37.0, 30.0, False, 7.0, 23.3),
        (30.0, 30.0, True, 0.0, 0.0),
    ],
)
def test_size_verdict_max_of_3mm_or_20pct(your, ref, ok, diff, pct):
    v = size_verdict(your, ref, VC)
    assert v.ok is ok and v.diff_mm == diff and v.diff_pct == pct and v.your_mm == your and v.reference_mm == ref


def test_size_verdict_on_a_matched_mass_like_finding_and_non_axial_flag(repo):
    meas = [Measurement(mark_id="M1", long_mm=12.0, plane="coronal", slice=36)]
    ev, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8))], measurements=meas)
    sv = outs["F1"].size_verdict
    assert sv == {
        "your_mm": 12.0,
        "reference_mm": 13.5,
        "diff_mm": -1.5,
        "diff_pct": 11.1,
        "ok": True,
        "plane": "coronal",
    }
    rf = ev.reveal.findings[0]
    assert rf.size_verdict is not None and rf.size_verdict.plane == "coronal" and rf.measure.long_mm == 13.5
    assert (
        "you measured 12 mm, reference 13.5 mm — within tolerance, measured on a coronal slice"
        in ev.facts_card.lines[0]
    )


def test_no_size_verdict_without_a_measurement_or_for_an_unmatched_mark(repo):
    _, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8))])
    assert outs["F1"].size_verdict is None
    meas = [Measurement(mark_id="M9", long_mm=12.0, plane="axial", slice=8)]
    _, outs = outcomes_of(repo, "vol_001", [vmark("M1", (24, 36, 8)), vmark("M9", (50, 10, 3))], measurements=meas)
    assert outs["F1"].size_verdict is None  # the measurement belongs to the unmatched mark


def test_reveal_carries_the_volumetric_finding_fields_and_no_heatmap(repo):
    ev, _ = outcomes_of(repo, "vol_003", [])
    f = ev.reveal.findings[0]
    assert f.slice_range == [4, 12] and f.centroid3 == [40.0, 28.0, 8.0] and f.label_values == [1, 2, 3]
    assert [c.name for c in f.components] == ["oedema", "tumour core", "enhancing tumour"]
    assert f.measure.slice in (7, 8) and f.measure.long_mm == 28.5  # fixture measure: widest axial slice
    assert ev.reveal.modality == "mr" and ev.reveal.provenance["badge"].startswith("Segmented by ")
    assert ev.reveal.search.heatmap_png_b64 is None and ev.reveal.search.slice_dwell == []
    assert ev.reveal.maskvol_url is None  # set by the service once the attempt id is known
