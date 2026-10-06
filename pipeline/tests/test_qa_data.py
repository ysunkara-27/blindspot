"""QA independent M1/M2 acceptance on the REAL processed data (skipped when data/processed is absent).

Owner: qa-reviewer. Read-only. Does not import pipeline code, so it cannot share its bugs.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest

from shared.contracts import GROUND_TRUTH_KEYS, Case

ROOT = Path(__file__).resolve().parents[2] / "data" / "processed"
pytestmark = pytest.mark.skipif(not (ROOT / "cases.jsonl").exists(), reason="no data/processed")


@pytest.fixture(scope="module")
def raw() -> list[dict]:
    return [json.loads(x) for x in (ROOT / "cases.jsonl").read_text().splitlines()]


def test_cases_validate_and_counts(raw):
    cases = [Case.model_validate(r) for r in raw]  # 100% validate
    assert len(cases) >= 3000
    assert len({c.case_id for c in cases}) == len(cases)
    n_norm = sum(c.is_normal for c in cases)
    assert n_norm > 0 and n_norm < len(cases)
    assert all(c.is_normal == (len(c.findings) == 0) for c in cases)
    assert all(re.fullmatch(r"cxd_\d+", c.case_id) for c in cases)
    for c in cases:
        for i, f in enumerate(c.findings, 1):
            assert f.finding_id == f"{c.case_id}#F{i}", f.finding_id


def test_masks_nonempty_inside_image_and_bbox_matches(raw):
    n = poly = 0
    bad: list[str] = []
    full = os.environ.get("QA_FULL_DATA") == "1"  # all 9.6k masks take ~60 s; default is a 1-in-8 deterministic sample
    for k, r in enumerate(raw):
        if not full and k % 8:
            continue
        W, H = r["width"], r["height"]
        assert (W, H) == (1024, 1024) or max(W, H) == 1024, (r["case_id"], W, H)
        for f in r["findings"]:
            n += 1
            g = f["geometry"]
            if g["kind"] == "polygon":
                poly += 1
            m = cv2.imread(str(ROOT / g["mask_path"]), cv2.IMREAD_GRAYSCALE)
            if m is None or m.shape != (H, W) or not (m > 0).any():
                bad.append(f["finding_id"])
                continue
            ys, xs = np.nonzero(m)
            x0, y0, x1, y1 = g["bbox"]
            if not (x0 == xs.min() and y0 == ys.min() and x1 == xs.max() + 1 and y1 == ys.max() + 1):
                bad.append(f["finding_id"] + " bbox")
            if not (0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H):
                bad.append(f["finding_id"] + " bbox-range")
            cx, cy = f["centroid"]
            if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                bad.append(f["finding_id"] + " centroid")
            for px, py in g.get("polygon") or []:
                if not (-1 <= px <= W + 1 and -1 <= py <= H + 1):
                    bad.append(f["finding_id"] + " polygon-range")
                    break
    assert not bad, bad[:10]
    assert poly / n >= 0.9


def test_taxonomy_labels_and_kinds(raw):
    import yaml

    tax = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "taxonomy.yaml").read_text())
    kinds = {x["id"]: x["kind"] for x in tax["labels"]}
    c = Counter()
    for r in raw:
        for f in r["findings"]:
            assert f["label"] in kinds, f["label"]
            assert f["kind"] == kinds[f["label"]]
            c[f["label"]] += 1
    assert set(c) == set(kinds)  # all 13 labels present


def test_splits_disjoint_complete_and_forms(raw):
    sp = json.loads((ROOT / "splits.json").read_text())["splits"]
    by = {r["case_id"]: r for r in raw}
    seen: dict[str, str] = {}
    for name, ids in sp.items():
        for i in ids:
            assert i not in seen, (i, seen[i], name)
            seen[i] = name
            assert by[i]["split"] == name  # cases.jsonl agrees with splits.json
    assert set(seen) == set(by)
    for form in ("assess_A", "assess_B"):
        cs = [by[i] for i in sp[form]]
        assert len(cs) == 20 and sum(c["is_normal"] for c in cs) == 8
        assert not any(c["qa_flags"] for c in cs), [c["case_id"] for c in cs if c["qa_flags"]]
    assert not set(sp["assess_A"]) & set(sp["assess_B"])
    for name in ("assess_A", "assess_B", "bench"):
        assert all(by[i]["source_split"] == "test" for i in sp[name])  # no train/test leakage into held-out forms
    assert all(by[i]["source_split"] == "train" for i in sp["practice"] + sp["holdout"])
    # forms are comparable: same label mix
    mix = lambda f: Counter(by[i]["findings"][0]["label"] if by[i]["findings"] else "normal" for i in sp[f])  # noqa: E731
    assert sum(abs(mix("assess_A")[k] - mix("assess_B")[k]) for k in set(mix("assess_A")) | set(mix("assess_B"))) <= 6


def test_patient_side_and_zones_on_real_data(raw):
    ok = bad = unassigned = 0
    for r in raw:
        if "orientation_suspect" in r["qa_flags"]:
            continue
        for f in r["findings"]:
            if f["kind"] != "focal":
                continue
            if f.get("side") is None:
                unassigned += 1
                continue
            if f["side"] in ("right", "left"):
                want = "right" if f["centroid"][0] < r["width"] / 2 else "left"
                ok += f["side"] == want
                bad += f["side"] != want
                if f.get("primary_zone", "").split("_")[0] in ("right", "left"):
                    assert f["primary_zone"].startswith(f["side"] + "_"), f["finding_id"]
    assert bad / max(1, ok + bad) < 0.01, (ok, bad)
    # focal findings of every non-flagged case carry side + zones once M2 has run
    flagged = {r["case_id"] for r in raw if "anatomy_missing" in r["qa_flags"]}
    missing = [
        r["case_id"]
        for r in raw
        if r["case_id"] not in flagged
        for f in r["findings"]
        if f["kind"] == "focal" and not f.get("zones")
    ]
    assert not missing, missing[:5]


def test_anatomy_coverage_and_heart_side(raw):
    in_scope = [r for r in raw if r["split"] != "holdout"]
    have = [r for r in in_scope if r.get("anatomy_path") and (ROOT / r["anatomy_path"]).exists()]
    assert len(have) / len(in_scope) >= 0.95
    suspect = sum("orientation_suspect" in r["qa_flags"] for r in raw)
    assert suspect / len(raw) <= 0.05, suspect
    ctr_ok = sum(r.get("cardiothoracic_ratio") is not None for r in have)
    assert ctr_ok / len(have) >= 0.95
    b0 = [r["difficulty_prior"] for r in have]
    assert all(isinstance(x, int | float) for x in b0)


def test_no_ground_truth_keys_collide_with_client_models():
    """GROUND_TRUTH_KEYS must cover every sensitive field name of the Case model (guards the leak tests)."""
    case_keys = set(Case.model_fields) | {
        k for k in ("label", "polygon", "side", "zones", "primary_zone", "relative_location")
    }
    sensitive = {
        "findings",
        "is_normal",
        "difficulty_prior",
        "cardiothoracic_ratio",
        "anatomy_path",
        "zones_path",
        "qa_flags",
    }
    assert sensitive <= GROUND_TRUTH_KEYS
    assert sensitive <= case_keys
