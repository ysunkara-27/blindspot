"""Lesion features, CTR, difficulty prior on SYNTHETIC data (SPEC §4.5-4.6)."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.anatomy.common import TXV_CLASSIFIER_MAP
from pipeline.anatomy.synthetic import H, W, disk, ellipse, rect, synth_anatomy
from pipeline.anatomy.zones import derive_zones
from pipeline.features.ctr import cardiothoracic_ratio
from pipeline.features.difficulty import CLIP, b0, fit_z, raw_features
from pipeline.features.lesion import classifier_probs, edge_distance, ring_contrast


# --------------------------------------------------------------------------- contrast
def test_ring_contrast_known_value():
    rng = np.random.default_rng(0)
    img = rng.normal(100, 10, (H, W))
    m = disk(128, 128, 10)
    img[m] += 50
    c = ring_contrast(img, m)
    assert c == pytest.approx(5.0, rel=0.15)  # |150 - 100| / 10


def test_ring_contrast_invisible_lesion_is_low():
    rng = np.random.default_rng(1)
    img = rng.normal(100, 10, (H, W))
    assert ring_contrast(img, disk(128, 128, 10)) < 1.0


def test_ring_contrast_empty_mask():
    assert ring_contrast(np.zeros((H, W)), np.zeros((H, W), bool)) is None


# --------------------------------------------------------------------------- edge distance
def test_edge_distance_normalised_by_lung_width():
    zones, _ = derive_zones(synth_anatomy(), W, H)
    # right lung x 30..109 (width 80); centroid 10 px inside the lateral edge
    assert edge_distance((39.0, 130.0), zones, "right") == pytest.approx(10 / 80, abs=0.02)
    centre = edge_distance((70.0, 130.0), zones, "right")
    assert centre == pytest.approx(40 / 80, abs=0.03)


# --------------------------------------------------------------------------- classifier mapping
def test_classifier_probs_mapping_explicit_and_partial():
    names = ["Atelectasis", "Nodule", "Pleural_Thickening", "Lung Lesion"]
    ex = {"txv_probs": np.array([0.1, 0.7, 0.3, 0.9], np.float32), "txv_pathologies": np.array(names)}
    p = classifier_probs(ex)
    assert p == pytest.approx({"atelectasis": 0.1, "nodule": 0.7, "pleural_thickening": 0.3})
    assert "calcification" not in TXV_CLASSIFIER_MAP and "diffuse_nodule" not in TXV_CLASSIFIER_MAP
    assert classifier_probs({}) == {}


# --------------------------------------------------------------------------- CTR
def test_ctr_exact_on_synthetic():
    heart = rect(100, 150, 179, 200)  # 80 px wide
    rl, ll = rect(20, 40, 109, 220), rect(146, 40, 235, 220)  # outer edges 20..235 → 216 px
    assert cardiothoracic_ratio(heart, rl, ll) == pytest.approx(80 / 216)


def test_ctr_uses_rows_with_both_lungs_and_widest_heart_row():
    heart = ellipse(128, 170, 50, 30)  # max width 101
    rl, ll = rect(30, 40, 109, 219), rect(146, 60, 225, 219)
    rl[30:40, 0:120] = True  # extra width only where the left lung is absent: ignored
    assert cardiothoracic_ratio(heart, rl, ll) == pytest.approx(101 / 196, abs=0.01)


def test_ctr_missing_structures():
    z = np.zeros((H, W), bool)
    assert cardiothoracic_ratio(z, rect(20, 40, 109, 220), rect(146, 40, 235, 220)) is None
    assert cardiothoracic_ratio(rect(100, 150, 179, 200), z, rect(146, 40, 235, 220)) is None


# --------------------------------------------------------------------------- difficulty
def _case(findings):
    return {"findings": findings}


def _f(area, contrast=1.0, zone="right_mid_zone", p=0.5):
    return {"kind": "focal", "area_frac": area, "contrast": contrast, "primary_zone": zone, "model_prob": p}


def test_b0_monotone_in_size_contrast_zone_and_prob():
    fs = [
        _f(a, c, z, p)
        for a in (1e-4, 1e-3, 1e-2)
        for c in (0.5, 2.0)
        for z in ("right_mid_zone", "retrocardiac")
        for p in (0.2, 0.8)
    ]
    case = _case(fs)
    params = fit_z([raw_features(f, case) for f in fs])
    g = lambda **kw: b0(raw_features(_f(**{**{"area": 1e-3}, **kw}), case), params)  # noqa: E731
    assert g(area=1e-4) > g(area=1e-2)  # smaller = harder
    assert g(contrast=0.5) > g(contrast=2.0)  # fainter = harder
    assert g(zone="retrocardiac") > g(zone="right_mid_zone")  # harder zone
    assert g(p=0.2) > g(p=0.8)  # model less sure = harder


def test_b0_missing_features_contribute_zero_and_clip():
    case = _case([_f(1e-3)])
    params = {k: (0.0, 1.0) for k in ("neg_log_area", "neg_contrast", "hardness", "n_findings", "one_minus_p")}
    raw = {"neg_log_area": None, "neg_contrast": None, "hardness": None, "n_findings": None, "one_minus_p": None}
    assert b0(raw, params) == 0.0
    big = raw_features(_f(1e-7, contrast=-100.0, zone="retrocardiac", p=0.0), case)
    assert b0(big, params) == CLIP
    assert raw_features({**_f(1e-3), "model_prob": None}, case)["one_minus_p"] is None


def test_fit_z_handles_constant_and_missing():
    rows = [{"neg_log_area": 1.0, "neg_contrast": None, "hardness": 0.3, "n_findings": 2.0, "one_minus_p": None}] * 3
    p = fit_z(rows)
    assert p["neg_log_area"] == (1.0, 1.0)  # zero variance → sd 1
    assert p["one_minus_p"] == (0.0, 1.0)
