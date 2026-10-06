"""SPEC §7.1 dwell: attention-proxy time inside a region from cursor / loupe / zoom telemetry.

`dwell_ms` is the literal §7.1 algorithm. `dwell_samples` + `dwell_in` compute the identical quantity
vectorised so one pass over 20k events serves many regions (findings, zones, review areas).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np


def _get(e: Any, k: str) -> Any:
    return e.get(k) if isinstance(e, dict) else getattr(e, k)


def _inside(region: np.ndarray, x: float, y: float) -> bool:
    h, w = region.shape
    xi, yi = int(x), int(y)
    return 0 <= xi < w and 0 <= yi < h and bool(region[yi, xi])


def center_in(vp: Sequence[float], region: np.ndarray) -> bool:
    x0, y0, x1, y1 = vp
    return _inside(region, (x0 + x1) / 2, (y0 + y1) / 2)


def dwell_ms(events: Sequence[Any], region: np.ndarray, cfg: dict) -> float:
    """Literal transcription of SPEC §7.1. cfg = scoring.yaml['dwell']."""
    total, still = 0.0, 0.0
    for e0, e1 in pairwise(events):
        dt = min(_get(e1, "t") - _get(e0, "t"), cfg["max_dt_ms"])
        x0, y0 = _get(e0, "x"), _get(e0, "y")
        if x0 is None or y0 is None:
            continue
        x1, y1 = _get(e1, "x"), _get(e1, "y")
        moved = x1 is None or y1 is None or (abs(x1 - x0) + abs(y1 - y0)) > 1.0
        still = 0.0 if moved else still + dt
        if still > cfg["max_still_ms"]:
            continue
        if _inside(region, x0, y0):
            total += dt
        if _get(e0, "zoom") >= cfg["zoom_dwell_min"] and center_in(_get(e0, "vp"), region):
            total += cfg["zoom_dwell_weight"] * dt
    return total


@dataclass
class DwellSamples:
    """Per-interval weights; point weight applies at (x, y), zoom weight at the viewport centre (cx, cy)."""

    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    w_point: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    w_zoom: np.ndarray

    @property
    def n(self) -> int:
        return int(self.t.size)


def dwell_samples(events: Sequence[Any], cfg: dict) -> DwellSamples:
    ts, xs, ys, wp, cxs, cys, wz = [], [], [], [], [], [], []
    still = 0.0
    for e0, e1 in pairwise(events):
        dt = min(_get(e1, "t") - _get(e0, "t"), cfg["max_dt_ms"])
        x0, y0 = _get(e0, "x"), _get(e0, "y")
        if x0 is None or y0 is None:
            continue
        x1, y1 = _get(e1, "x"), _get(e1, "y")
        moved = x1 is None or y1 is None or (abs(x1 - x0) + abs(y1 - y0)) > 1.0
        still = 0.0 if moved else still + dt
        if still > cfg["max_still_ms"]:
            continue
        vp = _get(e0, "vp")
        zoomed = _get(e0, "zoom") >= cfg["zoom_dwell_min"]
        ts.append(_get(e0, "t"))
        xs.append(x0)
        ys.append(y0)
        wp.append(dt)
        cxs.append((vp[0] + vp[2]) / 2)
        cys.append((vp[1] + vp[3]) / 2)
        wz.append(cfg["zoom_dwell_weight"] * dt if zoomed else 0.0)
    f = lambda a: np.asarray(a, dtype=float)  # noqa: E731
    return DwellSamples(f(ts), f(xs), f(ys), f(wp), f(cxs), f(cys), f(wz))


def _lookup(region: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h, w = region.shape
    xi, yi = x.astype(int), y.astype(int)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h) & (x >= 0) & (y >= 0)
    out = np.zeros(x.shape, dtype=bool)
    out[ok] = region[yi[ok], xi[ok]]
    return out


def contributions(s: DwellSamples, region: np.ndarray) -> np.ndarray:
    """Per-sample dwell contribution (ms) to `region`."""
    if s.n == 0:
        return np.zeros(0)
    return s.w_point * _lookup(region, s.x, s.y) + s.w_zoom * _lookup(region, s.cx, s.cy)


def dwell_in(s: DwellSamples, region: np.ndarray) -> float:
    return float(contributions(s, region).sum())


def first_time_reaching(s: DwellSamples, region: np.ndarray, threshold_ms: float) -> float | None:
    """Telemetry time (ms) at which cumulative dwell in `region` first reaches threshold_ms (None if never)."""
    c = contributions(s, region)
    if c.size == 0:
        return None
    cum = np.cumsum(c)
    idx = np.flatnonzero(cum >= max(threshold_ms, 1e-9))
    return float(s.t[idx[0]]) if idx.size else None
