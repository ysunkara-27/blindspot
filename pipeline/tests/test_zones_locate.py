"""Finding locations + mark→finding relation on SYNTHETIC anatomy (SPEC §4.4)."""

from __future__ import annotations

import re

import numpy as np
import pytest

from pipeline.anatomy import locate_finding, spatial_relation, zone_at
from pipeline.anatomy.locate import choose_zones, finding_side, zone_overlaps
from pipeline.anatomy.synthetic import H, W, disk, rect, synth_anatomy
from pipeline.anatomy.zones import centroid, derive_zones

NO_CM = re.compile(r"\bcm\b|centimet|\bmm\b|millimet|\blobe\b|\brib\b", re.I)


@pytest.fixture(scope="module")
def zm():
    return derive_zones(synth_anatomy(), W, H)


def test_lower_zone_lateral_just_above_cp_angle(zm):
    zones, meta = zm
    m = disk(45, 181, 5)  # image-left → patient right; lower third; just above the CP angle rows (>=188)
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["side"] == "right"
    assert loc["primary_zone"] == "right_lower_zone"
    assert loc["zones"][0] == "right_lower_zone"
    assert loc["relative_location"] == "right lower zone, lateral third, just above the right costophrenic angle"


def test_extending_into_cp_angle(zm):
    zones, meta = zm
    m = rect(32, 175, 60, 200)
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["primary_zone"] == "right_lower_zone"
    assert "right_costophrenic_angle" in loc["zones"]
    assert "extending into the right costophrenic angle" in loc["relative_location"]


def test_left_side_mirror(zm):
    zones, meta = zm
    m = disk(210, 181, 5)  # image-right → patient left; lateral = large x
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["side"] == "left"
    assert loc["primary_zone"] == "left_lower_zone"
    assert loc["relative_location"].startswith("left lower zone, lateral third")


def test_apex_wins_tie_with_upper_zone(zm):
    zones, meta = zm
    m = disk(70, 52, 4)
    ov = zone_overlaps(m, zones)
    assert ov["right_apex"] == pytest.approx(1.0) and ov["right_upper_zone"] == pytest.approx(1.0)
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["primary_zone"] == "right_apex"
    assert loc["zones"] == ["right_apex", "right_upper_zone"]


def test_zones_threshold_sorted_max3(zm):
    zones, meta = zm
    m = rect(32, 150, 108, 219)  # big basal opacity
    ov = zone_overlaps(m, zones)
    zl, primary = choose_zones(ov, zones, centroid(m))
    assert 1 <= len(zl) <= 3 and zl[0] == primary
    assert all(ov[z] >= 0.15 for z in zl)
    assert [ov[z] for z in zl[1:]] == sorted([ov[z] for z in zl[1:]], reverse=True)


def test_bilateral_and_midline(zm):
    zones, meta = zm
    both = disk(60, 190, 8) | disk(200, 190, 8)
    assert locate_finding(both, zones, meta["midline_x"])["side"] == "bilateral"
    med = rect(118, 40, 137, 80)
    loc = locate_finding(med, zones, meta["midline_x"])
    assert loc["primary_zone"] == "mediastinum"
    assert loc["side"] == "midline"


def test_side_uses_midline_not_image_centre():
    m = rect(0, 0, 9, 9)
    assert finding_side(m, midline_x=5.0) in ("bilateral", "midline")
    assert finding_side(m, midline_x=100.0) == "right"
    assert finding_side(m, midline_x=-1.0) == "left"


def test_no_zone_falls_back_to_nearest(zm):
    zones, meta = zm
    m = disk(5, 250, 2)  # outside every zone
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["primary_zone"] is not None and loc["zones"] == [loc["primary_zone"]]


def test_retrocardiac_finding(zm):
    zones, meta = zm
    m = disk(150, 190, 5)  # behind the heart on the patient's left
    loc = locate_finding(m, zones, meta["midline_x"])
    assert loc["primary_zone"] == "retrocardiac"
    assert loc["side"] == "left"
    assert loc["relative_location"].startswith("retrocardiac region")


def test_no_centimetres_or_lobes_in_text(zm):
    zones, meta = zm
    rng = np.random.default_rng(0)
    for _ in range(40):
        cx, cy, r = int(rng.integers(20, 236)), int(rng.integers(20, 236)), int(rng.integers(2, 15))
        loc = locate_finding(disk(cx, cy, r), zones, meta["midline_x"])
        assert loc["relative_location"] and not NO_CM.search(loc["relative_location"])


def test_zone_at_points(zm):
    zones, _ = zm
    assert zone_at(70, 50, zones) == "right_apex"  # image-left top → patient right apex
    assert zone_at(80, 120, zones) == "right_mid_zone"
    assert zone_at(200, 120, zones) == "left_mid_zone"
    assert zone_at(2, 2, zones) is None
    assert zone_at(2, 2, zones, nearest=True) is not None


def test_spatial_relation_other_lung(zm):
    zones, meta = zm
    f = {"centroid": (45.0, 181.0), "side": "right", "primary_zone": "right_lower_zone", "label": "nodule"}
    r = spatial_relation((200, 120), f, zones, meta["midline_x"])
    assert r["same_side"] is False
    assert r["text"] == (
        "The nodule is in the other lung: your mark was in the left mid zone; the nodule is in the right lower zone."
    )


def test_spatial_relation_same_lung_steps_and_direction(zm):
    from shared.contracts import Finding, Geometry

    zones, meta = zm
    f = Finding(
        finding_id="syn_x#F1",
        label="nodule",
        source_label="Nodule",
        kind="focal",
        geometry=Geometry(kind="bbox", bbox=(40, 176, 51, 187)),
        centroid=(45.0, 181.0),
        area_frac=0.001,
        side="right",
        primary_zone="right_lower_zone",
    )
    r = spatial_relation((80, 120), f, zones, meta["midline_x"])
    assert r["same_side"] is True and r["zone_steps"] == 1
    assert r["direction"] == "lower and more lateral"
    assert r["dy_lung_heights"] == pytest.approx(61 / 180, abs=0.01)
    assert r["dlat_lung_widths"] == pytest.approx(35 / 80, abs=0.01)
    assert r["text"] == (
        "Same lung: your mark was in the right mid zone; the nodule is one zone lower, in the right lower zone "
        "(about 0.3 lung-heights lower and 0.4 lung-widths more lateral)."
    )
    assert not NO_CM.search(r["text"])


def test_spatial_relation_left_lung_lateral_is_larger_x(zm):
    zones, meta = zm
    f = {"centroid": (215.0, 120.0), "side": "left", "primary_zone": "left_mid_zone", "label": "mass"}
    r = spatial_relation((170, 120), f, zones, meta["midline_x"])
    assert r["direction"] == "more lateral" and r["zone_steps"] == 0


def test_effusion_below_segmented_lung_is_not_subdiaphragmatic(zm):
    zones, meta = zm
    m = rect(35, 214, 70, 238)  # mostly in the band below the lung base (TXV lung stops at the fluid)
    eff = locate_finding(m, zones, meta["midline_x"], "effusion")
    assert eff["primary_zone"] == "right_costophrenic_angle"
    assert "subdiaphragmatic" not in eff["zones"]
    assert "below the diaphragm" not in eff["relative_location"]
    nod = locate_finding(m, zones, meta["midline_x"], "nodule")  # a nodule there is behind the dome
    assert nod["primary_zone"] == "subdiaphragmatic"


def test_intrathoracic_label_fully_below_lung_falls_back_to_nearest_non_band_zone(zm):
    zones, meta = zm
    m = rect(40, 225, 60, 235)  # entirely inside the band
    loc = locate_finding(m, zones, meta["midline_x"], "pleural_thickening")
    assert loc["primary_zone"] != "subdiaphragmatic" and loc["primary_zone"].startswith("right_")


def test_spatial_relation_mark_outside_lungs_says_side_not_lung(zm):
    zones, meta = zm
    f = {"centroid": (45.0, 181.0), "side": "right", "primary_zone": "right_lower_zone", "label": "nodule"}
    r = spatial_relation((10, 10), f, zones, meta["midline_x"])
    assert r["text"].startswith("Same side: your mark was in an area outside the lung fields")
    r2 = spatial_relation((240, 10), f, zones, meta["midline_x"])
    assert r2["text"].startswith("The nodule is on the other side:")
