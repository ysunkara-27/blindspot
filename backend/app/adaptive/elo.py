"""SPEC §9.1 Elo as a lightweight Rasch model. Constants from config/adaptive.yaml['elo']."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

NORMAL = "normal"  # θ_normal (specificity skill)


def p_success(theta: float, b: float) -> float:
    z = theta - b
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def update(theta: float, b: float, outcome: float, n_learner: int, n_case: int, cfg: dict) -> tuple[float, float]:
    p = p_success(theta, b)
    k_t = cfg["k_learner"] / (1 + cfg["k_decay"] * n_learner)
    k_b = cfg["k_case"] / (1 + cfg["k_decay"] * n_case)
    return theta + k_t * (outcome - p), b - k_b * (outcome - p)


def case_theta(
    abilities: Mapping[str, tuple[float, int]], labels: Iterable[str], is_normal: bool, init: float
) -> float:
    """Learner ability relevant to a case: θ_normal for normals, mean θ over the case's labels otherwise."""
    keys = [NORMAL] if is_normal else list(dict.fromkeys(labels))
    if not keys:
        return init
    return sum(abilities.get(k, (init, 0))[0] for k in keys) / len(keys)


def global_theta(abilities: Mapping[str, tuple[float, int]], init: float = 0.0) -> float:
    used = [t for t, n in abilities.values() if n > 0]
    return sum(used) / len(used) if used else init


def apply_attempt(
    abilities: dict[str, tuple[float, int]],
    b: float,
    n_case: int,
    is_normal: bool,
    finding_results: list[tuple[str, float]],
    success: bool,
    cfg: dict,
) -> tuple[dict[str, tuple[float, int]], float, dict]:
    """Abnormal: each involved θ_label updated with that finding's outcome (1 = localized/found) against case b;
    b updated once with case success. Normal: θ_normal and b updated with success. Returns (abilities, b, log)."""
    init = cfg.get("theta_init", 0.0)
    ab = dict(abilities)
    log: dict = {"b_before": b, "theta_before": {}, "theta_after": {}}
    if is_normal:
        items = [(NORMAL, 1.0 if success else 0.0)]
    else:
        items = finding_results
    theta_c = case_theta(ab, [lab for lab, _ in items], is_normal, init)
    for lab, out in items:
        th, n = ab.get(lab, (init, 0))
        log["theta_before"].setdefault(lab, th)
        new_th, _ = update(th, b, out, n, n_case, cfg)
        ab[lab] = (new_th, n + 1)
        log["theta_after"][lab] = new_th
    _, new_b = update(theta_c, b, 1.0 if success else 0.0, 0, n_case, cfg)
    log["b_after"] = new_b
    log["p_success"] = p_success(theta_c, b)
    return ab, new_b, log
