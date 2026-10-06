"""SPEC §7.3 review-area coverage and §7.4 search metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np

from backend.app.search.dwell import DwellSamples, dwell_in, first_time_reaching

LUNG_UNIONS = ("right_lung", "left_lung", "lungs")


@dataclass
class Coverage:
    visited: list[str]
    unvisited: list[str]
    first_visits: list[str]  # zones in the order they first became "visited"
    dwell_by_zone: dict[str, float] = field(default_factory=dict)


def review_coverage(
    samples: DwellSamples,
    zones: Mapping[str, np.ndarray],
    review_areas: Sequence[str],
    visit_ms: float,
    zone_order: Sequence[str] | None = None,
) -> Coverage:
    """Visited = dwell (no dilation) ≥ visit_ms. Review areas missing from `zones` count as unvisited."""
    names = [z for z in (zone_order or zones.keys()) if z in zones and z not in LUNG_UNIONS]
    dwell = {z: dwell_in(samples, zones[z]) for z in names}
    for ra in review_areas:
        if ra in zones and ra not in dwell:
            dwell[ra] = dwell_in(samples, zones[ra])
    visited = [ra for ra in review_areas if dwell.get(ra, 0.0) >= visit_ms]
    unvisited = [ra for ra in review_areas if ra not in visited]
    times = []
    for z in names:
        if dwell[z] >= visit_ms:
            t = first_time_reaching(samples, zones[z], visit_ms)
            if t is not None:
                times.append((t, z))
    first = [z for _, z in sorted(times)]
    return Coverage(visited, unvisited, first, {k: round(v, 1) for k, v in dwell.items()})


def lung_coverage_pct(samples: DwellSamples, lungs: np.ndarray | None, rho_px: float) -> float:
    """Fraction of lung pixels within ρ of any dwelled sample (point weight > 0)."""
    if lungs is None or not lungs.any() or samples.n == 0:
        return 0.0
    h, w = lungs.shape
    pts = np.zeros((h, w), np.uint8)
    keep = samples.w_point > 0
    xi = np.clip(samples.x[keep].astype(int), 0, w - 1)
    yi = np.clip(samples.y[keep].astype(int), 0, h - 1)
    inb = (samples.x[keep] >= 0) & (samples.x[keep] < w) & (samples.y[keep] >= 0) & (samples.y[keep] < h)
    pts[yi[inb], xi[inb]] = 1
    r = max(1, int(round(rho_px)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    near = cv2.dilate(pts, k) > 0
    return round(100.0 * float((near & lungs).sum()) / float(lungs.sum()), 1)


def zone_at(x: float, y: float, zones: Mapping[str, np.ndarray], priority: Sequence[str]) -> str | None:
    """Zone id (patient side) containing the point, by priority order."""
    for z in priority:
        m = zones.get(z)
        if m is None:
            continue
        h, w = m.shape
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < w and 0 <= yi < h and m[yi, xi]:
            return z
    return None


MARK_ZONE_PRIORITY = (
    "right_upper_zone",
    "right_mid_zone",
    "right_lower_zone",
    "left_upper_zone",
    "left_mid_zone",
    "left_lower_zone",
    "retrocardiac",
    "cardiac_silhouette",
    "right_hilum",
    "left_hilum",
    "mediastinum",
    "subdiaphragmatic",
    "right_clavicle",
    "left_clavicle",
    "spine",
)


def nearest_zone(x: float, y: float, zones: Mapping[str, np.ndarray], priority: Sequence[str]) -> str | None:
    """zone_at, else the zone whose nearest pixel is closest to the point."""
    z = zone_at(x, y, zones, priority)
    if z:
        return z
    best, best_d = None, float("inf")
    for name in priority:
        m = zones.get(name)
        if m is None or not m.any():
            continue
        ys, xs = np.nonzero(m[::4, ::4])
        d = float(np.min((xs * 4 - x) ** 2 + (ys * 4 - y) ** 2))
        if d < best_d:
            best, best_d = name, d
    return best


def search_metrics(events: Sequence, marks: Sequence, total_time_s: float | None) -> dict:
    """Time to first mark, zoom and loupe usage (SPEC §7.4)."""
    t_first = None
    for e in events:
        if e.kind == "down" and e.x is not None:
            if any(abs(e.x - m.x) <= 5 and abs(e.y - m.y) <= 5 for m in marks):
                t_first = round(e.t / 1000.0, 2)
                break
    if total_time_s is None and events:
        total_time_s = round(events[-1].t / 1000.0, 2)
    return {
        "time_to_first_mark_s": t_first,
        "total_time_s": total_time_s,
        "zoom_used": any(e.zoom > 1.05 for e in events),
        "loupe_used": any(e.loupe for e in events),
    }
