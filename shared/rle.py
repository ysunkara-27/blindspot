"""Run-length encoding for boolean masks and the zones-file format. FROZEN CONTRACT (orchestrator).

Zones file: data/processed/zones/<case_id>.json
{
  "case_id": "cxd_1", "width": 1024, "height": 1024, "approximate": false, "midline_x": 512.0,
  "zones": { "<zone_id>": <rle>, ... }       # every id in config/review_areas.yaml:zones that exists
                                             # PLUS "right_lung", "left_lung", "lungs" (union) for coverage
}
<rle> = list[int]: row-major (C order) alternating run lengths, starting with a run of 0s (COCO uncompressed style).
Anatomy file: data/processed/anatomy/<case_id>.npz with key "masks" = np.packbits(bool (14, H, W), axis=-1),
"targets" = array of the 14 TXV names (patient-side after orientation check), "shape" = (14, H, W).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

LUNG_KEYS = ("right_lung", "left_lung", "lungs")


def encode(mask: np.ndarray) -> list[int]:
    flat = np.asarray(mask, dtype=bool).ravel(order="C")
    if flat.size == 0:
        return []
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    bounds = np.concatenate(([0], change, [flat.size]))
    runs = np.diff(bounds).tolist()
    if flat[0]:
        runs = [0] + runs
    return [int(r) for r in runs]


def decode(runs: list[int], height: int, width: int) -> np.ndarray:
    out = np.zeros(height * width, dtype=bool)
    pos, val = 0, False
    for r in runs:
        if val and r:
            out[pos : pos + r] = True
        pos += r
        val = not val
    return out.reshape(height, width)


def write_zones(path: Path, case_id: str, zones: dict[str, np.ndarray], *, approximate: bool, midline_x: float) -> None:
    first = next(iter(zones.values()))
    h, w = first.shape
    doc: dict[str, Any] = {
        "case_id": case_id,
        "width": int(w),
        "height": int(h),
        "approximate": bool(approximate),
        "midline_x": float(midline_x),
        "zones": {k: encode(v) for k, v in zones.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")))


def read_zones(path: Path) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    doc = json.loads(Path(path).read_text())
    h, w = doc["height"], doc["width"]
    masks = {k: decode(v, h, w) for k, v in doc["zones"].items()}
    meta = {k: v for k, v in doc.items() if k != "zones"}
    return masks, meta
