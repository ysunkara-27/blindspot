"""Ingest unit tests on tiny fake ChestX-Det rows. No network, no real dataset."""

from __future__ import annotations

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from pipeline import ingest_chestxdet as ig
from shared.contracts import Case

TABLE = ig.load_taxonomy()
CHESTXDET_SYMS = [
    "Atelectasis", "Calcification", "Cardiomegaly", "Consolidation", "Diffuse Nodule", "Effusion", "Emphysema",
    "Fibrosis", "Fracture", "Mass", "Nodule", "Pleural Thickening", "Pneumothorax",
]  # fmt: skip


def png_bytes(arr: np.ndarray, mode: str = "L") -> bytes:
    im = Image.fromarray(arr)
    if mode != "L":
        im = im.convert(mode)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def make_row(
    annotation: dict, is_negative: bool = False, size: int = 1024, mode: str = "L", image_id: str = "1"
) -> dict:
    img = np.full((size, size), 90, np.uint8)
    img[size // 4 : size // 2, size // 4 : size // 2] = 200
    return {
        "image_id": image_id,
        "image": {"bytes": png_bytes(img, mode), "path": None},
        "annotation_json": json.dumps(annotation),
        "is_negative": is_negative,
        "split": "train",
    }


SQUARE = [[100, 100], [300, 100], [300, 300], [100, 300]]


# --------------------------------------------------------------------------- taxonomy / mapping
def test_taxonomy_maps_all_13_chestxdet_syms():
    m = ig.map_syms(CHESTXDET_SYMS, TABLE)
    assert len({v.label for v in m.values()}) == 13
    assert m["Pleural Thickening"].label == "pleural_thickening"
    assert m["Diffuse Nodule"].label == "diffuse_nodule"
    assert m["Cardiomegaly"].kind == "pattern"
    assert m["Pneumothorax"].kind == "focal"


def test_mapping_is_case_and_whitespace_insensitive():
    m = ig.map_syms(["  pleural   THICKENING ", "effusion", "DIFFUSE nodule"], TABLE)
    assert [m[k].label for k in ("  pleural   THICKENING ", "effusion", "DIFFUSE nodule")] == [
        "pleural_thickening",
        "effusion",
        "diffuse_nodule",
    ]


def test_unmapped_sym_fails_loudly_and_names_every_offender():
    with pytest.raises(ig.UnmappedLabelError) as e:
        ig.map_syms(["Effusion", "Infiltration", "Hernia"], TABLE)
    assert "Infiltration" in str(e.value) and "Hernia" in str(e.value)


def test_unmapped_sym_aborts_run_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(ig, "download", lambda raw_dir: [])
    monkeypatch.setattr(ig, "collect_syms", lambda shards, limit: __import__("collections").Counter({"Hernia": 1}))
    with pytest.raises(ig.UnmappedLabelError):
        ig.run(None, 1, False, out_dir=tmp_path, raw_dir=tmp_path)
    assert not (tmp_path / "cases.jsonl").exists()


# --------------------------------------------------------------------------- parsing
def test_parse_annotation_zips_instances():
    ann = {"syms": ["Effusion", "Nodule"], "boxes": [[1, 2, 3, 4], [5, 6, 7, 8]], "polygons": [SQUARE, SQUARE]}
    inst = ig.parse_annotation(json.dumps(ann))
    assert [i.sym for i in inst] == ["Effusion", "Nodule"]
    assert inst[1].box == (5.0, 6.0, 7.0, 8.0)
    assert inst[0].polygon[2] == (300.0, 300.0)


def test_parse_annotation_length_mismatch_raises():
    with pytest.raises(ValueError):
        ig.parse_annotation({"syms": ["Effusion"], "boxes": [], "polygons": []})


def test_parse_annotation_empty_is_no_instances():
    assert ig.parse_annotation({"syms": [], "boxes": [], "polygons": []}) == []


# --------------------------------------------------------------------------- rasterization
def test_rasterize_square_polygon_area_and_bbox():
    m = ig.rasterize_polygon([(10, 10), (29, 10), (29, 29), (10, 29)], 64, 64)
    assert m is not None and m.dtype == bool
    assert m.sum() == 20 * 20  # fillPoly includes boundary pixels
    assert ig.mask_bbox(m) == (10.0, 10.0, 30.0, 30.0)
    assert ig.mask_centroid(m) == pytest.approx((19.5, 19.5))


@pytest.mark.parametrize(
    "poly",
    [
        None,
        [],
        [(1, 1), (5, 5)],
        [(1, 1), (5, 5), (9, 9)],
        [(3, 3), (3, 3), (3, 3)],
        [(1, 1), (float("nan"), 2), (4, 4)],
    ],
)
def test_invalid_polygons_return_none(poly):
    assert ig.rasterize_polygon(poly, 32, 32) is None


def test_polygon_outside_image_is_clipped_and_flagged():
    raws = [ig.RawInstance("Effusion", (0, 0, 10, 10), [(-5, -5), (20, -5), (20, 20), (-5, 20)])]
    insts, ev = ig.build_instances(raws, ig.map_syms(["Effusion"], TABLE), 64, 64)
    assert insts[0].geom_kind == "polygon" and ig.FLAG_POLY_CLIPPED in insts[0].flags
    assert ev["polygon_clipped"] == 1
    assert ig.mask_bbox(insts[0].mask) == (0.0, 0.0, 21.0, 21.0)


def test_bbox_fallback_when_polygon_invalid():
    raws = [ig.RawInstance("Nodule", (10, 12, 20, 30), [(1, 1), (2, 2)])]
    insts, ev = ig.build_instances(raws, ig.map_syms(["Nodule"], TABLE), 64, 64)
    assert len(insts) == 1 and insts[0].geom_kind == "bbox" and insts[0].polygon is None
    assert ig.FLAG_MASK_FROM_BBOX in insts[0].flags and ev["mask_from_bbox"] == 1
    assert ig.mask_bbox(insts[0].mask) == (10.0, 12.0, 20.0, 30.0)


def test_instance_dropped_when_polygon_and_box_both_unusable():
    raws = [ig.RawInstance("Nodule", (10, 10, 10, 30), None)]
    insts, ev = ig.build_instances(raws, ig.map_syms(["Nodule"], TABLE), 64, 64)
    assert insts == [] and ev["instance_dropped_empty"] == 1


# --------------------------------------------------------------------------- merge
def _inst(label: str, x0: int, y0: int, x1: int, y1: int, kind: str = "polygon") -> ig.Instance:
    m = np.zeros((64, 64), bool)
    m[y0:y1, x0:x1] = True
    poly = [(x0, y0), (x1 - 1, y0), (x1 - 1, y1 - 1), (x0, y1 - 1)] if kind == "polygon" else None
    return ig.Instance(label, "focal", label.title(), m, kind, poly)


def test_merge_same_label_high_iou():
    a, b = _inst("nodule", 10, 10, 30, 30), _inst("nodule", 11, 11, 31, 31)  # IoU ~0.82
    out, n = ig.merge_duplicates([a, b])
    assert n == 1 and len(out) == 1
    assert out[0].mask.sum() == np.logical_or(a.mask, b.mask).sum()
    assert ig.FLAG_MERGED in out[0].flags and out[0].merged_from == 2 and out[0].geom_kind == "polygon"


def test_no_merge_across_labels_or_low_iou():
    a, b = _inst("nodule", 10, 10, 30, 30), _inst("mass", 10, 10, 30, 30)
    c = _inst("nodule", 20, 20, 40, 40)  # IoU with a = 100/700
    out, n = ig.merge_duplicates([a, b, c])
    assert n == 0 and [i.label for i in out] == ["nodule", "mass", "nodule"]


def test_merge_threshold_is_strict_and_transitive():
    a = _inst("effusion", 0, 0, 10, 10)
    b = _inst("effusion", 0, 0, 10, 6)  # IoU exactly 0.6 -> not merged
    assert ig.merge_duplicates([a, b])[1] == 0
    x, y, z = _inst("effusion", 0, 0, 20, 20), _inst("effusion", 1, 0, 21, 20), _inst("effusion", 2, 0, 22, 20)
    out, n = ig.merge_duplicates([x, y, z])
    assert n == 2 and len(out) == 1


# --------------------------------------------------------------------------- normal logic
@pytest.mark.parametrize(
    "is_negative,n,expected",
    [(True, 0, (True, False)), (False, 2, (False, False)), (True, 1, (False, True)), (False, 0, (False, True))],
)
def test_classify_normal(is_negative, n, expected):
    assert ig.classify_normal(is_negative, n) == expected


# --------------------------------------------------------------------------- end to end row conversion
def test_convert_row_writes_valid_case_and_masks(tmp_path: Path):
    for d in ("images", "masks"):
        (tmp_path / d).mkdir()
    ann = {
        "syms": ["Effusion", "Nodule", "Cardiomegaly"],
        "boxes": [[100, 100, 300, 300], [500, 500, 540, 530], [400, 600, 700, 800]],
        "polygons": [SQUARE, [[500, 500], [501, 501]], [[400, 600], [700, 600], [700, 800], [400, 800]]],
    }
    res = ig.convert_row(make_row(ann, image_id="777"), ig.map_syms(ann["syms"], TABLE), tmp_path)
    case: Case = res["case"]
    Case.model_validate_json(case.model_dump_json())
    assert case.case_id == "cxd_777" and case.image_path == "images/cxd_777.png" and not case.is_normal
    assert [f.finding_id for f in case.findings] == ["cxd_777#F1", "cxd_777#F2", "cxd_777#F3"]
    assert [f.label for f in case.findings] == ["effusion", "nodule", "cardiomegaly"]
    assert [f.kind for f in case.findings] == ["focal", "focal", "pattern"]
    assert [f.geometry.kind for f in case.findings] == ["polygon", "bbox", "polygon"]
    assert case.qa_flags == [ig.FLAG_MASK_FROM_BBOX]
    assert case.source_split == "train" and case.split == "practice" and case.pixel_spacing_mm is None
    img = cv2.imread(str(tmp_path / case.image_path), cv2.IMREAD_UNCHANGED)
    assert img.shape == (1024, 1024) and img.dtype == np.uint8
    for f in case.findings:
        assert f.geometry.mask_path == f"masks/{f.finding_id.replace('#', '_')}.png"
        m = cv2.imread(str(tmp_path / f.geometry.mask_path), cv2.IMREAD_UNCHANGED)
        assert m.shape == (1024, 1024) and set(np.unique(m)) <= {0, 255} and (m > 0).any()
        assert f.geometry.bbox == ig.mask_bbox(m > 0)
        assert f.area_frac == pytest.approx((m > 0).sum() / 1024**2)
        x0, y0, x1, y1 = f.geometry.bbox
        assert x0 <= f.centroid[0] <= x1 and y0 <= f.centroid[1] <= y1
    assert case.findings[0].geometry.bbox == (100.0, 100.0, 301.0, 301.0)


def test_convert_row_normal_and_mismatch(tmp_path: Path):
    for d in ("images", "masks"):
        (tmp_path / d).mkdir()
    empty = {"syms": [], "boxes": [], "polygons": []}
    res = ig.convert_row(make_row(empty, is_negative=True, image_id="5"), {}, tmp_path)
    assert res["case"].is_normal and res["case"].findings == [] and res["excluded"] is None

    res = ig.convert_row(make_row(empty, is_negative=False, image_id="6"), {}, tmp_path)
    assert res["case"] is None and res["excluded"] == [ig.FLAG_NEG_MISMATCH]
    assert not (tmp_path / "images" / "cxd_6.png").exists()

    ann = {"syms": ["Mass"], "boxes": [[1, 1, 50, 50]], "polygons": [SQUARE]}
    res = ig.convert_row(make_row(ann, is_negative=True, image_id="7"), ig.map_syms(["Mass"], TABLE), tmp_path)
    assert res["case"] is None and res["excluded"] == [ig.FLAG_NEG_MISMATCH]


def test_convert_row_rgba_and_resize(tmp_path: Path):
    for d in ("images", "masks"):
        (tmp_path / d).mkdir()
    ann = {"syms": ["Mass"], "boxes": [[50, 50, 150, 150]], "polygons": [[[50, 50], [149, 50], [149, 149], [50, 149]]]}
    res = ig.convert_row(make_row(ann, size=512, mode="RGBA", image_id="9"), ig.map_syms(["Mass"], TABLE), tmp_path)
    case = res["case"]
    assert res["stats"]["original_mode"] == "RGBA"
    assert ig.FLAG_RESIZED in case.qa_flags
    with Image.open(tmp_path / case.image_path) as im:
        assert im.mode == "L" and im.size == (1024, 1024)
    x0, y0, x1, y1 = case.findings[0].geometry.bbox
    assert (x0, y0) == (100.0, 100.0) and 296 <= x1 <= 300


def test_convert_row_is_resumable_and_idempotent(tmp_path: Path):
    for d in ("images", "masks"):
        (tmp_path / d).mkdir()
    ann = {"syms": ["Effusion"], "boxes": [[100, 100, 300, 300]], "polygons": [SQUARE]}
    mapping = ig.map_syms(["Effusion"], TABLE)
    a = ig.convert_row(make_row(ann, image_id="3"), mapping, tmp_path)["case"]
    mtimes = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.png")}
    b = ig.convert_row(make_row(ann, image_id="3"), mapping, tmp_path)["case"]
    assert a.model_dump_json() == b.model_dump_json()
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*.png")} == mtimes  # nothing rewritten
