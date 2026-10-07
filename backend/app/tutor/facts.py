"""Facts builder (SPEC §8.1): the only thing Claude is allowed to believe.

Deterministic. Every human-readable string (zones, locations, sizes, relations) is produced by code here or by
the backend engines; Claude only explains them. Never states centimetres (pixel spacing is unknown).

Volumetric (CT / MR) cases add, all code-built: case.modality / body_region / provenance sentence; per finding the
slice_range, size_mm (only when the reference carries a measure), components and a relative_location that names the
zone, the patient's side and the slice range ("middle slices of the volume, patient's right, slices 6-10 of 16");
the learner's measurements and each mark's plane / slice; search.slices_viewed_pct / finding_slices_viewed; outcomes
keep size_verdict / slices_viewed, and `unmatched` marks stay in as outcomes with result unmatched.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from backend.app.tutor import vocab
from shared.contracts import (
    AttemptSubmit,
    Case,
    DebriefFacts,
    FactsCase,
    FactsFinding,
    FactsLearner,
    FactsMark,
    FactsMeasurement,
    FactsPattern,
    FactsSearch,
    Finding,
    Outcome,
    SpatialRelation,
)

PROJECTION = "frontal; PA vs AP not recorded"
MODALITY_NAMES = {"ct": "CT", "mr": "MR"}
# Size words from mask area / image area. Presentation buckets only (not used for scoring).
SIZE_SMALL_MAX = 0.002  # < 0.2% of the image
SIZE_MEDIUM_MAX = 0.02  # < 2% of the image
# Difficulty words from the finding's difficulty prior (z-score scale, SPEC §4.5).
DIFFICULTY_EASY_MAX = -0.5
DIFFICULTY_HARD_MIN = 0.5


def short_id(x: str) -> str:
    return x.split("#", 1)[1] if "#" in x else x


def _fmt_pct(pct: float) -> str:
    if pct <= 0:
        return "0"
    decimals = max(0, 1 - math.floor(math.log10(pct)))
    return (f"{pct:.{decimals}f}").rstrip("0").rstrip(".")


def size_text(area_frac: float | None) -> str | None:
    if area_frac is None:
        return None
    word = "small" if area_frac < SIZE_SMALL_MAX else "medium" if area_frac < SIZE_MEDIUM_MAX else "large"
    return f"{word} (about {_fmt_pct(100.0 * area_frac)}% of the image)"


def difficulty_word(d: float | None) -> str | None:
    if d is None:
        return None
    if d <= DIFFICULTY_EASY_MAX:
        return "easy"
    if d >= DIFFICULTY_HARD_MIN:
        return "hard"
    return "moderate"


def _location_text(f: Finding, approximate: bool) -> str | None:
    text = f.relative_location or (vocab.zone_human(f.primary_zone) if f.primary_zone else None)
    if text and approximate:
        text += " (approximate)"
    return text


# --------------------------------------------------------------------------- volumetric strings (all code-built)
def n_slices(case: Case) -> int | None:
    return int(case.volume.shape[0]) if case.volume is not None else None


# Contract slice indices (slice_range, measure.slice, Mark.slice, telemetry.slice) are 0-based; EVERY human-facing
# string is 1-based, like the viewer's "Slice 8 of 28" (docs/VOLUMETRIC_PLAN.md).
HUMAN_SLICE_OFFSET = 1


def human_slice(z: int | float) -> int:
    """0-based contract slice index → the 1-based number the learner sees."""
    return int(z) + HUMAN_SLICE_OFFSET


def slice_range_text(slice_range: Sequence[int] | None, total: int | None = None) -> str | None:
    """'slices 7-11 of 16' / 'slice 9 of 16' from a 0-based contract slice_range (1-based for the learner)."""
    if not slice_range:
        return None
    z0, z1 = human_slice(slice_range[0]), human_slice(slice_range[-1])
    core = f"slice {z0}" if z0 == z1 else f"slices {z0}-{z1}"
    return f"{core} of {total}" if total else core


def side_text(side: str | None) -> str | None:
    if side in ("right", "left"):
        return f"patient's {side}"
    if side == "midline":
        return "midline"
    if side == "bilateral":
        return "both sides"
    return None


def projection_text(case: Case) -> str:
    if not vocab.is_volumetric(case.modality):
        return PROJECTION
    name = MODALITY_NAMES.get(case.modality, case.modality.upper())
    seq = f" {case.volume.sequence}" if case.volume is not None and case.volume.sequence else ""
    region = f" of the {case.body_region}" if case.body_region else ""
    total = n_slices(case)
    slices = f"; {total} axial slices" if total else ""
    return f"axial {name}{seq}{region}{slices}"


def provenance_text(case: Case) -> str | None:
    """'Reference segmented by an abdominal radiologist (single reader) (Medical Segmentation Decathlon, Task07
    Pancreas)': the badge from config/provenance.yaml, one sentence, code-built."""
    if case.provenance is None:
        return None
    return f"Reference segmented by {case.provenance.segmented_by} ({case.provenance.dataset})"


def _badge_sentence(badge: Any) -> str | None:
    """'Segmented by X (dataset)' (Provenance.badge) → 'Reference segmented by X (dataset)'."""
    if not badge or not isinstance(badge, str):
        return None
    return badge if badge.lower().startswith("reference ") else f"Reference {badge[:1].lower()}{badge[1:]}"


def volume_location_text(f: Finding, case: Case) -> str | None:
    """Zone (organ or slab third), patient's side, slice range: the only location words a volumetric debrief may
    use. Zone ids name the patient's side (CLAUDE.md non-negotiable 3)."""
    parts: list[str] = []
    base = f.relative_location or (vocab.zone_human(f.primary_zone) if f.primary_zone else None)
    if base:
        parts.append(base.rstrip("."))
    side = side_text(f.side)
    if side and (not base or side.split()[-1] not in base.lower()):
        parts.append(side)
    sr = slice_range_text(f.slice_range, n_slices(case))
    if sr:
        parts.append(sr)
    return ", ".join(parts) if parts else None


def size_mm_text(size_mm: float | None, measure_slice: int | None = None) -> str | None:
    if size_mm is None:
        return None
    s = f"{size_mm:g} mm long axis"
    return f"{s} on slice {human_slice(measure_slice)}" if measure_slice is not None else s


def _volume_facts_finding(f: Finding, case: Case, signs_drawn: list[str] | None = None) -> FactsFinding:
    size_mm = round(float(f.measure.long_mm), 1) if f.measure is not None else None
    return FactsFinding(
        signs_drawn=signs_drawn or None,
        id=f.short_id,
        label=f.label,
        display=vocab.display(f.label),
        kind=f.kind,
        side=f.side,
        primary_zone=f.primary_zone,
        zones=list(f.zones),
        relative_location=volume_location_text(f, case),
        size=size_mm_text(size_mm, f.measure.slice if f.measure is not None else None),
        difficulty=difficulty_word(f.difficulty) if f.kind == "focal" else None,  # type: ignore[arg-type]
        zones_approximate=case.zones_approximate,
        ctr=None,
        slice_range=[int(f.slice_range[0]), int(f.slice_range[1])] if f.slice_range else None,
        size_mm=size_mm,
        components=[c.name for c in f.components] if f.components else None,
    )


def facts_finding(f: Finding, case: Case, signs_drawn: list[str] | None = None) -> FactsFinding:
    """`signs_drawn`: names of the sign annotations drawn for this finding on the reveal (code-built, see
    backend/app/signs.py); the debrief may tell the reader to look at them by name."""
    if vocab.is_volumetric(case.modality):
        return _volume_facts_finding(f, case, signs_drawn)
    focal = f.kind == "focal"
    ctr = case.cardiothoracic_ratio if f.label == "cardiomegaly" else None
    return FactsFinding(
        signs_drawn=signs_drawn or None,
        id=f.short_id,
        label=f.label,
        display=vocab.display(f.label),
        kind=f.kind,
        side=f.side,
        primary_zone=f.primary_zone,
        zones=list(f.zones),
        relative_location=_location_text(
            f, case.zones_approximate
        ),  # code-built; patterns too (e.g. cardiac silhouette)
        size=size_text(f.area_frac) if focal else None,
        difficulty=difficulty_word(f.difficulty) if focal else None,  # type: ignore[arg-type]
        zones_approximate=case.zones_approximate,
        ctr=round(float(ctr), 2) if ctr is not None else None,
    )


def _norm_outcome(o: Outcome | Mapping[str, Any]) -> Outcome:
    o = o if isinstance(o, Outcome) else Outcome.model_validate(dict(o))
    upd: dict[str, Any] = {"target": short_id(o.target)}
    if o.matched:
        upd["matched"] = short_id(o.matched)
    return o.model_copy(update=upd)


def _norm_relation(r: Any) -> SpatialRelation | None:
    if isinstance(r, SpatialRelation):
        return r
    d = r if isinstance(r, Mapping) else (r.model_dump() if hasattr(r, "model_dump") else dict(vars(r)))
    src = d.get("from", d.get("from_", d.get("from_mark")))
    dst = d.get("to", d.get("to_finding"))
    text = d.get("text")
    if not src or not dst or not text:
        return None
    return SpatialRelation.model_validate({"from": short_id(str(src)), "to": short_id(str(dst)), "text": str(text)})


def _norm_search(s: Any) -> FactsSearch:
    if isinstance(s, FactsSearch):
        return s
    d = s if isinstance(s, Mapping) else s.model_dump()
    pct = d.get("slices_viewed_pct")
    fsv = d.get("finding_slices_viewed")
    return FactsSearch(
        lung_coverage_pct=float(round(float(d.get("lung_coverage_pct") or 0.0))),
        unvisited_review_areas=list(d.get("unvisited_review_areas") or []),
        first_visits=list(d.get("first_visits") or []),
        zoom_used=bool(d.get("zoom_used", False)),
        loupe_used=bool(d.get("loupe_used", False)),
        slices_viewed_pct=float(round(float(pct))) if pct is not None else None,
        finding_slices_viewed={short_id(str(k)): bool(v) for k, v in fsv.items()} if fsv else None,
    )


def _time_to_submit_s(submit: AttemptSubmit) -> float:
    try:
        t0 = datetime.fromisoformat(submit.client_timing.shown_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(submit.client_timing.submitted_at.replace("Z", "+00:00"))
        secs = (t1 - t0).total_seconds()
        if secs >= 0:
            return round(secs, 1)
    except (ValueError, TypeError):
        pass
    if submit.telemetry:
        return round(max(e.t for e in submit.telemetry) / 1000.0, 1)
    return 0.0


def involved_labels(case: Case, submit: AttemptSubmit) -> list[str]:
    """Ground-truth labels in finding order, then learner labels (marks, patterns). Deduplicated."""
    known = set(vocab.labels())
    seq: Iterable[str] = (
        [f.label for f in case.findings] + [m.label for m in submit.marks] + [p.label for p in submit.patterns]
    )
    out: list[str] = []
    for lab in seq:
        if lab in known and lab not in out:
            out.append(lab)
    return out


def build_facts(
    *,
    case: Case,
    submit: AttemptSubmit,
    outcomes: list[Outcome],
    spatial_relations: list[Any],
    search: Any,
    mark_zones: Mapping[str, str | None] | None = None,
    level: str = "MS2",
    history: Mapping[str, Any] | None = None,
    volume: Mapping[str, Any] | None = None,
    signs_drawn: Mapping[str, Sequence[str]] | None = None,
) -> DebriefFacts:
    """Assemble DebriefFacts (shared/schemas/debrief_facts.json) for one submitted attempt.

    `volume`: tutor_bridge.volume_facts(...) for CT / MR cases (BACKEND→TUTOR). Everything in it is also on the
    contract objects, which this builder reads directly; it is used only to fill a provenance badge or a size the
    case object lacks, so the two never disagree.
    `signs_drawn`: {finding id: [sign names]} drawn on the reveal (backend/app/signs.py) → FactsFinding.signs_drawn."""
    outs = [_norm_outcome(o) for o in outcomes]
    drawn = {short_id(str(k)): [str(x) for x in v] for k, v in (signs_drawn or {}).items()}
    vol = dict(volume or {})
    mark_zones = {short_id(k): v for k, v in (mark_zones or {}).items()}
    outcome_zone = {o.target: o.zone for o in outs if o.target.startswith("M")}
    marks = [
        FactsMark(
            id=short_id(m.mark_id),
            label=m.label,
            confidence=int(m.confidence),
            zone=mark_zones.get(short_id(m.mark_id)) or outcome_zone.get(short_id(m.mark_id)),
            plane=m.plane,
            slice=int(m.slice) if m.slice is not None else None,
        )
        for m in submit.marks
    ]
    measurements = [
        FactsMeasurement(mark_id=short_id(x.mark_id), long_mm=round(float(x.long_mm), 1), plane=x.plane)
        for x in submit.measurements
    ]
    labels = involved_labels(case, submit)
    hist = dict(history or {})
    hist = {k: v for k, v in hist.items() if k in labels or k == "recent_miss_types"}
    rels = [r for r in (_norm_relation(x) for x in spatial_relations or []) if r is not None]
    return DebriefFacts(
        case=FactsCase(
            case_id=case.case_id,
            is_normal=case.is_normal,
            projection=projection_text(case),
            pixel_spacing_mm=case.pixel_spacing_mm,
            findings=[facts_finding(f, case, drawn.get(f.short_id)) for f in case.findings],
            modality=case.modality,
            body_region=case.body_region,
            provenance=provenance_text(case) or _badge_sentence(vol.get("provenance")),
        ),
        learner=FactsLearner(
            level=level,
            declared_normal=submit.declared_normal,
            normal_confidence=int(submit.normal_confidence) if submit.normal_confidence is not None else None,
            hints_used=submit.hints_used,
            time_to_submit_s=_time_to_submit_s(submit),
            marks=marks,
            pattern_selections=[FactsPattern(label=p.label, confidence=int(p.confidence)) for p in submit.patterns],
            measurements=measurements,
        ),
        outcomes=outs,
        spatial_relations=rels,
        search=_norm_search(search),
        history=hist,
        teaching_cards=labels,
    )


def facts_json(facts: DebriefFacts) -> str:
    """Canonical JSON for the prompt (stable key order, no nulls dropped)."""
    return facts.model_dump_json(by_alias=True)
