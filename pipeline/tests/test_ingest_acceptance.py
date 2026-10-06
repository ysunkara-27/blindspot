"""SPEC §15.2 M1 acceptance checks against the REAL processed data. Skipped when data/processed is absent
(fresh clone / CI). Every mask is pixel-checked only with BLINDSPOT_FULL_DATA_CHECK=1 (≈ 30 s); otherwise a
seeded sample of 300 masks is checked."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline import splits as sp
from shared.contracts import Case

PROC = Path(os.environ.get("BLINDSPOT_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "processed"
pytestmark = pytest.mark.skipif(not (PROC / "cases.jsonl").exists(), reason="no processed data (run make data)")


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    with (PROC / "cases.jsonl").open() as fh:
        return [Case.model_validate_json(line) for line in fh if line.strip()]  # 100% schema-valid or raises


def test_counts_and_normals(cases):
    stats = json.loads((PROC / "ingest_stats.json").read_text())
    if stats.get("limit"):
        pytest.skip("dev run with --limit")
    assert len(cases) >= 3000
    assert len({c.case_id for c in cases}) == len(cases)
    normals = sum(c.is_normal for c in cases)
    assert normals == stats["normals"] > 0
    assert all((c.is_normal and not c.findings) or (not c.is_normal and c.findings) for c in cases)


def test_polygon_fraction_and_ids(cases):
    inst = [f for c in cases for f in c.findings]
    assert sum(f.geometry.kind == "polygon" for f in inst) / len(inst) >= 0.90
    for c in cases:
        assert c.case_id.startswith("cxd_") and c.width == c.height == 1024 and c.pixel_spacing_mm is None
        assert [f.finding_id for f in c.findings] == [f"{c.case_id}#F{i}" for i in range(1, len(c.findings) + 1)]


def test_every_sym_mapped():
    rep = json.loads((PROC / "taxonomy_report.json").read_text())
    assert rep["unmapped"] == [] and set(rep["mapping"]) == set(rep["unique_syms"])


def test_masks_nonempty_and_inside_image(cases):
    inst = [f for c in cases for f in c.findings]
    if os.environ.get("BLINDSPOT_FULL_DATA_CHECK") != "1":
        inst = random.Random(0).sample(inst, min(300, len(inst)))
    for f in inst:
        x0, y0, x1, y1 = f.geometry.bbox
        assert 0 <= x0 < x1 <= 1024 and 0 <= y0 < y1 <= 1024, f.finding_id
        assert 0 < f.area_frac <= 1
        m = cv2.imread(str(PROC / f.geometry.mask_path), cv2.IMREAD_GRAYSCALE)
        assert m is not None and m.shape == (1024, 1024), f.finding_id
        ys, xs = np.nonzero(m)
        assert len(xs) > 0, f.finding_id
        assert (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)) == f.geometry.bbox


def test_splits_valid_if_built(cases):
    p = PROC / "splits.json"
    if not p.exists():
        pytest.skip("splits not built yet")
    splits = json.loads(p.read_text())["splits"]
    sp.validate_splits(splits, cases)
    where = {cid: n for n, ids in splits.items() for cid in ids}
    assert all(c.split == where[c.case_id] for c in cases)
    assert Counter(len(splits[f]) for f in ("assess_A", "assess_B")) == Counter({20: 2})
