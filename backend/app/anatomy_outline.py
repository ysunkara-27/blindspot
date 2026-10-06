"""Simplified zone outlines for "Show anatomy" after submit (GET /api/attempts/{aid}/anatomy).

Pure functions over boolean masks: cv2.findContours + approxPolyDP, at most MAX_POINTS points per polygon.
Zone ids name the PATIENT's side (patient right = image left); outlines are in canonical pixel space.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

MAX_POINTS = 60
MIN_AREA_FRAC = 0.0005  # drop specks (< 0.05% of the image)
SKIP_ZONES = frozenset({"lungs"})  # union of right_lung + left_lung; redundant as an outline


def simplify_contour(cnt: np.ndarray, max_points: int = MAX_POINTS) -> list[list[float]]:
    """approxPolyDP with a growing epsilon until the polygon has <= max_points vertices."""
    peri = cv2.arcLength(cnt, True)
    eps = max(0.5, 0.002 * peri)
    approx = cv2.approxPolyDP(cnt, eps, True)
    while len(approx) > max_points:
        eps *= 1.5
        approx = cv2.approxPolyDP(cnt, eps, True)
    return [[float(x), float(y)] for x, y in approx.reshape(-1, 2)]


def mask_outlines(mask: np.ndarray, max_points: int = MAX_POINTS, min_area_frac: float = MIN_AREA_FRAC) -> list:
    """External outlines of a boolean mask, largest first; each a list of [x, y] (>= 3 points)."""
    m = np.ascontiguousarray(mask, dtype=np.uint8)
    if not m.any():
        return []
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = min_area_frac * m.shape[0] * m.shape[1]
    out = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < min_area:
            continue
        poly = simplify_contour(c, max_points)
        if len(poly) >= 3:
            out.append(poly)
    return out


def zone_outlines(
    zones: dict[str, np.ndarray],
    meta: dict[str, Any],
    human: Any,
    review_areas: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """{zones: [{id, human, review_area, polygons}], midline_x, approximate, width, height}."""
    out = []
    for zid, m in zones.items():
        if zid in SKIP_ZONES:
            continue
        polys = mask_outlines(m)
        if polys:
            out.append({"id": zid, "human": human(zid), "review_area": zid in review_areas, "polygons": polys})
    return {
        "zones": out,
        "midline_x": float(meta["midline_x"]) if meta.get("midline_x") is not None else None,
        "approximate": bool(meta.get("approximate", False)),
        "width": meta.get("width"),
        "height": meta.get("height"),
    }
