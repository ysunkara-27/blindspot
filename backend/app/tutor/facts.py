"""Facts builder (SPEC §8.1): the only thing Claude is allowed to believe.

Deterministic. Every human-readable string (zones, locations, sizes, relations) is produced by code here or by
the backend engines; Claude only explains them. Never states centimetres (pixel spacing is unknown).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
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
    FactsPattern,
    FactsSearch,
    Finding,
    Outcome,
    SpatialRelation,
)

PROJECTION = "frontal; PA vs AP not recorded"
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


def facts_finding(f: Finding, case: Case) -> FactsFinding:
    focal = f.kind == "focal"
    ctr = case.cardiothoracic_ratio if f.label == "cardiomegaly" else None
    return FactsFinding(
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
    return FactsSearch(
        lung_coverage_pct=float(round(float(d.get("lung_coverage_pct") or 0.0))),
        unvisited_review_areas=list(d.get("unvisited_review_areas") or []),
        first_visits=list(d.get("first_visits") or []),
        zoom_used=bool(d.get("zoom_used", False)),
        loupe_used=bool(d.get("loupe_used", False)),
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
) -> DebriefFacts:
    """Assemble DebriefFacts (shared/schemas/debrief_facts.json) for one submitted attempt."""
    outs = [_norm_outcome(o) for o in outcomes]
    mark_zones = {short_id(k): v for k, v in (mark_zones or {}).items()}
    outcome_zone = {o.target: o.zone for o in outs if o.target.startswith("M")}
    marks = [
        FactsMark(
            id=short_id(m.mark_id),
            label=m.label,
            confidence=int(m.confidence),
            zone=mark_zones.get(short_id(m.mark_id)) or outcome_zone.get(short_id(m.mark_id)),
        )
        for m in submit.marks
    ]
    labels = involved_labels(case, submit)
    hist = dict(history or {})
    hist = {k: v for k, v in hist.items() if k in labels or k == "recent_miss_types"}
    rels = [r for r in (_norm_relation(x) for x in spatial_relations or []) if r is not None]
    return DebriefFacts(
        case=FactsCase(
            case_id=case.case_id,
            is_normal=case.is_normal,
            projection=PROJECTION,
            pixel_spacing_mm=case.pixel_spacing_mm,
            findings=[facts_finding(f, case) for f in case.findings],
        ),
        learner=FactsLearner(
            level=level,
            declared_normal=submit.declared_normal,
            normal_confidence=int(submit.normal_confidence) if submit.normal_confidence is not None else None,
            hints_used=submit.hints_used,
            time_to_submit_s=_time_to_submit_s(submit),
            marks=marks,
            pattern_selections=[FactsPattern(label=p.label, confidence=int(p.confidence)) for p in submit.patterns],
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
