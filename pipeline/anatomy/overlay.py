"""QA overlays: anatomy + zones + finding outlines → data/qa/anatomy_<case_id>.png (SPEC §15.2 M2).

Run: python -m pipeline.anatomy.overlay [--n 20] [--case cxd_123 ...]
The image is shown in standard display: patient RIGHT on the image LEFT (an "R" marker is drawn there).
"""

from __future__ import annotations

import argparse
import random
from typing import Any

import cv2
import numpy as np

from pipeline.anatomy import common as C

# BGR
ZONE_STYLE: list[tuple[str, tuple[int, int, int]]] = [
    ("right_apex", (60, 220, 60)),
    ("left_apex", (60, 220, 60)),
    ("right_hilum", (0, 140, 255)),
    ("left_hilum", (0, 140, 255)),
    ("right_costophrenic_angle", (255, 220, 0)),
    ("left_costophrenic_angle", (255, 220, 0)),
    ("subdiaphragmatic", (200, 200, 60)),
    ("mediastinum", (160, 160, 160)),
    ("cardiac_silhouette", (90, 60, 200)),
    ("retrocardiac", (180, 60, 255)),  # after the heart so it stays visible
]
THIRD_TINT = {"upper": (255, 120, 60), "mid": (60, 200, 255), "lower": (120, 255, 120)}
FOCAL = (0, 255, 255)
PATTERN = (255, 0, 255)


def _outline(img: np.ndarray, m: np.ndarray, col: tuple[int, int, int], th: int = 2) -> None:
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(img, cnts, -1, col, th, lineType=cv2.LINE_AA)


def _text(img: np.ndarray, s: str, xy: tuple[int, int], col=(255, 255, 255), scale: float = 0.55) -> None:
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, col, 1, cv2.LINE_AA)


def render_overlay(case: dict[str, Any], zones: dict[str, np.ndarray], meta: dict[str, Any]) -> np.ndarray:
    proc = C.processed_dir()
    gray = cv2.imread(str(proc / case["image_path"]), cv2.IMREAD_GRAYSCALE)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    tint = img.copy()
    for side in ("right", "left"):
        for part, col in THIRD_TINT.items():
            tint[zones[f"{side}_{part}_zone"]] = col
    img = cv2.addWeighted(tint, 0.18, img, 0.82, 0)
    for side in ("right", "left"):
        _outline(img, zones[f"{side}_lung"], (255, 255, 255), 1)
    for z, col in ZONE_STYLE:
        if zones[z].any():
            _outline(img, zones[z], col, 2)
    xm = int(round(meta["midline_x"]))
    for y in range(0, img.shape[0], 24):
        cv2.line(img, (xm, y), (xm, y + 12), (0, 0, 255), 1)
    # finding outlines + labels
    lines = []
    for k, f in enumerate(case["findings"]):
        col = FOCAL if f["kind"] == "focal" else PATTERN
        mp = f["geometry"].get("mask_path")
        if mp:
            fm = C.read_mask_png(mp, proc)
            _outline(img, fm, col, 2)
        short = f["finding_id"].split("#", 1)[1]
        cx, cy = (int(v) for v in f["centroid"])
        _text(img, f"{short} {f['label']}", (cx + 8, cy), col, 0.6)
        if k >= 8:
            continue
        if f["kind"] == "focal":
            lines.append(f"{short} {f['label']} [{f.get('side')}] {f.get('relative_location')}")
            lines.append(f"    zones={f.get('zones')} b0={f.get('difficulty')}")
        else:
            lines.append(f"{short} {f['label']} (pattern)")
    h, w = img.shape[:2]
    _text(img, "R", (24, 60), (255, 255, 255), 1.6)
    hdr = f"{case['case_id']}  {case['split']}  image LEFT = patient RIGHT  approx={meta['approximate']}"
    if case.get("cardiothoracic_ratio") is not None:
        hdr += f"  CTR={case['cardiothoracic_ratio']:.2f}"
    _text(img, hdr, (80, 32), (255, 255, 255), 0.7)
    flags = [f for f in case.get("qa_flags", []) if f]
    if flags:
        _text(img, "flags: " + ",".join(flags), (80, 56), (80, 80, 255), 0.55)
    if len(case["findings"]) > 8:
        lines.append(f"... +{len(case['findings']) - 8} more findings")
    y = h - 14 - 22 * (len(lines) - 1)
    for ln in lines:
        _text(img, ln[:110], (12, y), (255, 255, 255), 0.5)
        y += 22
    legend = [
        ("apex", (60, 220, 60)),
        ("hilum", (0, 140, 255)),
        ("CP angle", (255, 220, 0)),
        ("retrocardiac", (180, 60, 255)),
        ("subdiaphragmatic", (200, 200, 60)),
        ("mediastinum", (160, 160, 160)),
        ("heart", (90, 60, 200)),
        ("midline", (0, 0, 255)),
    ]
    x = w - 190
    for i, (name, col) in enumerate(legend):
        _text(img, name, (x, 90 + 20 * i), col, 0.5)
    return img


def write_overlays(n: int = 20, seed: int = 0, case_ids: list[str] | None = None) -> list[str]:
    from shared.rle import read_zones

    log = C.get_logger("overlay")
    proc = C.processed_dir()
    cases = [c for c in C.read_cases() if c.get("zones_path") and c.get("anatomy_path")]
    if case_ids:
        pick = [c for c in cases if c["case_id"] in set(case_ids)]
    else:
        rng = random.Random(seed)
        abn = [c for c in cases if any(f["kind"] == "focal" for f in c["findings"])]
        nor = [c for c in cases if c["is_normal"]]
        n_nor = min(len(nor), max(1, n // 5))
        pick = rng.sample(abn, min(len(abn), n - n_nor)) + rng.sample(nor, n_nor)
    out = C.qa_dir()
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for c in pick:
        zones, meta = read_zones(proc / c["zones_path"])
        img = render_overlay(c, zones, meta)
        p = out / f"anatomy_{c['case_id']}.png"
        cv2.imwrite(str(p), cv2.resize(img, (768, 768), interpolation=cv2.INTER_AREA))
        written.append(str(p))
    log.info("wrote %d overlays to %s", len(written), out)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--case", action="append", default=None)
    a = ap.parse_args(argv)
    write_overlays(a.n, a.seed, a.case)


if __name__ == "__main__":
    main()
