"""Orientation check (SPEC §4.2) + anatomy npz IO on SYNTHETIC masks."""

from __future__ import annotations

import numpy as np

from pipeline.anatomy.common import TXV_TARGETS, clean_mask, load_anatomy, save_anatomy
from pipeline.anatomy.orientation import case_orientation, decide_global, swap_name
from pipeline.anatomy.synthetic import W, rect, synth_anatomy


def test_patient_side_names_pass():
    r = case_orientation(synth_anatomy(), W)
    assert r["right_lung_x"] < r["left_lung_x"]  # patient right lung on the image left
    assert r["lungs_ok"] and r["heart_ok"] and r["heart_image_right"] and not r["suspect"]


def test_image_side_names_are_suspect():
    r = case_orientation(synth_anatomy(swap=True), W)
    assert r["lungs_ok"] is False and r["suspect"]


def test_heart_on_image_left_is_suspect():
    a = synth_anatomy()
    a["Heart"] = rect(60, 160, 100, 200)
    r = case_orientation(a, W)
    assert r["heart_ok"] is False and r["suspect"]


def test_global_decision_80_percent_rule():
    assert decide_global([True] * 9 + [False])[0] == "keep"
    assert decide_global([False] * 9 + [True])[0] == "swap"
    assert decide_global([True] * 6 + [False] * 4)[0] == "undecided"
    assert decide_global([])[0] == "undecided"


def test_swap_name():
    assert swap_name("Left Lung") == "Right Lung"
    assert swap_name("Right Hilus Pulmonis") == "Left Hilus Pulmonis"
    assert swap_name("Heart") == "Heart"
    assert sorted(swap_name(t) for t in TXV_TARGETS) == sorted(TXV_TARGETS)


def test_npz_roundtrip_packbits(tmp_path):
    a = synth_anatomy()
    stack = np.stack([a.get(t, np.zeros_like(a["Heart"])) for t in TXV_TARGETS])
    p = tmp_path / "syn.npz"
    save_anatomy(p, stack, TXV_TARGETS, txv_probs=np.zeros(18, np.float32))
    masks, extras = load_anatomy(p, clean=False)
    assert list(masks) == list(TXV_TARGETS)
    for t in TXV_TARGETS:
        assert np.array_equal(masks[t], stack[TXV_TARGETS.index(t)])
    assert extras["txv_probs"].shape == (18,)
    with np.load(p) as z:
        assert tuple(z["shape"]) == stack.shape and z["masks"].dtype == np.uint8


def test_clean_mask_removes_specks():
    m = rect(10, 10, 60, 60) | rect(200, 200, 202, 202)
    assert not clean_mask(m, keep_largest_only=True)[201, 201]
    assert not clean_mask(m, keep_largest_only=False)[201, 201]
    two = rect(10, 10, 60, 60) | rect(100, 10, 140, 60)  # two comparable parts (e.g. diaphragm domes)
    assert clean_mask(two, keep_largest_only=False)[30, 120]
