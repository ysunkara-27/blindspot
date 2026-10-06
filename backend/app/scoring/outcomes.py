"""SPEC §6.3 outcomes per focal finding, pattern finding and mark."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from backend.app.scoring.matching import MatchResult
from backend.app.search.misstype import miss_type
from shared.contracts import Finding, Mark, Outcome, PatternSelection


def focal_outcomes(
    focal: Sequence[Finding],
    marks: Sequence[Mark],
    m: MatchResult,
    dwell_by_finding: Mapping[str, float],
    miss_cfg: dict,
) -> list[Outcome]:
    by_id = {mk.mark_id: mk for mk in marks}
    out: list[Outcome] = []
    for f in focal:
        fid = f.short_id
        dwell = round(float(dwell_by_finding.get(fid, 0.0)), 1)
        mid = m.mark_for(fid)
        if mid is None:
            out.append(Outcome(target=fid, result=miss_type(dwell, miss_cfg), dwell_ms=dwell, zone=f.primary_zone))
            continue
        mk = by_id[mid]
        res = "found" if mk.label == f.label else "mislabeled"
        out.append(
            Outcome(
                target=fid,
                result=res,
                dwell_ms=dwell,
                zone=f.primary_zone,
                matched=mid,
                learner_label=None if res == "found" else mk.label,
            )
        )
    return out


def pattern_outcomes(patterns: Sequence[Finding], selections: Sequence[PatternSelection]) -> list[Outcome]:
    chosen = {p.label for p in selections}
    gt = {f.label for f in patterns}
    out = [
        Outcome(target=f.short_id, result="pattern_found" if f.label in chosen else "pattern_missed") for f in patterns
    ]
    for lab in sorted(chosen - gt):
        out.append(Outcome(target=lab, result="pattern_false", learner_label=lab))
    return out


def mark_outcomes(marks: Sequence[Mark], m: MatchResult, mark_zone: Mapping[str, str | None]) -> list[Outcome]:
    out: list[Outcome] = []
    for mk in marks:
        z = mark_zone.get(mk.mark_id)
        if mk.mark_id in m.pairs:
            out.append(
                Outcome(
                    target=mk.mark_id,
                    result="true_positive",
                    matched=m.pairs[mk.mark_id],
                    zone=z,
                    learner_label=mk.label,
                )
            )
        elif mk.mark_id in m.duplicates:
            out.append(
                Outcome(
                    target=mk.mark_id,
                    result="duplicate",
                    matched=m.duplicates[mk.mark_id],
                    zone=z,
                    learner_label=mk.label,
                )
            )
        else:
            out.append(Outcome(target=mk.mark_id, result="false_positive", zone=z, learner_label=mk.label))
    return out


def normal_outcome(declared_normal: bool, marks: Sequence[Mark]) -> list[Outcome]:
    if declared_normal and not marks:
        return [Outcome(target="case", result="true_negative")]
    return []
