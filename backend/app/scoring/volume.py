"""Volumetric (CT / MR) hit test and size verdicts — docs/VOLUMETRIC_PLAN.md, config/scoring.yaml `volumetric`.

Pure functions over numpy arrays (z, y, x). Voxel coordinates are (x, y, z) floats as in the contract (Mark.voxel).

Hit test for a mark against ONE finding:
1. the mark's own voxel (rounded) lies in the finding's component → hit;
2. it lies in a DIFFERENT labelled structure (an organ, or another finding) → NO rescue by the tolerance
   (`cross_label_rescue: false`): the mark is unmatched if that structure is anatomy, or hits the other finding;
3. it lies in unlabelled tissue → hit if any voxel of the finding is within the tolerance ellipse in-plane
   (τ = tolerance_frac · larger in-plane FOV in mm, converted to voxels per axis) and within ±slice_window slices.

Marks that hit nothing are `unmatched` (reported, never penalised): public CT sets do not label every lesion.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

from shared.contracts import Mark, Measurement, SizeVerdict

Voxel = tuple[float, float, float]


# ------------------------------------------------------------------ geometry helpers
def mark_voxel(mark: Mark) -> Voxel | None:
    """(x, y, z) of a mark. `voxel` wins; else derived from plane + slice + in-plane (x, y):
    axial (x, y) → (x, y, slice) · coronal (x, z) → (x, slice, y) · sagittal (y, z) → (slice, x, y)."""
    if mark.voxel is not None:
        return (float(mark.voxel[0]), float(mark.voxel[1]), float(mark.voxel[2]))
    if mark.slice is None:
        return None
    plane = mark.plane or "axial"
    s = float(mark.slice)
    if plane == "axial":
        return (float(mark.x), float(mark.y), s)
    if plane == "coronal":
        return (float(mark.x), s, float(mark.y))
    return (s, float(mark.x), float(mark.y))


def voxel_index(v: Voxel, shape: Sequence[int]) -> tuple[int, int, int] | None:
    """(z, y, x) integer index at round(voxel), or None when outside the volume."""
    nz, ny, nx = (int(n) for n in shape)
    x, y, z = (int(round(float(c))) for c in v)
    if 0 <= z < nz and 0 <= y < ny and 0 <= x < nx:
        return z, y, x
    return None


def tolerance_mm(shape: Sequence[int], spacing: Sequence[float], cfg: Mapping) -> float:
    """τ in mm = tolerance_frac · max(in-plane FOV): FOV = ny·sy, nx·sx."""
    _, ny, nx = (int(n) for n in shape)
    _, sy, sx = (float(s) for s in spacing)
    return float(cfg["hit"]["tolerance_frac"]) * max(ny * sy, nx * sx)


def tolerance_voxels(shape: Sequence[int], spacing: Sequence[float], cfg: Mapping) -> tuple[int, float, float]:
    """(slice window in slices, τ in y voxels, τ in x voxels)."""
    tau = tolerance_mm(shape, spacing, cfg)
    _, sy, sx = (float(s) for s in spacing)
    return int(cfg["hit"]["slice_window"]), tau / sy, tau / sx


def structure_at(mv: np.ndarray, v: Voxel) -> int:
    """Mask label value at round(voxel); 0 outside the volume."""
    idx = voxel_index(v, mv.shape)
    return int(mv[idx]) if idx is not None else 0


def hits_volume(
    v: Voxel,
    finding_mask: np.ndarray,
    mv: np.ndarray,
    slice_window: int,
    tau_y: float,
    tau_x: float,
    cross_label_rescue: bool = False,
) -> bool:
    """Pure hit test (module docstring). `finding_mask` = the finding's own component; `mv` = the label volume."""
    idx = voxel_index(v, mv.shape)
    if idx is None:
        return False
    if finding_mask[idx]:
        return True
    if int(mv[idx]) != 0 and not cross_label_rescue:
        return False  # squarely inside a different labelled structure
    z, y, x = idx
    nz, ny, nx = mv.shape
    ry, rx = max(0, int(math.floor(tau_y))), max(0, int(math.floor(tau_x)))
    z0, z1 = max(0, z - slice_window), min(nz, z + slice_window + 1)
    y0, y1 = max(0, y - ry), min(ny, y + ry + 1)
    x0, x1 = max(0, x - rx), min(nx, x + rx + 1)
    block = finding_mask[z0:z1, y0:y1, x0:x1]
    if not block.any():
        return False
    yy, xx = np.mgrid[y0:y1, x0:x1]
    ty, tx = max(tau_y, 1e-9), max(tau_x, 1e-9)
    ellipse = ((yy - y) / ty) ** 2 + ((xx - x) / tx) ** 2 <= 1.0
    return bool((block & ellipse[None, :, :]).any())


# ------------------------------------------------------------------ size verdicts
def size_verdict(your_mm: float, reference_mm: float, cfg: Mapping, plane: str | None = None) -> SizeVerdict:
    """Correct when |your − reference| ≤ max(tolerance_mm, tolerance_frac · reference)."""
    diff = float(your_mm) - float(reference_mm)
    tol = max(float(cfg["size"]["tolerance_mm"]), float(cfg["size"]["tolerance_frac"]) * float(reference_mm))
    pct = (abs(diff) / float(reference_mm) * 100.0) if reference_mm > 0 else (0.0 if diff == 0 else 100.0)
    return SizeVerdict(
        your_mm=round(float(your_mm), 1),
        reference_mm=round(float(reference_mm), 1),
        diff_mm=round(diff, 1),
        diff_pct=round(pct, 1),
        ok=abs(diff) <= tol + 1e-9,
        plane=plane,
    )


def size_verdicts(
    pairs: Mapping[str, str],
    findings_by_id: Mapping[str, object],
    measurements: Sequence[Measurement],
    cfg: Mapping,
) -> dict[str, SizeVerdict]:
    """{finding_id: verdict} for every matched mass-like finding (config size.ask_for_labels) that carries a
    reference `measure` and whose matching mark has a learner measurement."""
    ask = set(cfg["size"].get("ask_for_labels") or [])
    by_mark = {m.mark_id: m for m in measurements}
    out: dict[str, SizeVerdict] = {}
    for mark_id, fid in pairs.items():
        f = findings_by_id.get(fid)
        meas = by_mark.get(mark_id)
        if f is None or meas is None or getattr(f, "label", None) not in ask or getattr(f, "measure", None) is None:
            continue
        out[fid] = size_verdict(meas.long_mm, f.measure.long_mm, cfg, plane=meas.plane)  # type: ignore[attr-defined]
    return out
