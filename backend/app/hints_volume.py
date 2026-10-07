"""Deterministic hint ladder for CT / MR cases (SPEC §8.8 shape, volumetric data). No LLM.

`hint_data()` is also what the tutor's hints.py receives (BACKEND→TUTOR in docs/PROGRESS.md); `fallback_hint()` is
the text used when the tutor module has no `hint_volume`. One template per level, symmetric for normal and abnormal
scans, so the wording alone cannot tell the learner whether the scan is normal:

H1  "You haven't looked at the upper slices of the volume or the pancreas yet."  (unvisited review areas by slice
    dwell; at most 3, least-dwelt first, listed in config order)  /  "Scroll through every slice again, top to bottom."
H2  "Look again at the patient's right side, in the pancreas."  (side + organ/slab of the hardest unmarked finding;
    on a normal scan, or when everything is marked: the least-dwelt review area, per-case hash tie-break)
H3  "In the pancreas, check for this sign: <first key sign of the teaching card>."
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from backend.app import config
from backend.app.cases import CaseRepository
from backend.app.scoring.volume import hits_volume, mark_voxel, tolerance_voxels
from backend.app.search.volume import coverage, slice_trace, slices_viewed_pct
from shared.contracts import Case, Finding, Mark, TelemetryEvent

H1_ALL = "Scroll through every slice again, top to bottom."
H1_MAX = 3
GENERIC_SIGN = "an edge, density or signal that the surrounding tissue does not explain"
_HALVES = {"right_half": "right", "left_half": "left", "brain_right": "right", "brain_left": "left"}


def _rank(case_id: str, key: str) -> str:
    return hashlib.sha256(f"{case_id}|{key}".encode()).hexdigest()


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def unmarked_findings(case: Case, marks: Sequence[Mark], repo: CaseRepository) -> list[Finding]:
    if case.volume is None:
        return []
    vc = config.volumetric_cfg()
    mv = repo.maskvol(case.case_id)
    if mv is None:
        return [f for f in case.findings if f.kind == "focal"]
    sw, ty, tx = tolerance_voxels(case.volume.shape, case.volume.spacing, vc)
    out = []
    for f in case.findings:
        if f.kind != "focal":
            continue
        fm = repo.finding_volmask(case.case_id, f.finding_id)
        vox = [mark_voxel(m) for m in marks]
        if fm is None or not any(v is not None and hits_volume(v, fm, mv, sw, ty, tx) for v in vox):
            out.append(f)
    return out


def hardest(findings: Sequence[Finding]) -> Finding | None:
    """Highest difficulty prior, else hardest zone (config hardness), else the first."""
    if not findings:
        return None
    zc = config.volumetric_zones_cfg()
    return max(
        findings,
        key=lambda f: (
            f.difficulty if f.difficulty is not None else -1e9,
            zc.get(f.primary_zone or "", {}).get("hardness", 0.0),
        ),
    )


def hint_data(
    case: Case, marks: Sequence[Mark], telemetry: Sequence[TelemetryEvent], repo: CaseRepository
) -> dict[str, Any]:
    """Everything a hint needs, computed by code: search state (never truth) plus, separately, the hardest unmarked
    finding (truth: used only by H2/H3)."""
    assert case.volume is not None
    sc = config.scoring()
    vc = config.volumetric_cfg()
    shape = tuple(int(n) for n in case.volume.shape)
    tr = slice_trace(telemetry, sc["dwell"])
    zones = repo.volume_zones(case.case_id)
    areas = config.volumetric_review_areas(case.body_region)
    cov = coverage(tr, zones, shape, areas, float(vc["dwell"]["visit_ms"]))
    un = unmarked_findings(case, marks, repo)
    h = hardest(un)
    return {
        "modality": case.modality,
        "body_region": case.body_region,
        "review_areas": [a for a in areas if a in zones],
        "unvisited_review_areas": cov.unvisited,
        "dwell_by_zone": cov.dwell_by_zone,
        "slices_viewed_pct": slices_viewed_pct(tr, shape[0], float(vc["dwell"]["visit_ms"])),
        "n_unmarked": len(un),
        "hardest_unmarked": None
        if h is None
        else {
            "finding_id": h.short_id,
            "label": h.label,
            "side": h.side,
            "zone": h.primary_zone,
            "zones": list(h.zones),
        },
    }


def h1_text(data: dict[str, Any]) -> str:
    un = list(data.get("unvisited_review_areas") or [])
    if not un:
        return H1_ALL
    dwell = data.get("dwell_by_zone") or {}
    order = {z: i for i, z in enumerate(data.get("review_areas") or un)}
    pick = sorted(un, key=lambda z: (float(dwell.get(z, 0.0)), order.get(z, 99)))[:H1_MAX]
    pick = sorted(pick, key=lambda z: order.get(z, 99))
    return "You haven't looked at " + _join(["the " + config.zone_human(z) for z in pick]) + " yet."


def _focus_zone(case: Case, data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """(zone, side, label) for H2/H3: the hardest unmarked finding, else the least-dwelt review area."""
    h = data.get("hardest_unmarked")
    if h:
        zone = h.get("zone") or next((z for z in h.get("zones") or []), None)
        return zone, h.get("side"), h.get("label")
    areas = list(data.get("review_areas") or [])
    if not areas:
        return None, None, None
    dwell = data.get("dwell_by_zone") or {}
    zone = min(areas, key=lambda z: (float(dwell.get(z, 0.0)), _rank(case.case_id, z)))
    side = _HALVES.get(zone)
    return zone, side, None


def h2_text(zone: str, side: str | None) -> str:
    where = config.zone_human(zone)
    if side in ("right", "left"):
        return f"Look again at the patient's {side} side, in the {where}."
    return f"Look again at the {where}."


def _first_sign(label: str | None, case: Case) -> str:
    from backend.app import tutor_bridge

    cards = tutor_bridge.load_cards()
    if label is None:
        opts = [lab for lab in config.learner_options(case.modality) if lab in cards]
        label = min(opts, key=lambda lab: _rank(case.case_id, lab)) if opts else None
    card = cards.get(label) if label else None
    return card.key_signs[0] if card and card.key_signs else GENERIC_SIGN


def h3_text(zone: str, sign: str) -> str:
    s = sign.strip().rstrip(".")
    s = s[0].lower() + s[1:] if s else GENERIC_SIGN
    return f"In the {config.zone_human(zone)}, check for this sign: {s}."


def fallback_hint(level: int, case: Case, data: dict[str, Any], previous: Sequence[Any] | None = None) -> str:
    level = min(3, max(1, int(level)))
    if level == 1:
        return h1_text(data)
    zone, side, label = _focus_zone(case, data)
    if zone is None:
        return H1_ALL
    if level == 2:
        return h2_text(zone, side)
    return h3_text(zone, _first_sign(label, case))
