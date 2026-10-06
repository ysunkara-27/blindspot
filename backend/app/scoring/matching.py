"""SPEC §6.2 matching of marks to focal findings (Hungarian, scipy.optimize.linear_sum_assignment)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass
class MatchResult:
    pairs: dict[str, str] = field(default_factory=dict)  # mark_id -> finding_id
    pair_cost: dict[str, float] = field(default_factory=dict)  # mark_id -> cost
    duplicates: dict[str, str] = field(default_factory=dict)  # mark_id -> finding_id it re-hits
    false_positives: list[str] = field(default_factory=list)

    def mark_for(self, finding_id: str) -> str | None:
        for m, f in self.pairs.items():
            if f == finding_id:
                return m
        return None


def label_cost(mark_label: str, finding_label: str, groups: Sequence[frozenset[str]], costs: dict) -> float:
    if mark_label == finding_label:
        return float(costs["exact"])
    if mark_label != "not_sure" and any(mark_label in g and finding_label in g for g in groups):
        return float(costs["related"])
    return float(costs["other"])


def cost_matrix(
    mark_labels: Sequence[str],
    finding_labels: Sequence[str],
    hit: np.ndarray,
    groups: Sequence[frozenset[str]],
    costs: dict,
) -> np.ndarray:
    no_hit = float(costs["no_hit"])
    c = np.full((len(mark_labels), len(finding_labels)), no_hit, dtype=float)
    for i, ml in enumerate(mark_labels):
        for j, fl in enumerate(finding_labels):
            if hit[i, j]:
                c[i, j] = label_cost(ml, fl, groups, costs)
    return c


def match(
    mark_ids: Sequence[str],
    mark_labels: Sequence[str],
    finding_ids: Sequence[str],
    finding_labels: Sequence[str],
    hit: np.ndarray,
    groups: Sequence[frozenset[str]],
    costs: dict,
) -> MatchResult:
    """`hit[i, j]` = mark i hits finding j. Pairs with cost ≥ no_hit are dropped."""
    res = MatchResult()
    if not mark_ids:
        return res
    hit = np.asarray(hit, dtype=bool).reshape(len(mark_ids), len(finding_ids))
    if finding_ids:
        c = cost_matrix(mark_labels, finding_labels, hit, groups, costs)
        rows, cols = linear_sum_assignment(c)
        for r, k in zip(rows, cols):
            if c[r, k] < float(costs["no_hit"]):
                res.pairs[mark_ids[r]] = finding_ids[k]
                res.pair_cost[mark_ids[r]] = float(c[r, k])
    matched_findings = set(res.pairs.values())
    for i, mid in enumerate(mark_ids):
        if mid in res.pairs:
            continue
        dup = next(
            (finding_ids[j] for j in range(len(finding_ids)) if hit[i, j] and finding_ids[j] in matched_findings), None
        )
        if dup is not None:
            res.duplicates[mid] = dup
        else:
            res.false_positives.append(mid)
    return res
