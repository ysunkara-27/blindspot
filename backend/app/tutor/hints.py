"""Deterministic hint ladder (SPEC §8.8). No LLM. Hints are disabled in Assessment mode by the backend.

H1 (all cases): review areas not yet visited (dwell ≥ visit_ms, no dilation), else compare sides.
H2: abnormal → patient side + primary zone of the hardest focal finding not yet marked; normal → asymmetry.
H3: abnormal → the first key sign from that finding's card; normal → "normal is a valid call".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from backend.app.tutor import vocab
from backend.app.tutor.cards import load_cards
from shared.contracts import Case, Finding, Mark, TeachingCard, TelemetryEvent

H1_ALL_VISITED = "Compare each region with the same region on the other side."
H2_NORMAL = "Asymmetry is the clue: compare left and right zone by zone."
H3_NORMAL = "If every review area is clear, normal is a valid call."
H2_PATTERN = "Step back and judge the whole film: the heart size and both lungs overall."
H2_ALL_MARKED = "Your marks are near every focal finding; check each label and the Global findings list."


def _get(e: Any, k: str) -> Any:
    return e.get(k) if isinstance(e, Mapping) else getattr(e, k, None)


def _inside(region: np.ndarray, x: float, y: float) -> bool:
    h, w = region.shape
    xi, yi = int(x), int(y)
    return 0 <= xi < w and 0 <= yi < h and bool(region[yi, xi])


def dwell_ms(events: Sequence[Any], region: np.ndarray, cfg: Mapping[str, Any]) -> float:
    """SPEC §7.1 attention-proxy dwell inside `region` (local copy used only if the backend engine is absent)."""
    total, still = 0.0, 0.0
    max_dt = float(cfg.get("max_dt_ms", 250))
    max_still = float(cfg.get("max_still_ms", 1500))
    zmin = float(cfg.get("zoom_dwell_min", 2.0))
    zw = float(cfg.get("zoom_dwell_weight", 0.5))
    for e0, e1 in zip(events, events[1:], strict=False):
        dt = min(float(_get(e1, "t")) - float(_get(e0, "t")), max_dt)
        x0, y0 = _get(e0, "x"), _get(e0, "y")
        if x0 is None or y0 is None:
            continue
        x1, y1 = _get(e1, "x"), _get(e1, "y")
        moved = x1 is None or y1 is None or (abs(x1 - x0) + abs(y1 - y0)) > 1.0
        still = 0.0 if moved else still + dt
        if still > max_still:
            continue
        if _inside(region, x0, y0):
            total += dt
        vp = _get(e0, "vp")
        if float(_get(e0, "zoom") or 1.0) >= zmin and vp is not None:
            if _inside(region, (vp[0] + vp[2]) / 2.0, (vp[1] + vp[3]) / 2.0):
                total += zw * dt
    return total


def unvisited_review_areas(
    telemetry: Sequence[TelemetryEvent], zones: Mapping[str, np.ndarray], scoring_cfg: Mapping[str, Any] | None = None
) -> list[str]:
    sc = scoring_cfg if scoring_cfg is not None else vocab.scoring_cfg()
    dcfg = dict(sc.get("dwell", {}))
    visit_ms = float(dcfg.get("visit_ms", 300))
    areas = vocab.review_area_ids()
    try:  # prefer the backend's coverage engine so hints and the reveal agree
        from backend.app.search.coverage import review_coverage
        from backend.app.search.dwell import dwell_samples

        cov = review_coverage(dwell_samples(list(telemetry), dcfg), zones, areas, visit_ms)
        return [a for a in cov.unvisited if a in zones]
    except Exception:  # noqa: BLE001 — engine missing or changed: fall back to the local SPEC §7.1 dwell
        return [a for a in areas if a in zones and dwell_ms(list(telemetry), zones[a], dcfg) < visit_ms]


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _marked(f: Finding, marks: Sequence[Mark], tau: float) -> bool:
    x0, y0, x1, y1 = f.geometry.bbox
    return any(x0 - tau <= m.x <= x1 + tau and y0 - tau <= m.y <= y1 + tau for m in marks)


def hardest_unmarked(case: Case, marks: Sequence[Mark], scoring_cfg: Mapping[str, Any] | None = None) -> Finding | None:
    sc = scoring_cfg if scoring_cfg is not None else vocab.scoring_cfg()
    tau = float(sc.get("hit", {}).get("tolerance_frac", 0.02)) * case.width
    cand = [f for f in case.findings if f.kind == "focal" and not _marked(f, marks, tau)]
    if not cand:
        return None
    return max(
        cand,
        key=lambda f: (
            f.difficulty if f.difficulty is not None else case.difficulty_prior,
            vocab.zone_hardness(f.primary_zone),
            -f.area_frac,
            f.finding_id,
        ),
    )


def hint(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    telemetry: Sequence[TelemetryEvent],
    zones: Mapping[str, np.ndarray],
    cfg: Mapping[str, Any] | None = None,
    cards: dict[str, TeachingCard] | None = None,
) -> str:
    """Hint text for ladder step `level` (1..3). `cfg` is config/scoring.yaml (loaded if None)."""
    level = min(3, max(1, int(level)))
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    if level == 1:
        un = unvisited_review_areas(telemetry, zones, sc)
        if not un:
            return H1_ALL_VISITED
        return "You haven't looked at: " + _join([vocab.zone_human(z) for z in un]) + "."
    if case.is_normal or not case.findings:
        return H2_NORMAL if level == 2 else H3_NORMAL
    target = hardest_unmarked(case, marks, sc)
    cards = cards if cards is not None else load_cards()
    if target is None:
        patterns = [f for f in case.findings if f.kind == "pattern"]
        if not patterns:
            return H2_ALL_MARKED
        if level == 2:
            return H2_PATTERN
        card = cards.get(patterns[0].label)
        return f"Look for this sign: {card.key_signs[0]}." if card else H2_PATTERN
    if level == 2:
        where = vocab.zone_human(target.primary_zone)
        if target.side in ("right", "left"):
            return f"Look again at the patient's {target.side} side, in the {where}."
        return f"Look again at the {where}."
    card = cards.get(target.label)
    if card and card.key_signs:
        return f"Look for this sign: {card.key_signs[0]}."
    return f"Look again at the {vocab.zone_human(target.primary_zone)}."
