"""Pack format and QA rendering for volumetric cases.

volumes/<case_id>.i16.gz  int16 little-endian, C-order (z,y,x), gzip     (CT in HU clipped to [-1024, 3071])
masks/<case_id>.u8.gz     uint8 same shape, label VALUES as in the MSD mask (anatomy + lesion values)
previews/<case_id>_axial.png  QA only: windowed axial slice, lesion outline amber, anatomy outline blue, "R" top-left
zones3d/<case_id>.json    zone DEFINITIONS (see zones_document); the backend derives the masks from the pack
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import cv2
import numpy as np

CT_MIN, CT_MAX = -1024, 3071
LESION_BGR = (0, 170, 255)  # amber
ANATOMY_BGR = (255, 160, 60)  # blue
TILE = 192


def write_gz(path: Path, arr: np.ndarray) -> int:
    """Write a C-contiguous array as gzip (level 6). Returns the compressed size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(np.ascontiguousarray(arr).tobytes())
    tmp.replace(path)
    return path.stat().st_size


def read_gz(path: Path, dtype: str, shape: tuple[int, int, int]) -> np.ndarray:
    with gzip.open(path, "rb") as fh:
        buf = fh.read()
    arr = np.frombuffer(buf, dtype=np.dtype(dtype))
    if arr.size != int(np.prod(shape)):
        raise ValueError(f"{path}: {arr.size} values do not fill shape {shape}")
    return arr.reshape(shape)


def to_int16(vol: np.ndarray, modality: str) -> np.ndarray:
    if modality == "ct":
        vol = np.clip(vol, CT_MIN, CT_MAX)
    else:
        vol = np.clip(vol, -32768, 32767)
    return np.rint(vol).astype("<i2")


def window_u8(sl: np.ndarray, wc: float, ww: float) -> np.ndarray:
    lo = wc - ww / 2
    return np.clip((sl.astype(np.float32) - lo) / max(ww, 1e-6) * 255.0, 0, 255).astype(np.uint8)


def mr_window(vol: np.ndarray) -> tuple[float, float]:
    """Percentile 1–99 of the non-zero voxels → (wc, ww)."""
    nz = vol[vol != 0]
    if nz.size == 0:
        return 0.0, 1.0
    p1, p99 = np.percentile(nz, [1, 99])
    ww = max(float(p99 - p1), 1.0)
    return round(float((p1 + p99) / 2), 1), round(ww, 1)


def _draw_outline(img: np.ndarray, binary: np.ndarray, colour: tuple[int, int, int], thickness: int = 1) -> None:
    contours, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(img, contours, -1, colour, thickness)


def render_preview(
    vol: np.ndarray,
    mask: np.ndarray,
    z: int,
    window: tuple[float, float],
    lesion_values: tuple[int, ...],
    anatomy_values: tuple[int, ...],
) -> np.ndarray:
    """BGR image of slice z with outlines and an 'R' marker at image left (patient right)."""
    g = window_u8(vol[z], *window)
    img = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if anatomy_values:
        _draw_outline(img, np.isin(mask[z], anatomy_values), ANATOMY_BGR)
    if lesion_values:
        _draw_outline(img, np.isin(mask[z], lesion_values), LESION_BGR)
    cv2.putText(img, "R", (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def slice_polygon(binary: np.ndarray, max_pts: int = 60) -> list[tuple[float, float]] | None:
    """Largest external contour of a 2-D mask as (x, y) floats, simplified to ≤ max_pts."""
    contours, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    eps = 0.0
    while len(c) > max_pts:
        eps = eps + 0.5
        c = cv2.approxPolyDP(c, eps, True)
    pts = [(float(p[0][0]), float(p[0][1])) for p in c]
    return pts if len(pts) >= 3 else None


def zones_document(
    shape: tuple[int, int, int],
    spacing: tuple[float, float, float],
    organ_zones: dict[str, list[int]],
    half_zones: dict[str, str],
    *,
    organ_dilation_mm: float,
    midline_frac: float,
) -> dict:
    """The zones3d/<case_id>.json content (documented in docs/PROGRESS.md under VOLUMETRIC ZONES FILE)."""
    zones: dict[str, list[int] | str] = {k: list(v) for k, v in organ_zones.items()}
    zones.update({"superior_slab": "slab:superior", "mid_slab": "slab:mid", "inferior_slab": "slab:inferior"})
    zones.update(half_zones)
    return {
        "version": 1,
        "shape": list(shape),
        "spacing": list(spacing),
        "zones": zones,
        "rules": {
            "organ": "mask value in list, dilated by organ_dilation_mm per axis, holes filled",
            "organ_dilation_mm": organ_dilation_mm,
            "slab": "thirds of z: superior=[0,nz//3), mid=[nz//3, nz-nz//3), inferior=[nz-nz//3, nz)",
            "half": "x columns: midline = |x-(nx-1)/2| <= midline_frac*nx; right = x below that band; left = above",
            "midline_frac": midline_frac,
            "patient_right_is_low_x": True,
        },
    }


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")))


def contact_sheet(sections: list[tuple[str, list[tuple[str, np.ndarray]]]], path: Path, cols: int = 6) -> None:
    """Rows of titled tiles per section (task). Each tile is a preview BGR image resized to TILE×TILE (letterboxed)."""
    header = 22
    rows_img: list[np.ndarray] = []
    for title, tiles in sections:
        band = np.full((header, cols * TILE, 3), 30, np.uint8)
        cv2.putText(band, title, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        rows_img.append(band)
        n_rows = max((len(tiles) + cols - 1) // cols, 1)
        grid = np.zeros((n_rows * TILE, cols * TILE, 3), np.uint8)
        for i, (label, img) in enumerate(tiles):
            r, c = divmod(i, cols)
            h, w = img.shape[:2]
            s = TILE / max(h, w)
            small = cv2.resize(img, (max(int(w * s), 1), max(int(h * s), 1)), interpolation=cv2.INTER_AREA)
            y0, x0 = r * TILE + (TILE - small.shape[0]) // 2, c * TILE + (TILE - small.shape[1]) // 2
            grid[y0 : y0 + small.shape[0], x0 : x0 + small.shape[1]] = small
            cv2.putText(
                grid,
                label,
                (c * TILE + 4, r * TILE + TILE - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
        rows_img.append(grid)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.concatenate(rows_img, axis=0))
