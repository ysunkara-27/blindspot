"""Volumetric (CT / MR) glue for the services: window presets, URLs the API hands out, submit validation.

Window presets are display defaults (not ground truth). Model/threshold config lives in config/*.yaml; these presets
are viewer conveniences fixed by docs/VOLUMETRIC_PLAN.md.
"""

from __future__ import annotations

import math

from backend.app.settings import get_settings
from shared.contracts import AttemptSubmit, Case, NextCaseVolume, VolumePreset

CT_PRESETS = (
    ("Lung", -600.0, 1500.0),
    ("Mediastinum", 50.0, 400.0),
    ("Abdomen", 60.0, 400.0),
    ("Liver", 80.0, 150.0),
    ("Bone", 400.0, 1800.0),
    ("Brain", 40.0, 80.0),
)


def presets(case: Case) -> list[VolumePreset]:
    if case.volume is None:
        return []
    if case.modality == "ct":
        return [VolumePreset(name=n, wc=wc, ww=ww) for n, wc, ww in CT_PRESETS]
    return [VolumePreset(name="Default", wc=case.volume.window.wc, ww=case.volume.window.ww)]


def volume_url(case_id: str) -> str:
    return f"{get_settings().api_prefix}/cases/{case_id}/volume"


def maskvol_url(attempt_id: str) -> str:
    return f"{get_settings().api_prefix}/attempts/{attempt_id}/maskvol"


def next_case_volume(case: Case) -> NextCaseVolume | None:
    """Voxels only: shape, spacing, window, data URL, presets. Never labels, mask path or findings."""
    v = case.volume
    if v is None:
        return None
    return NextCaseVolume(
        shape=[int(n) for n in v.shape],
        spacing=[float(s) for s in v.spacing],
        window=v.window,
        data_url=volume_url(case.case_id),
        sequence=v.sequence,
        presets=presets(case),
    )


def provenance_badge(case: Case) -> dict | None:
    """The badge dict shown on every case (dataset provenance; not ground truth about the image)."""
    if case.provenance is None:
        return None
    d = case.provenance.model_dump()
    d["badge"] = case.provenance.badge
    return d


def _plane_extent(plane: str | None, shape: tuple[int, int, int]) -> tuple[int, int]:
    """(width, height) of the displayed plane in voxels."""
    nz, ny, nx = shape
    if plane == "coronal":
        return nx, nz
    if plane == "sagittal":
        return ny, nz
    return nx, ny


def _slice_count(plane: str | None, shape: tuple[int, int, int]) -> int:
    nz, ny, nx = shape
    return ny if plane == "coronal" else nx if plane == "sagittal" else nz


def submit_problems_volume(body: AttemptSubmit, case: Case, max_marks: int) -> list[str]:
    """Pure check of a volumetric submit. Marks need a voxel or a (plane, slice); coordinates must be finite and
    inside the volume; measurements must reference a mark. Empty list = valid."""
    assert case.volume is not None
    shape = tuple(int(n) for n in case.volume.shape)
    errs: list[str] = []
    if len(body.marks) > max_marks:
        errs.append(f"too many marks ({len(body.marks)} > {max_marks})")
    seen: set[str] = set()
    for m in body.marks:
        if m.mark_id in seen:
            errs.append(f"duplicate mark_id {m.mark_id!r}")
        seen.add(m.mark_id)
        vals = [m.x, m.y, *(m.voxel or ())]
        if any(not math.isfinite(float(v)) for v in vals):
            errs.append(f"mark {m.mark_id!r} has non-finite coordinates")
            continue
        if m.voxel is None and m.slice is None:
            errs.append(f"mark {m.mark_id!r} needs a voxel or a slice on a volumetric case")
            continue
        if m.voxel is not None:
            x, y, z = m.voxel
            nz, ny, nx = shape
            if not (0.0 <= x <= nx and 0.0 <= y <= ny and 0.0 <= z <= nz - 1):
                errs.append(f"mark {m.mark_id!r} voxel ({x:g}, {y:g}, {z:g}) is outside the volume {list(shape)}")
        else:
            w, h = _plane_extent(m.plane, shape)
            n = _slice_count(m.plane, shape)
            if not (0.0 <= m.x <= w and 0.0 <= m.y <= h):
                errs.append(f"mark {m.mark_id!r} is outside the {m.plane or 'axial'} plane ({m.x:g}, {m.y:g})")
            if not (0 <= int(m.slice) < n):  # type: ignore[arg-type]
                errs.append(f"mark {m.mark_id!r} slice {m.slice} is outside the {m.plane or 'axial'} range 0..{n - 1}")
    for ms in body.measurements:
        if ms.mark_id not in seen:
            errs.append(f"measurement for unknown mark {ms.mark_id!r}")
        if not math.isfinite(float(ms.long_mm)):
            errs.append(f"measurement for {ms.mark_id!r} is not finite")
    for i, e in enumerate(body.telemetry):
        vals = [e.t, e.zoom, e.x, e.y, *(e.vp or ())]
        if any(v is not None and not math.isfinite(v) for v in vals):
            errs.append(f"telemetry event {i} has non-finite values")
            break
    if body.normal_confidence is not None and not math.isfinite(float(body.normal_confidence)):
        errs.append("normal_confidence is not finite")
    return errs
