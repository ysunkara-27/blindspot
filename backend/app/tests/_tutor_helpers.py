"""Shared builders for tutor tests: synthetic fixture cases → scenarios covering every result type.

Synthetic fixtures only (pipeline/tests/fixtures/synthetic); labeled synthetic; never shown in the UI.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.settings import REPO_ROOT
from backend.app.tutor.facts import build_facts
from shared.contracts import (
    AttemptSubmit,
    Case,
    ClientTiming,
    DebriefFacts,
    Mark,
    Outcome,
    PatternSelection,
    TelemetryEvent,
)
from shared.rle import read_zones

FIXTURES = REPO_ROOT / "pipeline" / "tests" / "fixtures" / "synthetic"
MARK_ZONE_PRIORITY = (
    "retrocardiac",
    "right_apex",
    "left_apex",
    "right_costophrenic_angle",
    "left_costophrenic_angle",
    "right_hilum",
    "left_hilum",
    "right_upper_zone",
    "right_mid_zone",
    "right_lower_zone",
    "left_upper_zone",
    "left_mid_zone",
    "left_lower_zone",
    "cardiac_silhouette",
    "mediastinum",
    "subdiaphragmatic",
)
UNVISITED_DEFAULT = ["left_apex", "retrocardiac", "right_costophrenic_angle"]


@lru_cache
def cases() -> dict[str, Case]:
    out = {}
    for ln in (FIXTURES / "cases.jsonl").read_text().splitlines():
        c = Case.model_validate_json(ln)
        out[c.case_id] = c
    return out


@lru_cache
def zones(case_id: str) -> dict[str, np.ndarray]:
    masks, _ = read_zones(FIXTURES / cases()[case_id].zones_path)
    return masks


def zone_at(case_id: str, x: float, y: float) -> str | None:
    z = zones(case_id)
    for name in MARK_ZONE_PRIORITY:
        m = z.get(name)
        if m is not None and m[int(round(y)), int(round(x))]:
            return name
    return None


def mark(mid: str, x: float, y: float, label: str, conf: int = 3) -> Mark:
    return Mark(mark_id=mid, x=x, y=y, label=label, confidence=conf)  # type: ignore[arg-type]


def submit(
    marks: list[Mark] | None = None,
    patterns: list[tuple[str, int]] | None = None,
    declared_normal: bool = False,
    normal_confidence: int | None = None,
    telemetry: list[TelemetryEvent] | None = None,
) -> AttemptSubmit:
    return AttemptSubmit(
        marks=marks or [],
        patterns=[PatternSelection(label=lab, confidence=c) for lab, c in (patterns or [])],  # type: ignore[arg-type]
        declared_normal=declared_normal,
        normal_confidence=normal_confidence,  # type: ignore[arg-type]
        telemetry=telemetry or [],
        hints_used=0,
        client_timing=ClientTiming(shown_at="2026-10-05T22:00:00Z", submitted_at="2026-10-05T22:00:41Z"),
    )


def search(unvisited: list[str] | None = None) -> dict[str, Any]:
    return {
        "lung_coverage_pct": 46.4,
        "unvisited_review_areas": UNVISITED_DEFAULT if unvisited is None else unvisited,
        "visited_review_areas": [],
        "first_visits": ["right_hilum", "left_hilum"],
        "zoom_used": True,
        "loupe_used": True,
    }


def oc(target: str, result: str, **kw: Any) -> Outcome:
    return Outcome(target=target, result=result, **kw)  # type: ignore[arg-type]


Scenario = tuple[Case, AttemptSubmit, list[Outcome], list[dict[str, str]], dict[str, Any]]


def _s_found() -> Scenario:
    c = cases()["syn_001"]
    m = mark("M1", 70, 150, "nodule", 4)
    z = zone_at(c.case_id, 70, 150)
    outs = [
        oc("F1", "found", dwell_ms=2400, zone="right_mid_zone", matched="M1"),
        oc("M1", "true_positive", matched="F1", zone=z, learner_label="nodule"),
    ]
    return c, submit([m]), outs, [], search([])


def _s_mislabeled() -> Scenario:
    c = cases()["syn_001"]
    m = mark("M1", 71, 149, "mass", 3)
    outs = [
        oc("F1", "mislabeled", dwell_ms=1800, zone="right_mid_zone", matched="M1", learner_label="mass"),
        oc("M1", "true_positive", matched="F1", zone=zone_at(c.case_id, 71, 149), learner_label="mass"),
    ]
    return c, submit([m]), outs, [], search()


def _s_missed_search() -> Scenario:
    c = cases()["syn_002"]
    m = mark("M1", 70, 45, "pneumothorax", 4)
    z = zone_at(c.case_id, 70, 45)
    outs = [
        oc("F1", "missed_search", dwell_ms=120, zone="left_upper_zone"),
        oc("M1", "false_positive", zone=z, learner_label="pneumothorax"),
    ]
    rel = [
        {
            "from": "M1",
            "to": "F1",
            "text": "The pneumothorax is in the other lung: your mark was in the right upper zone; "
            "the pneumothorax is in the left upper zone.",
        }
    ]
    return c, submit([m]), outs, rel, search(["left_apex", "left_hilum", "retrocardiac"])


def _s_missed_recognition() -> Scenario:
    c = cases()["syn_003"]
    outs = [oc("F1", "missed_recognition", dwell_ms=520, zone="right_lower_zone")]
    return c, submit([], declared_normal=True, normal_confidence=4), outs, [], search()


def _s_missed_decision() -> Scenario:
    c = cases()["syn_004"]
    m = mark("M1", 190, 185, "atelectasis", 2)
    z = zone_at(c.case_id, 190, 185)
    outs = [
        oc("F1", "missed_decision", dwell_ms=2100, zone="left_mid_zone"),
        oc("M1", "false_positive", zone=z, learner_label="atelectasis"),
    ]
    rel = [
        {
            "from_mark": "M1",
            "to_finding": "F1",
            "text": "Your mark was in the left lower zone; the consolidation is in the left mid zone, higher than "
            "your mark.",
        }
    ]
    return c, submit([m]), outs, rel, search([])


def _s_multi() -> Scenario:
    c = cases()["syn_005"]
    m = mark("M1", 80, 95, "mass", 5)
    outs = [
        oc("F1", "found", dwell_ms=3000, zone="right_upper_zone", matched="M1"),
        oc("F2", "missed_search", dwell_ms=0, zone="left_lower_zone"),
        oc("M1", "true_positive", matched="F1", zone=zone_at(c.case_id, 80, 95), learner_label="mass"),
    ]
    return c, submit([m]), outs, [], search(["left_costophrenic_angle", "retrocardiac", "subdiaphragmatic"])


def _s_bilateral() -> Scenario:
    c = cases()["syn_006"]
    m = mark("M1", 55, 215, "effusion", 4)
    outs = [
        oc("F1", "found", dwell_ms=900, zone="right_lower_zone", matched="M1"),
        oc("F2", "missed_recognition", dwell_ms=600, zone="left_lower_zone"),
        oc("M1", "true_positive", matched="F1", zone=zone_at(c.case_id, 55, 215), learner_label="effusion"),
    ]
    return c, submit([m]), outs, [], search()


def _s_pattern_found() -> Scenario:
    c = cases()["syn_007"]
    return c, submit([], patterns=[("cardiomegaly", 4)]), [oc("F1", "pattern_found")], [], search([])


def _s_pattern_missed() -> Scenario:
    c = cases()["syn_007"]
    m = mark("M1", 60, 120, "nodule", 5)
    outs = [
        oc("F1", "pattern_missed"),
        oc("M1", "false_positive", zone=zone_at(c.case_id, 60, 120), learner_label="nodule"),
    ]
    return c, submit([m]), outs, [], search()


def _s_false_positive_normal() -> Scenario:
    c = cases()["syn_008"]
    m = mark("M1", 70, 150, "nodule", 5)
    outs = [oc("M1", "false_positive", zone=zone_at(c.case_id, 70, 150), learner_label="nodule")]
    return c, submit([m]), outs, [], search()


def _s_true_negative() -> Scenario:
    c = cases()["syn_009"]
    return c, submit([], declared_normal=True, normal_confidence=4), [oc("case", "true_negative")], [], search([])


def _s_pattern_false_normal() -> Scenario:
    c = cases()["syn_010"]
    outs = [oc("emphysema", "pattern_false", learner_label="emphysema")]
    return c, submit([], patterns=[("emphysema", 3)]), outs, [], search()


SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "found": _s_found,
    "mislabeled": _s_mislabeled,
    "missed_search": _s_missed_search,
    "missed_recognition": _s_missed_recognition,
    "missed_decision": _s_missed_decision,
    "multi": _s_multi,
    "bilateral": _s_bilateral,
    "pattern_found": _s_pattern_found,
    "pattern_missed": _s_pattern_missed,
    "false_positive_normal": _s_false_positive_normal,
    "true_negative": _s_true_negative,
    "pattern_false_normal": _s_pattern_false_normal,
}


def facts_for(
    name: str, level: str = "MS2", history: dict[str, Any] | None = None
) -> tuple[DebriefFacts, Case, AttemptSubmit]:
    c, sub, outs, rels, srch = SCENARIOS[name]()
    mark_zones = {m.mark_id: zone_at(c.case_id, m.x, m.y) for m in sub.marks}
    f = build_facts(
        case=c,
        submit=sub,
        outcomes=outs,
        spatial_relations=rels,
        search=srch,
        mark_zones=mark_zones,
        level=level,
        history=history or {},
    )
    return f, c, sub


def jitter_events(x: float, y: float, t0: float, ms: float, step: float = 33.0) -> list[TelemetryEvent]:
    """Pointer hovering around (x, y) with 2 px jitter so it counts as moving (not idle)."""
    out = []
    n = int(ms // step) + 1
    for i in range(n):
        dx = 2.0 if i % 2 else -2.0
        out.append(
            TelemetryEvent(t=t0 + i * step, kind="move", x=x + dx, y=y, zoom=1.0, vp=(0, 0, 256, 256), loupe=True)
        )
    return out


def zone_center(case_id: str, zone: str) -> tuple[float, float]:
    """Most interior pixel of the zone (so pointer jitter stays inside it)."""
    import cv2

    dist = cv2.distanceTransform(zones(case_id)[zone].astype(np.uint8), cv2.DIST_L2, 3)
    y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
    return float(x), float(y)


def fixture_root() -> Path:
    return FIXTURES
