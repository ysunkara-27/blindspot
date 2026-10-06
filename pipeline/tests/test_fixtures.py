import json
from pathlib import Path

import cv2

from shared.contracts import Case
from shared.rle import read_zones

ROOT = Path(__file__).resolve().parent / "fixtures" / "synthetic"


def test_synthetic_fixtures_validate():
    cases = [Case.model_validate_json(ln) for ln in (ROOT / "cases.jsonl").read_text().splitlines()]
    assert len(cases) == 10
    assert sum(c.is_normal for c in cases) == 3
    for c in cases:
        assert (ROOT / c.image_path).exists()
        masks, meta = read_zones(ROOT / c.zones_path)
        assert "lungs" in masks and "right_apex" in masks and "retrocardiac" in masks
        for f in c.findings:
            m = cv2.imread(str(ROOT / f.geometry.mask_path), cv2.IMREAD_GRAYSCALE)
            assert m is not None and (m > 0).any()
            assert f.primary_zone is not None


def test_patient_right_is_image_left():
    cases = [json.loads(ln) for ln in (ROOT / "cases.jsonl").read_text().splitlines()]
    for c in cases:
        for f in c["findings"]:
            if f["side"] == "right":
                assert f["centroid"][0] < c["width"] / 2
            if f["side"] == "left":
                assert f["centroid"][0] > c["width"] / 2
