"""Pattern-finding locations (QA issue 9; SPEC §4.4) on SYNTHETIC fixtures and toy anatomy only.

Patient RIGHT is on the image LEFT: a lung pattern drawn at small x must come out as side "right".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipeline.anatomy import common as C
from pipeline.anatomy import locate_finding
from pipeline.anatomy.locate import (
    PATTERN_LABELS,
    PRIMARY_TIE,
    cardiomegaly_location,
    locate_pattern,
    lung_pattern_location,
    zone_overlaps,
)
from pipeline.anatomy.synthetic import H, W, rect, synth_anatomy
from pipeline.anatomy.zones import derive_zones
from shared.rle import read_zones

FIX = Path(__file__).resolve().parent / "fixtures" / "synthetic"
BANNED = re.compile(r"\bcm\b|centimet|\bmm\b|millimet|\blobes?\b|\bribs?\b|\d+(?:st|nd|rd|th)\b", re.I)


@pytest.fixture(scope="module")
def zm():
    return derive_zones(synth_anatomy(), W, H)


@pytest.fixture(scope="module")
def heart():
    return synth_anatomy()["Heart"]


def test_pattern_labels_match_contract():
    assert PATTERN_LABELS == {"cardiomegaly", "emphysema", "fibrosis", "diffuse_nodule"}


# --------------------------------------------------------------------------- fixture syn_007
def test_syn_007_cardiomegaly_fixture_is_midline_cardiac_silhouette():
    case = next(json.loads(ln) for ln in (FIX / "cases.jsonl").read_text().splitlines() if '"syn_007"' in ln)
    f = case["findings"][0]
    assert f["kind"] == "pattern" and f["label"] == "cardiomegaly"
    zones, meta = read_zones(FIX / case["zones_path"])
    mask = C.read_mask_png(f["geometry"]["mask_path"], FIX)
    loc = locate_finding(mask, zones, meta["midline_x"], f["label"], kind=f["kind"], ctr=case["cardiothoracic_ratio"])
    assert loc["side"] == "midline"
    assert loc["primary_zone"] == "cardiac_silhouette" and loc["zones"][0] == "cardiac_silhouette"
    assert 1 <= len(loc["zones"]) <= 3
    assert loc["relative_location"] == "cardiac silhouette, enlarged (CTR 0.62, measured automatically)"
    # agrees with the hand-built fixture where the fixture is specific
    assert loc["side"] == f["side"] and loc["primary_zone"] == f["primary_zone"]
    no_ctr = locate_finding(mask, zones, meta["midline_x"], "cardiomegaly")  # kind inferred from the label
    assert no_ctr["relative_location"] == "cardiac silhouette" and no_ctr["side"] == "midline"


# --------------------------------------------------------------------------- toy anatomy
def test_cardiomegaly_on_heart_mask(zm, heart):
    zones, meta = zm
    loc = locate_finding(heart, zones, meta["midline_x"], "cardiomegaly", ctr=0.581)
    assert loc["side"] == "midline"
    assert loc["primary_zone"] == "cardiac_silhouette"
    assert "subdiaphragmatic" not in loc["zones"]
    assert loc["relative_location"] == "cardiac silhouette, enlarged (CTR 0.58, measured automatically)"


def test_cardiomegaly_prefers_cardiac_silhouette_over_a_larger_lung_overlap(zm, heart):
    zones, meta = zm
    m = (heart & rect(0, 190, 255, 255)) | rect(146, 100, 225, 140)  # outline mostly over the patient-left mid zone
    ov = zone_overlaps(m, zones)
    assert ov["left_mid_zone"] > ov["cardiac_silhouette"] + PRIMARY_TIE >= 0.15 + PRIMARY_TIE
    loc = locate_finding(m, zones, meta["midline_x"], "cardiomegaly")
    assert loc["primary_zone"] == "cardiac_silhouette" and loc["zones"][0] == "cardiac_silhouette"
    assert loc["side"] == "midline"
    # the same mask as a lung pattern is located by plain argmax
    fib = locate_finding(m, zones, meta["midline_x"], "fibrosis")
    assert fib["primary_zone"] == "left_mid_zone" and fib["side"] == "left"


def test_bilateral_upper_zone_pattern(zm):
    zones, meta = zm
    m = rect(38, 75, 101, 99) | rect(154, 75, 217, 99)  # upper thirds of both lungs, clear of apex/periphery
    loc = locate_finding(m, zones, meta["midline_x"], "emphysema")
    assert loc["side"] == "bilateral"
    assert set(loc["zones"]) == {"right_upper_zone", "left_upper_zone"}
    assert loc["primary_zone"] == loc["zones"][0]
    assert loc["relative_location"] == "both lungs, mainly the upper zones"


def test_image_left_lung_pattern_is_patient_right_throughout(zm):
    zones, meta = zm
    m = rect(40, 75, 100, 212)  # image LEFT → patient RIGHT; spans all three thirds of that lung
    loc = locate_finding(m, zones, meta["midline_x"], "fibrosis")
    assert loc["side"] == "right"
    assert loc["primary_zone"] == "right_mid_zone"
    assert sorted(loc["zones"]) == ["right_lower_zone", "right_mid_zone", "right_upper_zone"]
    assert all(z.startswith("right_") for z in loc["zones"])
    assert loc["relative_location"] == "right lung, throughout the upper, mid and lower zones"


def test_left_lower_pattern_names_retrocardiac_and_heart(zm):
    zones, meta = zm
    m = rect(150, 165, 220, 215)  # image RIGHT → patient LEFT base, partly behind the heart
    loc = locate_finding(m, zones, meta["midline_x"], "diffuse_nodule")
    assert loc["side"] == "left" and loc["primary_zone"] == "left_lower_zone"
    assert loc["relative_location"] == (
        "left lung, mainly the lower zone, including the retrocardiac region (behind the heart), "
        "overlapping the cardiac silhouette"
    )


def test_lung_pattern_apex_is_included_without_repeating_the_side(zm):
    zones, meta = zm
    loc = locate_finding(rect(150, 40, 220, 90), zones, meta["midline_x"], "diffuse_nodule")
    assert loc["side"] == "left" and loc["primary_zone"] == "left_upper_zone"
    assert loc["relative_location"] == "left lung, mainly the upper zone, including the apex and periphery"


def test_patterns_never_below_the_diaphragm(zm):
    zones, meta = zm
    m = rect(40, 200, 100, 240)  # half of it lies in the band below the diaphragm
    assert zone_overlaps(m, zones)["subdiaphragmatic"] >= 0.15
    for label in sorted(PATTERN_LABELS):
        loc = locate_finding(m, zones, meta["midline_x"], label)
        assert "subdiaphragmatic" not in loc["zones"], label
        assert "diaphragm" not in (loc["relative_location"] or ""), label


def test_empty_mask_is_unlocated(zm):
    zones, meta = zm
    loc = locate_pattern(rect(0, 0, -1, -1), zones, meta["midline_x"], "emphysema")
    assert loc == {"side": None, "zones": [], "primary_zone": None, "relative_location": None}


# --------------------------------------------------------------------------- text templates (pure)
@pytest.mark.parametrize(
    ("side", "zones", "text"),
    [
        ("bilateral", ["right_upper_zone", "left_upper_zone"], "both lungs, mainly the upper zones"),
        ("bilateral", ["left_upper_zone", "right_upper_zone", "right_mid_zone"],
         "both lungs, mainly the upper zones and right mid zone"),
        ("right", ["right_mid_zone", "right_upper_zone", "right_lower_zone"],
         "right lung, throughout the upper, mid and lower zones"),
        ("right", ["right_mid_zone", "right_lower_zone", "right_hilum"],
         "right lung, mainly the mid and lower zones, including the hilum"),
        ("left", ["left_upper_zone", "left_apex", "left_clavicle"],
         "left lung, mainly the upper zone, including the apex, overlapping the left clavicle"),
        ("left", ["left_periphery"], "left lung, mainly the periphery"),
        ("right", ["right_lower_zone", "left_lower_zone"], "right lung, mainly the lower zone and left lower zone"),
        ("midline", ["mediastinum", "spine", "right_periphery"],
         "central chest, mainly over the mediastinum and spine, including the right lung periphery"),
    ],
)  # fmt: skip
def test_lung_pattern_text(side, zones, text):
    assert lung_pattern_location(side, zones) == text
    assert not BANNED.search(text)


def test_text_edge_cases():
    assert lung_pattern_location("right", []) is None
    assert lung_pattern_location(None, ["right_upper_zone"]) is None
    assert cardiomegaly_location(None) == "cardiac silhouette"
    assert cardiomegaly_location(0.6049) == "cardiac silhouette, enlarged (CTR 0.60, measured automatically)"


def test_no_units_lobes_or_ribs_in_any_pattern_text(zm, heart):
    zones, meta = zm
    masks = [heart, rect(40, 75, 100, 212), rect(150, 165, 220, 215), rect(38, 75, 217, 99), rect(118, 40, 137, 80)]
    for m in masks:
        for label in sorted(PATTERN_LABELS):
            rel = locate_finding(m, zones, meta["midline_x"], label, ctr=0.55)["relative_location"]
            assert rel and not BANNED.search(rel), (label, rel)
