"""Volumetric (CT / MR) scenarios for tutor tests, built on the synthetic MSD-style fixtures
(pipeline/tests/fixtures/synthetic/cases_msd.jsonl). Synthetic, labeled synthetic, never shown in the UI.

Outcomes are hand-built here the way backend/app/tutor_bridge.py will pass them (Outcome rows with size_verdict /
slices_viewed, `unmatched` marks, FactsSearch with slices_viewed_pct / finding_slices_viewed).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from backend.app.settings import REPO_ROOT
from backend.app.tutor.facts import build_facts
from shared.contracts import (
    AttemptSubmit,
    Case,
    ClientTiming,
    DebriefFacts,
    Mark,
    Measurement,
    Outcome,
    TelemetryEvent,
)

FIXTURES = REPO_ROOT / "pipeline" / "tests" / "fixtures" / "synthetic"


@lru_cache
def vol_cases() -> dict[str, Case]:
    out = {}
    for ln in (FIXTURES / "cases_msd.jsonl").read_text().splitlines():
        if ln.strip():
            c = Case.model_validate_json(ln)
            out[c.case_id] = c
    return out


def vmark(mid: str, x: float, y: float, z: int, label: str, conf: int = 3) -> Mark:
    return Mark(mark_id=mid, x=x, y=y, label=label, confidence=conf, plane="axial", slice=z, voxel=(x, y, float(z)))  # type: ignore[arg-type]


def vsubmit(
    marks: list[Mark] | None = None,
    *,
    declared_normal: bool = False,
    normal_confidence: int | None = None,
    measurements: list[Measurement] | None = None,
    telemetry: list[TelemetryEvent] | None = None,
) -> AttemptSubmit:
    return AttemptSubmit(
        marks=marks or [],
        patterns=[],
        declared_normal=declared_normal,
        normal_confidence=normal_confidence,  # type: ignore[arg-type]
        telemetry=telemetry or [],
        hints_used=0,
        client_timing=ClientTiming(shown_at="2026-10-06T22:00:00Z", submitted_at="2026-10-06T22:01:05Z"),
        measurements=measurements or [],
    )


def vsearch(
    unvisited: list[str] | None = None,
    *,
    slices_viewed_pct: float = 62.5,
    finding_slices_viewed: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "lung_coverage_pct": 0.0,
        "unvisited_review_areas": ["superior_slab"] if unvisited is None else unvisited,
        "visited_review_areas": [],
        "first_visits": ["mid_slab"],
        "zoom_used": False,
        "loupe_used": False,
        "slices_viewed_pct": slices_viewed_pct,
        "finding_slices_viewed": finding_slices_viewed or {},
    }


def voc(target: str, result: str, **kw: Any) -> Outcome:
    return Outcome(target=target, result=result, **kw)  # type: ignore[arg-type]


def verdict(your_mm: float, reference_mm: float, ok: bool) -> dict[str, Any]:
    diff = round(your_mm - reference_mm, 1)
    return {
        "your_mm": your_mm,
        "reference_mm": reference_mm,
        "diff_mm": diff,
        "diff_pct": round(100.0 * diff / reference_mm, 1),
        "ok": ok,
        "plane": "axial",
    }


Scenario = tuple[Case, AttemptSubmit, list[Outcome], list[dict[str, str]], dict[str, Any]]


def _s_found() -> Scenario:  # pancreatic tumour, marked on its slice, measured within tolerance
    c = vol_cases()["vol_001"]
    m = vmark("M1", 24, 36, 8, "pancreatic_tumour", 4)
    meas = [Measurement(mark_id="M1", long_mm=12.0, plane="axial", slice=8)]
    outs = [
        voc(
            "F1",
            "found",
            dwell_ms=2600,
            zone="mid_slab",
            matched="M1",
            slices_viewed=True,
            size_verdict=verdict(12.0, 13.5, True),
        ),
        voc("M1", "true_positive", matched="F1", zone="mid_slab", learner_label="pancreatic_tumour"),
    ]
    return c, vsubmit([m], measurements=meas), outs, [], vsearch([], finding_slices_viewed={"F1": True})


def _s_found_size_off() -> Scenario:  # found, measured 25 % too small
    c = vol_cases()["vol_001"]
    m = vmark("M1", 24, 36, 8, "pancreatic_tumour", 5)
    meas = [Measurement(mark_id="M1", long_mm=10.0, plane="axial", slice=8)]
    outs = [
        voc(
            "F1",
            "found",
            dwell_ms=2600,
            zone="mid_slab",
            matched="M1",
            slices_viewed=True,
            size_verdict=verdict(10.0, 13.5, False),
        ),
        voc("M1", "true_positive", matched="F1", zone="mid_slab", learner_label="pancreatic_tumour"),
    ]
    return c, vsubmit([m], measurements=meas), outs, [], vsearch([], finding_slices_viewed={"F1": True})


def _s_missed_search() -> Scenario:  # never scrolled to slices 6-10; called it normal
    c = vol_cases()["vol_001"]
    outs = [voc("F1", "missed_search", dwell_ms=0, zone="mid_slab", slices_viewed=False)]
    srch = vsearch(
        ["superior_slab", "mid_slab", "pancreas"], slices_viewed_pct=31.0, finding_slices_viewed={"F1": False}
    )
    return c, vsubmit([], declared_normal=True, normal_confidence=4), outs, [], srch


def _s_missed_recognition() -> Scenario:  # liver: one found, one passed over briefly
    c = vol_cases()["vol_002"]
    m = vmark("M1", 18, 24, 5, "liver_tumour", 3)
    outs = [
        voc("F1", "found", dwell_ms=2100, zone="mid_slab", matched="M1", slices_viewed=True),
        voc("F2", "missed_recognition", dwell_ms=1200, zone="mid_slab", slices_viewed=True),
        voc("M1", "true_positive", matched="F1", zone="mid_slab", learner_label="liver_tumour"),
    ]
    return c, vsubmit([m]), outs, [], vsearch([], finding_slices_viewed={"F1": True, "F2": True})


def _s_missed_decision() -> Scenario:  # brain: lingered on the slices and judged them normal
    c = vol_cases()["vol_003"]
    outs = [voc("F1", "missed_decision", dwell_ms=4800, zone="mid_slab", slices_viewed=True)]
    srch = vsearch([], slices_viewed_pct=100.0, finding_slices_viewed={"F1": True})
    return c, vsubmit([], declared_normal=True, normal_confidence=5), outs, [], srch


def _s_mislabeled() -> Scenario:  # pancreatic tumour called liver tumour
    c = vol_cases()["vol_001"]
    m = vmark("M1", 25, 37, 8, "liver_tumour", 3)
    outs = [
        voc(
            "F1",
            "mislabeled",
            dwell_ms=1900,
            zone="mid_slab",
            matched="M1",
            learner_label="liver_tumour",
            slices_viewed=True,
        ),
        voc("M1", "true_positive", matched="F1", zone="mid_slab", learner_label="liver_tumour"),
    ]
    return c, vsubmit([m]), outs, [], vsearch([], finding_slices_viewed={"F1": True})


def _s_unmatched() -> Scenario:  # found + an extra mark the reference does not label
    c = vol_cases()["vol_001"]
    m1 = vmark("M1", 24, 36, 8, "pancreatic_tumour", 4)
    m2 = vmark("M2", 50, 12, 3, "liver_tumour", 2)
    outs = [
        voc("F1", "found", dwell_ms=2600, zone="mid_slab", matched="M1", slices_viewed=True),
        voc("M1", "true_positive", matched="F1", zone="mid_slab", learner_label="pancreatic_tumour"),
        voc("M2", "unmatched", zone="superior_slab", learner_label="liver_tumour"),
    ]
    return c, vsubmit([m1, m2]), outs, [], vsearch([], finding_slices_viewed={"F1": True})


def _s_true_negative() -> Scenario:  # lesion-free slab called normal
    c = vol_cases()["vol_004"]
    return c, vsubmit([], declared_normal=True, normal_confidence=4), [voc("case", "true_negative")], [], vsearch([])


def _s_unmatched_normal() -> Scenario:  # lesion-free slab with one unmatched mark (reported, never penalised)
    c = vol_cases()["vol_004"]
    m = vmark("M1", 30, 30, 7, "pancreatic_tumour", 2)
    outs = [voc("M1", "unmatched", zone="mid_slab", learner_label="pancreatic_tumour")]
    return c, vsubmit([m]), outs, [], vsearch(["superior_slab", "inferior_slab"], slices_viewed_pct=50.0)


VOL_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "found": _s_found,
    "found_size_off": _s_found_size_off,
    "missed_search": _s_missed_search,
    "missed_recognition": _s_missed_recognition,
    "missed_decision": _s_missed_decision,
    "mislabeled": _s_mislabeled,
    "unmatched": _s_unmatched,
    "true_negative": _s_true_negative,
    "unmatched_normal": _s_unmatched_normal,
}


def vol_facts_for(name: str, level: str = "MS2") -> tuple[DebriefFacts, Case, AttemptSubmit]:
    c, sub, outs, rels, srch = VOL_SCENARIOS[name]()
    f = build_facts(
        case=c,
        submit=sub,
        outcomes=outs,
        spatial_relations=rels,
        search=srch,
        mark_zones={o.target: o.zone for o in outs if o.target.startswith("M")},
        level=level,
        history={},
    )
    return f, c, sub
