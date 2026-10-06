"""SPEC §6.3 case score (0–100) and binary success. Weights from config/scoring.yaml."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shared.contracts import Outcome

LOCALIZED = {"found", "mislabeled"}
MISSED = {"missed_search", "missed_recognition", "missed_decision"}


@dataclass
class ScoreParts:
    n_focal: int
    localized: int
    label_credit: float
    n_patterns_involved: int
    patterns_correct: int
    false_positives: int
    pattern_false: int
    hints: int


def parts(outcomes: Sequence[Outcome], label_credit: float, hints: int) -> ScoreParts:
    res = [o.result for o in outcomes]
    gt_patterns = sum(r in ("pattern_found", "pattern_missed") for r in res)
    pf = res.count("pattern_false")
    return ScoreParts(
        n_focal=sum(r in LOCALIZED | MISSED for r in res),
        localized=sum(r in LOCALIZED for r in res),
        label_credit=label_credit,
        n_patterns_involved=gt_patterns + pf,
        patterns_correct=res.count("pattern_found"),
        false_positives=res.count("false_positive"),
        pattern_false=pf,
        hints=hints,
    )


def label_credit_for(pair_costs: Sequence[float], costs: dict) -> float:
    """DECISION: exact label = 1; related-group label = 1 − related cost (partial credit); other/not sure = 0."""
    total = 0.0
    for c in pair_costs:
        if c == float(costs["exact"]):
            total += 1.0
        elif c == float(costs["related"]):
            total += 1.0 - float(costs["related"])
    return total


def case_score(p: ScoreParts, is_normal: bool, cfg: dict) -> float:
    w = cfg["score_weights"]
    if is_normal:
        n = w["normal"]
        s = n["base"] + n["false_positive"] * (p.false_positives + p.pattern_false) + n["hint"] * p.hints
        return float(min(100.0, max(0.0, s)))
    a = w["abnormal"]
    pat_acc = p.patterns_correct / p.n_patterns_involved if p.n_patterns_involved else 1.0
    if p.n_focal:
        s = (
            a["localization"] * p.localized / p.n_focal
            + a["label"] * p.label_credit / p.n_focal
            + a["pattern"] * pat_acc
        )
    else:  # pattern-only case: patterns carry the full positive weight
        s = (a["localization"] + a["label"] + a["pattern"]) * pat_acc
    s += a["false_positive"] * p.false_positives + a["hint"] * p.hints
    return float(round(min(100.0, max(0.0, s)), 1))


def case_success(p: ScoreParts, is_normal: bool, cfg: dict) -> bool:
    if is_normal:
        return p.false_positives == 0 and p.pattern_false == 0
    max_fp = int(cfg["success"]["abnormal_max_false_positives"])
    gt_patterns = p.n_patterns_involved - p.pattern_false
    return p.localized == p.n_focal and p.false_positives <= max_fp and p.patterns_correct == gt_patterns
