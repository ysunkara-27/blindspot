"""M2 acceptance on the REAL data (SPEC §15.2). Skipped unless BLINDSPOT_FULL_DATA_CHECK=1 and M2 outputs exist."""

from __future__ import annotations

import json
import os
import re

import numpy as np
import pytest

from pipeline.anatomy import common as C

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINDSPOT_FULL_DATA_CHECK") != "1" or not (C.processed_dir() / "anatomy").exists(),
    reason="set BLINDSPOT_FULL_DATA_CHECK=1 after `make anatomy features` to check the real data",
)
BANNED = re.compile(r"\bcm\b|centimet|\bmm\b|millimet|\blobe\b|\brib\b", re.I)


@pytest.fixture(scope="module")
def cases():
    from shared.contracts import Case

    raw = C.read_cases()
    for d in raw:
        Case.model_validate(d)
    return [d for d in raw if d["split"] in C.IN_SCOPE_SPLITS]


def test_anatomy_coverage_at_least_95pct(cases):
    have = sum((C.processed_dir() / C.anatomy_rel(c["case_id"])).exists() for c in cases)
    assert have / len(cases) >= 0.95


def test_orientation_report(cases):
    rep = json.loads((C.qa_dir() / "orientation_report.json").read_text())
    assert rep["decision"] in ("keep", "swap")
    assert rep["heart_on_image_right_frac_non_flagged"] >= 0.90


def test_every_focal_finding_located_and_featured(cases):
    for c in cases:
        assert c["zones_path"] and (C.processed_dir() / c["zones_path"]).exists()
        for f in c["findings"]:
            if f["kind"] != "focal":
                continue
            assert f["side"] in ("right", "left", "bilateral", "midline"), f["finding_id"]
            assert f["zones"] and f["primary_zone"] == f["zones"][0], f["finding_id"]
            assert f["relative_location"] and not BANNED.search(f["relative_location"]), f["finding_id"]
            assert f["contrast"] is not None and f["edge_dist"] is not None, f["finding_id"]
            assert f["difficulty"] is not None and -2.5 <= f["difficulty"] <= 2.5
            if f["label"] in C.TXV_CLASSIFIER_MAP and c.get("anatomy_path"):
                assert f["model_prob"] is not None, f["finding_id"]


def test_every_finding_incl_pattern_has_side_and_primary_zone():
    """QA issue 9: every finding in cases.jsonl (all splits, focal AND pattern) is located."""
    lung_lead = {"right": "right lung", "left": "left lung", "bilateral": "both lungs", "midline": "central chest"}
    raw = C.read_cases()
    n_pattern = n_cm = n_cm_heart = 0
    for c in raw:
        for f in c["findings"]:
            fid = f["finding_id"]
            assert f["side"] in ("right", "left", "bilateral", "midline"), fid
            assert f["primary_zone"] and f["zones"] and f["primary_zone"] == f["zones"][0], fid
            assert len(f["zones"]) <= 3, fid
            rel = f["relative_location"]
            assert rel and not BANNED.search(rel), fid
            if f["kind"] != "pattern":
                continue
            n_pattern += 1
            assert "subdiaphragmatic" not in f["zones"], fid
            if f["label"] == "cardiomegaly":
                n_cm += 1
                n_cm_heart += f["primary_zone"] == "cardiac_silhouette"
                assert f["side"] == "midline", fid
                ctr = c["cardiothoracic_ratio"]
                want = "cardiac silhouette" if ctr is None else f"cardiac silhouette, enlarged (CTR {ctr:.2f},"
                assert rel.startswith(want), (fid, rel, ctr)
            else:
                assert rel.startswith(lung_lead[f["side"]] + ","), (fid, rel)
    assert n_pattern > 0 and n_cm > 0
    assert n_cm_heart / n_cm >= 0.99, (n_cm_heart, n_cm)


def test_case_b0_and_ctr(cases):
    seg_ok = [c for c in cases if c.get("anatomy_path") and "anatomy_failed" not in c["qa_flags"]]
    assert sum(c["cardiothoracic_ratio"] is not None for c in seg_ok) / len(seg_ok) >= 0.95
    for c in cases:
        if c["is_normal"]:
            assert c["difficulty_prior"] == 0.0
        focal = [f["difficulty"] for f in c["findings"] if f["kind"] == "focal"]
        if focal and not c["is_normal"]:
            assert c["difficulty_prior"] == max(focal)


def test_patient_side_matches_midline(cases):
    from shared.rle import read_zones

    rng = np.random.default_rng(0)
    sample = [cases[i] for i in rng.choice(len(cases), size=min(150, len(cases)), replace=False)]
    for c in sample:
        _, meta = read_zones(C.processed_dir() / c["zones_path"])
        for f in c["findings"]:
            if f["kind"] == "focal" and f["side"] == "right":
                assert f["centroid"][0] < meta["midline_x"] + 0.1 * c["width"], f["finding_id"]
            if f["kind"] == "focal" and f["side"] == "left":
                assert f["centroid"][0] > meta["midline_x"] - 0.1 * c["width"], f["finding_id"]
            if f["kind"] == "focal" and f["primary_zone"].startswith("right_"):
                assert f["side"] != "left", f["finding_id"]


def test_twenty_overlays():
    assert len(list(C.qa_dir().glob("anatomy_cxd_*.png"))) >= 20
