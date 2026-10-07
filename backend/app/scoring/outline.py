"""Free-drawn outline marks (Mark.tool = "draw", Mark.polygon): rasterisation, hit rules and the outline verdict.

A drawn mark's (x, y) is its polygon centroid; it is accepted as a hit on a finding when the centroid hits (the
point rule in scoring/hit.py) OR IoU(polygon, finding mask) ≥ iou_hit OR ≥ area_frac_hit of the polygon's area lies
on the finding. The verdict shown on the reveal (RevealMark.outline_verdict):
  on_target  IoU ≥ on_target_iou
  partly     a hit by the looser rules (centroid / IoU / area fraction) but not on target
  too_broad  covers ≥ 50 % of the finding but its area is > too_broad_factor × the finding's
  off        none of the above
Thresholds mirror config/scoring.yaml `outline` (read when present; DEFAULT_OUTLINE otherwise). Pure functions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import cv2
import numpy as np

from shared.contracts import Mark

# Mirrors config/scoring.yaml `outline` (orchestrator-owned); read through outline_cfg() when the file has the keys.
DEFAULT_OUTLINE: dict[str, float] = {
    "iou_hit": 0.1,
    "on_target_iou": 0.3,
    "area_frac_hit": 0.4,
    "too_broad_factor": 8,
    "max_points": 400,
    "cover_frac_broad": 0.5,
}
MIN_POINTS = 3


def outline_cfg(scoring: Mapping[str, Any] | None) -> dict[str, float]:
    cfg = dict(DEFAULT_OUTLINE)
    for k, v in (scoring or {}).get("outline", {}).items() if scoring else []:
        if k in cfg and isinstance(v, (int, float)):
            cfg[k] = float(v)
    return cfg


def polygon_centroid(poly: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Area-weighted centroid (shoelace); the vertex mean for a degenerate (zero-area) polygon."""
    pts = np.asarray(poly, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = cross.sum() / 2.0
    if abs(a) < 1e-9:
        return float(x.mean()), float(y.mean())
    cx = ((x + x1) * cross).sum() / (6.0 * a)
    cy = ((y + y1) * cross).sum() / (6.0 * a)
    return float(cx), float(cy)


def polygon_problems(
    poly: Sequence[Sequence[float]] | None, width: float, height: float, max_points: int, mark_id: str
) -> list[str]:
    """Validation messages (empty = ok): ≥ 3 points, ≤ max_points, finite, inside [0, width] × [0, height]."""
    if poly is None:
        return []
    errs: list[str] = []
    if len(poly) < MIN_POINTS:
        errs.append(f"mark {mark_id!r} polygon needs at least {MIN_POINTS} points (has {len(poly)})")
    if len(poly) > max_points:
        errs.append(f"mark {mark_id!r} polygon has too many points ({len(poly)} > {max_points})")
    for i, p in enumerate(poly):
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            errs.append(f"mark {mark_id!r} polygon point {i} is not an (x, y) pair")
            break
        if not (np.isfinite(x) and np.isfinite(y)):
            errs.append(f"mark {mark_id!r} polygon point {i} is not finite")
            break
        if not (0.0 <= x <= width and 0.0 <= y <= height):
            errs.append(f"mark {mark_id!r} polygon point {i} ({x:g}, {y:g}) is outside the image")
            break
    return errs


def normalize_mark(mark: Mark) -> Mark:
    """A mark with a polygon gets tool "draw" and (x, y) = the polygon centroid; other marks are returned as is."""
    if not mark.polygon:
        return mark if mark.tool != "draw" else mark.model_copy(update={"tool": "point"})
    cx, cy = polygon_centroid(mark.polygon)
    return mark.model_copy(update={"x": round(cx, 2), "y": round(cy, 2), "tool": "draw"})


def rasterize(poly: Sequence[Sequence[float]], height: int, width: int) -> np.ndarray:
    """Boolean (height, width) mask of the filled polygon (pixel space, vertices rounded)."""
    out = np.zeros((int(height), int(width)), np.uint8)
    pts = np.asarray([[round(float(x)), round(float(y))] for x, y in poly], dtype=np.int32).reshape(-1, 1, 2)
    if len(pts) >= 3:
        cv2.fillPoly(out, [pts], 1)
    return out > 0


def overlap_stats(poly_mask: np.ndarray, finding_mask: np.ndarray) -> dict[str, float]:
    """iou, poly_frac (share of the polygon on the finding), cover_frac (share of the finding inside the polygon),
    area_ratio (polygon area / finding area)."""
    pa = float(poly_mask.sum())
    fa = float(finding_mask.sum())
    inter = float((poly_mask & finding_mask).sum())
    union = pa + fa - inter
    return {
        "iou": inter / union if union > 0 else 0.0,
        "poly_frac": inter / pa if pa > 0 else 0.0,
        "cover_frac": inter / fa if fa > 0 else 0.0,
        "area_ratio": pa / fa if fa > 0 else float("inf"),
    }


def outline_hits(stats: Mapping[str, float], cfg: Mapping[str, float]) -> bool:
    return stats["iou"] >= cfg["iou_hit"] or stats["poly_frac"] >= cfg["area_frac_hit"]


def outline_verdict(stats: Mapping[str, float], centroid_hit: bool, cfg: Mapping[str, float]) -> str:
    if stats["iou"] >= cfg["on_target_iou"]:
        return "on_target"
    if stats["cover_frac"] >= cfg.get("cover_frac_broad", 0.5) and stats["area_ratio"] > cfg["too_broad_factor"]:
        return "too_broad"
    if centroid_hit or outline_hits(stats, cfg):
        return "partly"
    return "off"


def outline_verdict_for(
    mark_id: str,
    matched: str | None,
    stats: Mapping[tuple[str, str], Mapping[str, float]],
    hit_row: Mapping[str, bool],
    cfg: Mapping[str, float],
) -> str:
    """Verdict of a drawn mark against its matched finding, else against the finding it covers most (so an unmatched
    outline is still reported as too_broad when it swallowed a finding). `hit_row` = {finding id: hit?} for the mark."""
    mine = {fid: st for (mid, fid), st in stats.items() if mid == mark_id}
    if not mine:
        return "off"
    fid = matched if matched in mine else max(mine, key=lambda f: mine[f]["cover_frac"])
    return outline_verdict(mine[fid], bool(hit_row.get(fid, False)), cfg)
