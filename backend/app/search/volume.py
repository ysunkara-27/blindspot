"""Volumetric search analysis: per-slice dwell, miss types and coverage from scroll/cursor telemetry.

Telemetry events on a volume carry `plane` and `slice`. The interval between consecutive events is attributed to the
(plane, slice) on screen at its start, capped at dwell.max_dt_ms (250 ms, as the 2D engine); gaps longer than
GAP_IGNORE_MS (tab hidden, no events) are ignored. Thresholds come from config/scoring.yaml `volumetric.dwell`.

Miss types (DECISION, docs/PROGRESS.md): the finding's slices on screen < slice_search_ms → missed_search; otherwise
missed_recognition when the slices were on screen < slice_recognition_ms OR the cursor never came within near_mm
(in-plane, on a slice holding the finding); missed_decision only when both held (long enough AND close enough).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from backend.app.cases import SLAB_THIRDS, finding_box
from shared.contracts import Finding, SliceDwell

GAP_IGNORE_MS = 5000.0
PLANES = ("axial", "coronal", "sagittal")
Box = tuple[int, int, int, int, int, int]  # z0, z1, y0, y1, x0, x1 (end-exclusive)


def _get(e: Any, k: str) -> Any:
    return e.get(k) if isinstance(e, dict) else getattr(e, k, None)


@dataclass
class Sample:
    plane: str
    slice: int
    x: float | None
    y: float | None
    ms: float


@dataclass
class SliceTrace:
    dwell: dict[tuple[str, int], float] = field(default_factory=dict)  # (plane, slice) → ms on screen
    samples: list[Sample] = field(default_factory=list)  # cursor samples with their interval weight


def slice_trace(events: Sequence[Any], cfg: Mapping) -> SliceTrace:
    """Per (plane, slice) time on screen + weighted cursor samples. Events without a slice are skipped."""
    out = SliceTrace()
    max_dt = float(cfg["max_dt_ms"])
    for e0, e1 in pairwise(events):
        s = _get(e0, "slice")
        if s is None:
            continue
        plane = _get(e0, "plane") or "axial"
        if plane not in PLANES:
            continue
        gap = float(_get(e1, "t")) - float(_get(e0, "t"))
        if gap < 0 or gap > GAP_IGNORE_MS:
            continue
        dt = min(gap, max_dt)
        key = (plane, int(s))
        out.dwell[key] = out.dwell.get(key, 0.0) + dt
        out.samples.append(Sample(plane, int(s), _get(e0, "x"), _get(e0, "y"), dt))
    return out


# ------------------------------------------------------------------ findings on slices
def box_of(f: Finding, shape: Sequence[int]) -> Box:
    return finding_box(f, tuple(int(n) for n in shape))  # type: ignore[return-value]


def slice_holds(box: Box, plane: str, s: int) -> bool:
    z0, z1, y0, y1, x0, x1 = box
    if plane == "axial":
        return z0 <= s < z1
    if plane == "coronal":
        return y0 <= s < y1
    return x0 <= s < x1


def finding_slice_ms(tr: SliceTrace, box: Box) -> float:
    """Total time (ms, any plane) a slice holding the finding was on screen."""
    return float(sum(ms for (plane, s), ms in tr.dwell.items() if slice_holds(box, plane, s)))


def finding_axial_slices_seen(tr: SliceTrace, box: Box, visit_ms: float) -> int:
    z0, z1 = box[0], box[1]
    return sum(1 for z in range(z0, z1) if tr.dwell.get(("axial", z), 0.0) >= visit_ms)


def _inplane_distance_mm(sample: Sample, box: Box, spacing: Sequence[float]) -> float | None:
    """Distance (mm) from the cursor to the finding's box in the sample's plane; None without a cursor."""
    if sample.x is None or sample.y is None:
        return None
    sz, sy, sx = (float(v) for v in spacing)
    z0, z1, y0, y1, x0, x1 = box
    if sample.plane == "axial":  # image (x, y) = (x, y)
        a = (sample.x, x0, x1 - 1, sx)
        b = (sample.y, y0, y1 - 1, sy)
    elif sample.plane == "coronal":  # image (x, y) = (x, z)
        a = (sample.x, x0, x1 - 1, sx)
        b = (sample.y, z0, z1 - 1, sz)
    else:  # sagittal: image (x, y) = (y, z)
        a = (sample.x, y0, y1 - 1, sy)
        b = (sample.y, z0, z1 - 1, sz)
    da = max(a[1] - a[0], 0.0, a[0] - a[2]) * a[3]
    db = max(b[1] - b[0], 0.0, b[0] - b[2]) * b[3]
    return float(np.hypot(da, db))


def near_ms(tr: SliceTrace, box: Box, spacing: Sequence[float], near_mm: float) -> float:
    """Time the cursor was within near_mm of the finding on a slice holding it."""
    total = 0.0
    for s in tr.samples:
        if not slice_holds(box, s.plane, s.slice):
            continue
        d = _inplane_distance_mm(s, box, spacing)
        if d is not None and d <= near_mm:
            total += s.ms
    return total


def miss_type_volume(slice_ms: float, near_ms_: float, cfg: Mapping) -> str:
    if slice_ms < float(cfg["slice_search_ms"]):
        return "missed_search"
    if slice_ms < float(cfg["slice_recognition_ms"]) or near_ms_ <= 0.0:
        return "missed_recognition"
    return "missed_decision"


# ------------------------------------------------------------------ summaries
def slice_dwell_list(tr: SliceTrace, boxes: Mapping[str, Box]) -> list[SliceDwell]:
    out = []
    for (plane, s), ms in sorted(tr.dwell.items(), key=lambda kv: (PLANES.index(kv[0][0]), kv[0][1])):
        fids = [fid for fid, b in boxes.items() if slice_holds(b, plane, s)]
        out.append(SliceDwell(plane=plane, slice=s, ms=round(ms, 1), has_finding=bool(fids), finding_ids=fids or None))
    return out


def slices_viewed_pct(tr: SliceTrace, nz: int, visit_ms: float) -> float:
    seen = sum(1 for (plane, s), ms in tr.dwell.items() if plane == "axial" and 0 <= s < nz and ms >= visit_ms)
    return round(100.0 * seen / max(1, nz), 1)


def sample_voxel(s: Sample) -> tuple[int, int, int] | None:
    """(z, y, x) index of a cursor sample, by plane (see scoring.volume.mark_voxel)."""
    if s.x is None or s.y is None:
        return None
    if s.plane == "axial":
        return s.slice, int(round(s.y)), int(round(s.x))
    if s.plane == "coronal":
        return int(round(s.y)), s.slice, int(round(s.x))
    return int(round(s.y)), int(round(s.x)), s.slice


def zone_dwell(tr: SliceTrace, zones: Mapping[str, np.ndarray], shape: Sequence[int]) -> dict[str, float]:
    """ms per zone. Slab thirds: time their axial slices were on screen (any cursor position); every other zone
    (organs, halves, hemispheres): time the cursor's voxel lay inside it."""
    nz, ny, nx = (int(n) for n in shape)
    out: dict[str, float] = {}
    for name, m in zones.items():
        if name in SLAB_THIRDS:
            zs = [z for z in range(nz) if m[z].any()]
            out[name] = float(sum(tr.dwell.get(("axial", z), 0.0) for z in zs))
            continue
        total = 0.0
        for s in tr.samples:
            idx = sample_voxel(s)
            if idx is None:
                continue
            z, y, x = idx
            if 0 <= z < nz and 0 <= y < ny and 0 <= x < nx and m[z, y, x]:
                total += s.ms
        out[name] = total
    return {k: round(v, 1) for k, v in out.items()}


@dataclass
class VolumeCoverage:
    visited: list[str]
    unvisited: list[str]
    first_visits: list[str]
    dwell_by_zone: dict[str, float]


def coverage(
    tr: SliceTrace, zones: Mapping[str, np.ndarray], shape: Sequence[int], review_areas: Sequence[str], visit_ms: float
) -> VolumeCoverage:
    """Review areas absent from the case (an organ this mask does not label) are dropped, not reported unvisited."""
    dwell = zone_dwell(tr, zones, shape)
    areas = [a for a in review_areas if a in zones]
    visited = [a for a in areas if dwell.get(a, 0.0) >= visit_ms]
    unvisited = [a for a in areas if a not in visited]
    # first-visit order: replay cumulative dwell per zone
    cum: dict[str, float] = {}
    order: list[str] = []
    nz, ny, nx = (int(n) for n in shape)
    skip = {"right_half", "left_half", "midline_volume"} - set(review_areas)
    for s in tr.samples:
        idx = sample_voxel(s)
        for name in zones:
            if name in order or name in skip:
                continue
            m = zones[name]
            if name in SLAB_THIRDS:
                inside = s.plane == "axial" and 0 <= s.slice < nz and m[s.slice].any()
            else:
                inside = idx is not None and all(0 <= i < n for i, n in zip(idx, (nz, ny, nx))) and bool(m[idx])
            if inside:
                cum[name] = cum.get(name, 0.0) + s.ms
                if cum[name] >= visit_ms:
                    order.append(name)
    return VolumeCoverage(visited, unvisited, order, dwell)


def zone_of_voxel(
    v: tuple[float, float, float] | None, zones: Mapping[str, np.ndarray], priority: Sequence[str]
) -> str | None:
    """First zone in `priority` containing the voxel (organs before slab thirds)."""
    if v is None:
        return None
    for name in priority:
        m = zones.get(name)
        if m is None:
            continue
        nz, ny, nx = m.shape
        x, y, z = (int(round(float(c))) for c in v)
        if 0 <= z < nz and 0 <= y < ny and 0 <= x < nx and m[z, y, x]:
            return name
    return None


def slice_direction_words(from_z: float, to_z: float) -> str | None:
    """'3 slices lower' (higher z = more inferior; slice 0 is the most superior)."""
    d = int(round(to_z - from_z))
    if d == 0:
        return None
    n = abs(d)
    return f"{n} slice{'s' if n != 1 else ''} {'lower' if d > 0 else 'higher'}"


def inplane_direction_words(
    from_xy: tuple[float, float], to_xy: tuple[float, float], shape: Sequence[int]
) -> list[str]:
    """Patient-side words: image x grows toward the patient's LEFT; image y grows posteriorly (axial)."""
    _, ny, nx = (int(n) for n in shape)
    dx = (to_xy[0] - from_xy[0]) / max(1, nx)
    dy = (to_xy[1] - from_xy[1]) / max(1, ny)
    words = []
    if abs(dx) > 0.08:
        words.append("toward the patient's left" if dx > 0 else "toward the patient's right")
    if abs(dy) > 0.08:
        words.append("more posterior" if dy > 0 else "more anterior")
    return words
