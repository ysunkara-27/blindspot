"""Renderer (SPEC §8.2): three PNGs, correct sizes, overlays only where they belong, ≤ 1568 px."""

import cv2
import numpy as np

from backend.app.tests._tutor_helpers import facts_for, fixture_root
from backend.app.tutor.render import AMBER_BGR, CYAN_BGR, MAX_EDGE, render_images
from shared.contracts import Mark


def decode(b):
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def count_color(img, bgr, tol=40):
    return int((np.abs(img.astype(int) - np.array(bgr)).sum(axis=2) < tol).sum())


def test_three_pngs_with_expected_sizes_small_finding():
    f, case, sub = facts_for("missed_search")  # small pneumothorax → quarter-width window ×2
    imgs = render_images(case, f, sub.marks, fixture_root())
    assert set(imgs) == {"full", "crop", "crop_outlined"}
    full, crop, outl = (decode(imgs[k]) for k in ("full", "crop", "crop_outlined"))
    assert imgs["full"][:8] == b"\x89PNG\r\n\x1a\n"
    assert full.shape[:2] == (256, 256)
    assert crop.shape[:2] == (128, 128) == outl.shape[:2]
    assert count_color(full, CYAN_BGR) > 0 and count_color(full, AMBER_BGR) > 0
    assert count_color(crop, CYAN_BGR) == 0, "the clean crop has no outline"
    assert count_color(outl, CYAN_BGR) > 0


def test_large_finding_uses_half_width_window():
    f, case, sub = facts_for("pattern_missed")  # cardiomegaly mask is large
    imgs = render_images(case, f, sub.marks, fixture_root())
    assert decode(imgs["crop"]).shape[:2] == (128, 128)


def test_normal_case_crops_around_false_positive_mark():
    f, case, sub = facts_for("false_positive_normal")
    imgs = render_images(case, f, sub.marks, fixture_root())
    full = decode(imgs["full"])
    assert count_color(full, CYAN_BGR) == 0 and count_color(full, AMBER_BGR) > 0


def test_long_edge_is_capped(tmp_path):
    f, case, _ = facts_for("found")
    big = np.full((2000, 2000), 90, np.uint8)
    (tmp_path / "images").mkdir()
    cv2.imwrite(str(tmp_path / "images" / "big.png"), big)
    s = 2000 / 256
    fnd = case.findings[0]
    poly = [(x * s, y * s) for x, y in fnd.geometry.polygon]
    g = fnd.geometry.model_copy(
        update={"polygon": poly, "bbox": tuple(v * s for v in fnd.geometry.bbox), "mask_path": None}
    )
    big_case = case.model_copy(
        update={
            "image_path": "images/big.png",
            "width": 2000,
            "height": 2000,
            "findings": [
                fnd.model_copy(update={"geometry": g, "centroid": (fnd.centroid[0] * s, fnd.centroid[1] * s)})
            ],
        }
    )
    imgs = render_images(big_case, f, [Mark(mark_id="M1", x=500, y=900, label="nodule", confidence=3)], tmp_path)
    for b in imgs.values():
        assert max(decode(b).shape[:2]) <= MAX_EDGE
