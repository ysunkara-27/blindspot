"""Scripted learner behaviours → AttemptSubmit objects with deterministic telemetry (SPEC §12.2, §12.3).

Telemetry is synthetic by construction (it is a test input, not learner data). Each scenario carries the outcome
it is *intended* to produce; running it through the production engines (eval.adapters.score_attempt) checks that
the engines classify it as intended.

Telemetry model: 33 ms pointer samples, zoom 1×, full viewport, loupe on. A "linger" jitters ±2 px around a
point (so the idle cap never triggers); a "sweep" crosses a region in a straight line. Between visits the pointer
leaves the image (x = None), so jumps never credit dwell to the regions they cross.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from shared.contracts import AttemptSubmit, Case, ClientTiming, Finding, Mark, PatternSelection, TelemetryEvent

SAMPLE_MS = 33.0
BEHAVIOURS = (
    "all_correct",
    "wrong_side",
    "mislabeled",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "overcall_normal",
)
ABNORMAL_BEHAVIOURS = BEHAVIOURS[:-1]
RECOGNITION_MS = 500.0  # "passes through ~500 ms"
DECISION_MS = 2000.0  # "lingers ~2,000 ms"
VISIT_MS = 1200.0  # visiting a finding it then marks
NEUTRAL_MS = 800.0  # looking somewhere irrelevant

# Plausible wrong label for each focal label (related group where one exists; else a clinically adjacent label).
CONFUSION = {
    "nodule": "mass",
    "mass": "nodule",
    "calcification": "nodule",
    "consolidation": "atelectasis",
    "atelectasis": "consolidation",
    "effusion": "pleural_thickening",
    "pleural_thickening": "effusion",
    "pneumothorax": "pleural_thickening",
    "fracture": "calcification",
}


@dataclass
class Scenario:
    scenario_id: str
    case_id: str
    behaviour: str
    target: str | None  # short finding id the behaviour is about
    submit: AttemptSubmit
    intended: dict[str, str]  # outcome target ("F1", "M2", "case") → intended result
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skip:
    case_id: str
    behaviour: str
    reason: str


# ------------------------------------------------------------------------------------------------ geometry
def interior_point(mask: np.ndarray) -> tuple[float, float]:
    """The mask pixel farthest from the mask boundary (robust to non-convex shapes)."""
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    y, x = np.unravel_index(int(np.argmax(dt)), dt.shape)
    return float(x) + 0.5, float(y) + 0.5


def distance_from(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance (px) of every pixel to the nearest mask pixel (0 inside)."""
    return cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)


class Ctx:
    """Per-case geometry: masks, ROIs, zones, safety distances."""

    def __init__(self, case: Case, repo: Any, cfg: dict[str, Any]):
        self.case = case
        self.w, self.h = case.width, case.height
        self.rho = float(cfg["roi"]["roi_frac"]) * self.w
        self.tau = float(cfg["hit"]["tolerance_frac"]) * self.w
        self.jitter = max(2.0, 0.002 * self.w)
        self.focal = [f for f in case.findings if f.kind == "focal"]
        self.masks = {f.short_id: repo.mask(case.case_id, f.finding_id) for f in self.focal}
        for f in self.focal:
            if self.masks[f.short_id] is None:
                self.masks[f.short_id] = _bbox_mask(f, self.w, self.h)
        self.dist = {k: distance_from(m) for k, m in self.masks.items()}
        self.zones, meta = repo.zones(case.case_id)
        self.midline = float(meta.get("midline_x") or self.w / 2)
        # A visit is "clear" of a finding ROI if it stays this far from the mask (ρ + 30% + jitter + margin).
        self.safe = 1.3 * self.rho + 2 * self.jitter + 3.0

    def clear_of(self, x: float, y: float, fid: str) -> bool:
        xi, yi = int(np.clip(x, 0, self.w - 1)), int(np.clip(y, 0, self.h - 1))
        return float(self.dist[fid][yi, xi]) > self.safe

    def hits_any(self, x: float, y: float) -> bool:
        xi, yi = int(np.clip(x, 0, self.w - 1)), int(np.clip(y, 0, self.h - 1))
        return any(float(d[yi, xi]) <= self.tau + 1.0 for d in self.dist.values())

    def neutral_points(self, avoid: Sequence[str], k: int = 3) -> list[tuple[float, float]]:
        """Interior points of lung zones that stay clear of every ROI in `avoid` (and of all findings)."""
        order = [
            "right_upper_zone",
            "left_upper_zone",
            "right_mid_zone",
            "left_mid_zone",
            "right_lower_zone",
            "left_lower_zone",
            "right_hilum",
            "left_hilum",
            "mediastinum",
        ]
        pts = []
        for z in order:
            m = self.zones.get(z)
            if m is None or not m.any():
                continue
            # restrict the zone to pixels clear of every finding, then take its deepest point
            ok = m.copy()
            for fid in self.dist:
                ok &= self.dist[fid] > self.safe
            if not ok.any():
                continue
            x, y = interior_point(ok)
            if all(self.clear_of(x, y, a) for a in avoid):
                pts.append((x, y))
            if len(pts) >= k:
                break
        return pts


def _bbox_mask(f: Finding, w: int, h: int) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    x0, y0, x1, y1 = (int(round(v)) for v in f.geometry.bbox)
    m[max(0, y0) : y1, max(0, x0) : x1] = True
    return m


# ------------------------------------------------------------------------------------------------ telemetry
class Tape:
    """Builds a TelemetryEvent list."""

    def __init__(self, w: int, h: int, loupe: bool = True):
        self.w, self.h, self.loupe = w, h, loupe
        self.t = 0.0
        self.events: list[TelemetryEvent] = []

    def _ev(self, kind: str, x: float | None, y: float | None) -> None:
        if x is not None:
            x = float(np.clip(x, 0, self.w - 1))
            y = float(np.clip(y, 0, self.h - 1))
        self.events.append(
            TelemetryEvent(
                t=round(self.t, 1),
                kind=kind,
                x=x,
                y=y,
                zoom=1.0,
                vp=(0.0, 0.0, float(self.w), float(self.h)),
                loupe=self.loupe,
            )
        )

    def linger(self, x: float, y: float, ms: float, jitter: float) -> None:
        """Pointer over (x, y) for `ms`, moving ±jitter px each sample (never idle-capped)."""
        self._ev("enter", x, y)
        n = max(1, int(round(ms / SAMPLE_MS)))
        offs = [(jitter, 0.0), (0.0, jitter), (-jitter, 0.0), (0.0, -jitter)]
        for i in range(n):
            self.t += SAMPLE_MS
            dx, dy = offs[i % 4]
            self._ev("move", x + dx, y + dy)
        self.leave()

    def sweep(self, x0: float, y0: float, x1: float, y1: float, n: int) -> None:
        self._ev("enter", x0, y0)
        for i in range(1, n + 1):
            self.t += SAMPLE_MS
            a = i / n
            self._ev("move", x0 + a * (x1 - x0), y0 + a * (y1 - y0))
        self.leave()

    def click(self, x: float, y: float) -> None:
        self._ev("enter", x, y)
        self.t += SAMPLE_MS
        self._ev("down", x, y)
        self.t += 80.0
        self._ev("up", x, y)
        self.leave()

    def leave(self) -> None:
        self.t += SAMPLE_MS
        self._ev("leave", None, None)
        self.t += 150.0  # pointer travels off-image; no dwell is credited


def sweep_through(tape: Tape, ctx: Ctx, fid: str, inside_ms: float) -> None:
    """Horizontal sweep through the finding ROI with ≈ inside_ms of samples inside the ROI."""
    roi = ctx.dist[fid] <= ctx.rho
    x, y = interior_point(ctx.masks[fid])
    row = roi[int(y)]
    xs = np.flatnonzero(row)
    # contiguous run containing x
    xi = int(x)
    lo = xi
    while lo - 1 >= 0 and row[lo - 1]:
        lo -= 1
    hi = xi
    while hi + 1 < row.size and row[hi + 1]:
        hi += 1
    if xs.size == 0:
        lo, hi = xi, xi
    n_inside = max(2, int(round(inside_ms / SAMPLE_MS)))
    step = max(1.5, (hi - lo + 1) / n_inside)
    start = lo - 2 * step
    n_total = int(np.ceil((hi + 2 * step - start) / step))
    tape.sweep(start, y, start + n_total * step, y, n_total)


# ------------------------------------------------------------------------------------------------ builders
def _submit(tape: Tape, marks: list[Mark], patterns: list[PatternSelection], declared_normal: bool) -> AttemptSubmit:
    total_ms = tape.t
    return AttemptSubmit(
        marks=marks,
        patterns=patterns,
        declared_normal=declared_normal,
        normal_confidence=4 if declared_normal else None,
        telemetry=tape.events,
        hints_used=0,
        client_timing=ClientTiming(
            shown_at="2026-10-05T12:00:00.000Z",
            submitted_at=f"2026-10-05T12:{int(total_ms // 60000):02d}:{(total_ms % 60000) / 1000:06.3f}Z",
        ),
    )


def build_scenario(
    case: Case, repo: Any, cfg: dict[str, Any], behaviour: str, target: str | None = None
) -> Scenario | Skip:
    ctx = Ctx(case, repo, cfg)
    tape = Tape(ctx.w, ctx.h)
    marks: list[Mark] = []
    intended: dict[str, str] = {}

    def add_mark(x: float, y: float, label: str) -> str:
        mid = f"M{len(marks) + 1}"
        tape.click(x, y)
        marks.append(Mark(mark_id=mid, x=round(x, 1), y=round(y, 1), label=label, confidence=4))
        return mid

    patterns = [PatternSelection(label=f.label, confidence=4) for f in case.findings if f.kind == "pattern"]
    for f in case.findings:
        if f.kind == "pattern":
            intended[f.short_id] = "pattern_found"

    if behaviour == "overcall_normal":
        if not case.is_normal:
            return Skip(case.case_id, behaviour, "not a normal case")
        pts = ctx.neutral_points([], k=3)
        if not pts:
            return Skip(case.case_id, behaviour, "no lung zone available")
        for x, y in pts[1:]:
            tape.linger(x, y, NEUTRAL_MS, ctx.jitter)
        x, y = pts[0]
        tape.linger(x, y, VISIT_MS, ctx.jitter)
        mid = add_mark(x, y, "nodule")
        intended[mid] = "false_positive"
        return Scenario(
            f"{case.case_id}:{behaviour}",
            case.case_id,
            behaviour,
            None,
            _submit(tape, marks, [], False),
            intended,
            {"mark_xy": (x, y)},
        )

    if behaviour == "all_correct" and not case.is_normal and not ctx.focal and patterns:
        for x, y in ctx.neutral_points([], k=3):  # pattern-only case: look around, report the global findings
            tape.linger(x, y, NEUTRAL_MS, ctx.jitter)
        return Scenario(
            f"{case.case_id}:{behaviour}",
            case.case_id,
            behaviour,
            None,
            _submit(tape, marks, patterns, False),
            intended,
            {"pattern_only": True},
        )
    if case.is_normal or not ctx.focal:
        return Skip(case.case_id, behaviour, "needs a focal finding")
    tgt = next((f for f in ctx.focal if f.short_id == target), ctx.focal[0]) if target else ctx.focal[0]
    tid = tgt.short_id
    others = [f for f in ctx.focal if f.short_id != tid]

    # Behaviours that must keep the pointer away from the target need every other visit to be clear of its ROI.
    away = behaviour in ("wrong_side", "missed_search", "missed_recognition", "missed_decision")
    other_pts = {f.short_id: interior_point(ctx.masks[f.short_id]) for f in others}
    if away and any(not ctx.clear_of(x, y, tid) for x, y in other_pts.values()):
        return Skip(case.case_id, behaviour, "another finding lies inside the target's ROI margin")
    neutral = ctx.neutral_points([tid] if away else [], k=2)

    for x, y in neutral:
        tape.linger(x, y, NEUTRAL_MS, ctx.jitter)
    for f in others:  # all other focal findings are visited and marked correctly
        x, y = other_pts[f.short_id]
        tape.linger(x, y, VISIT_MS, ctx.jitter)
        mid = add_mark(x, y, f.label)
        intended[f.short_id] = "found"
        intended[mid] = "true_positive"

    tx, ty = interior_point(ctx.masks[tid])
    meta: dict[str, Any] = {"target_label": tgt.label, "target_side": tgt.side}
    if behaviour == "all_correct":
        tape.linger(tx, ty, VISIT_MS, ctx.jitter)
        mid = add_mark(tx, ty, tgt.label)
        intended[tid], intended[mid] = "found", "true_positive"
    elif behaviour == "mislabeled":
        wrong = CONFUSION.get(tgt.label, "not_sure")
        tape.linger(tx, ty, VISIT_MS, ctx.jitter)
        mid = add_mark(tx, ty, wrong)
        intended[tid], intended[mid] = "mislabeled", "true_positive"
        meta["learner_label"] = wrong
    elif behaviour == "wrong_side":
        mx, my = 2 * ctx.midline - tx, ty
        if not (0 <= mx < ctx.w) or ctx.hits_any(mx, my) or not ctx.clear_of(mx, my, tid):
            return Skip(case.case_id, behaviour, "mirror point hits a finding or the target ROI")
        tape.linger(mx, my, VISIT_MS, ctx.jitter)
        mid = add_mark(mx, my, tgt.label)
        intended[tid], intended[mid] = "missed_search", "false_positive"
        meta["mark_xy"] = (mx, my)
    elif behaviour == "missed_search":
        intended[tid] = "missed_search"
    elif behaviour == "missed_recognition":
        sweep_through(tape, ctx, tid, RECOGNITION_MS)
        intended[tid] = "missed_recognition"
    elif behaviour == "missed_decision":
        tape.linger(tx, ty, DECISION_MS, ctx.jitter)
        intended[tid] = "missed_decision"
    else:
        raise ValueError(behaviour)
    return Scenario(
        f"{case.case_id}:{behaviour}:{tid}",
        case.case_id,
        behaviour,
        tid,
        _submit(tape, marks, patterns, False),
        intended,
        meta,
    )


def generate(
    cases: Sequence[Case], repo: Any, cfg: dict[str, Any], behaviours: Sequence[str] = BEHAVIOURS
) -> tuple[list[Scenario], list[Skip]]:
    out: list[Scenario] = []
    skips: list[Skip] = []
    for c in cases:
        for b in behaviours:
            if (b == "overcall_normal") != c.is_normal:
                continue
            r = build_scenario(c, repo, cfg, b)
            (out if isinstance(r, Scenario) else skips).append(r)
    return out, skips


def compare(intended: dict[str, str], actual: dict[str, str]) -> dict[str, tuple[str, str | None, bool]]:
    return {k: (v, actual.get(k), actual.get(k) == v) for k, v in intended.items()}
