"""SPEC §9.2 next-case selection (Practice / Drill / Review) and §9.3 assessment order. Pure functions.

Constants from config/adaptive.yaml['selection']. All randomness comes from the injected `rng`.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from backend.app.adaptive.elo import case_theta, p_success

# QA flags that do NOT disqualify a case from being served (allowlist). Any other flag (e.g. orientation_suspect,
# merged_duplicate_instances) keeps the case out of assessment forms and the practice/drill/review pools.
BENIGN_FLAGS = frozenset({"synthetic", "anatomy_missing", "anatomy_failed", "zones_approximate", "approximate_zones"})


def qa_ok(flags: Sequence[str]) -> bool:
    return all(f in BENIGN_FLAGS for f in flags)


@dataclass(frozen=True)
class CaseInfo:
    case_id: str
    is_normal: bool
    labels: tuple[str, ...]  # canonical labels of the case's findings (focal + pattern)
    b: float
    split: str = "practice"
    qa_flags: tuple[str, ...] = ()


@dataclass
class LearnerState:
    abilities: dict[str, tuple[float, int]] = field(default_factory=dict)  # label -> (θ, n)
    seen_in_session: set[str] = field(default_factory=set)
    recent: list[str] = field(default_factory=list)  # last attempts (case ids), newest last
    last_label: str | None = None
    n_drawn: int = 0  # cases drawn so far in this session
    n_abnormal_drawn: int = 0


def eligible(info: CaseInfo, core: Sequence[str]) -> bool:
    if info.split != "practice":
        return False
    if not qa_ok(info.qa_flags):
        return False
    return info.is_normal or any(lab in core for lab in info.labels)


def weakest_label(abilities: Mapping[str, tuple[float, int]], core: Sequence[str], init: float) -> str:
    """Lowest θ with ≥ 2 attempts; else the least practised core label."""
    tried = [(abilities[lab][0], lab) for lab in core if lab in abilities and abilities[lab][1] >= 2]
    if tried:
        return min(tried)[1]
    return min(core, key=lambda lab: (abilities.get(lab, (init, 0))[1], core.index(lab)))


def draw_abnormal(state: LearnerState, prevalence: float, rng: random.Random) -> bool:
    """Bernoulli draw at `prevalence`, nudged toward the target by the session's realised deficit so that
    realised prevalence stays close to the instructor setting (DECISION in PROGRESS.md)."""
    deficit = prevalence * state.n_drawn - state.n_abnormal_drawn  # in cases; > 0 → too few abnormals so far
    p = min(0.95, max(0.05, prevalence + 0.25 * deficit))
    return rng.random() < p


def select_next(
    pool: Sequence[CaseInfo],
    state: LearnerState,
    cfg: dict,
    rng: random.Random,
    *,
    core: Sequence[str],
    theta_init: float = 0.0,
    drill_label: str | None = None,
    prevalence: float | None = None,
    strategy: str = "adaptive",
) -> CaseInfo | None:
    """`strategy` (SessionCreate.settings.selection): "adaptive" = SPEC §9.2 as written; "weak_areas" = every
    abnormal draw targets the learner's weakest core label (weakest_label_prob 1.0); "random" = uniform over the
    eligible pool at the configured prevalence (no Elo objective, no label targeting). The eligibility rules
    (practice split only, no QA flags, not seen this session, not recent) are the same for all three."""
    prev = cfg["prevalence_abnormal"] if prevalence is None else prevalence
    base = [c for c in pool if eligible(c, core if drill_label is None else (*core, drill_label))]
    if drill_label:
        base = [c for c in base if c.is_normal or drill_label in c.labels]
    if not base:
        base = [c for c in pool if c.split == "practice" and qa_ok(c.qa_flags)]  # never assess/bench/flagged
    if not base:
        return None
    recent = set(state.recent[-int(cfg["recent_window"]) :])
    cands = [c for c in base if c.case_id not in state.seen_in_session and c.case_id not in recent]
    if not cands:
        cands = [c for c in base if c.case_id not in state.seen_in_session] or list(base)

    want_abnormal = draw_abnormal(state, prev, rng)
    cls = [c for c in cands if (not c.is_normal) == want_abnormal] or cands
    if strategy == "random":
        return rng.choice(cls)

    target_label = None
    abnormal = [c for c in cls if not c.is_normal]
    if abnormal:
        if drill_label:
            target_label = drill_label
        elif rng.random() < (1.0 if strategy == "weak_areas" else cfg["weakest_label_prob"]):
            target_label = weakest_label(state.abilities, list(core), theta_init)
        else:
            target_label = rng.choice(list(core))
        with_label = [c for c in abnormal if target_label in c.labels]
        if with_label:
            cls = with_label

    if rng.random() < cfg["epsilon"]:
        return rng.choice(cls)

    def objective(c: CaseInfo) -> float:
        labels = [lab for lab in c.labels if lab in core] or list(c.labels)
        th = case_theta(state.abilities, labels, c.is_normal, theta_init)
        repeat = 1.0 if (state.last_label and state.last_label in c.labels and not drill_label) else 0.0
        return (
            abs(p_success(th, c.b) - cfg["target_p"])
            + cfg["repeat_label_penalty"] * repeat
            + rng.gauss(0.0, cfg["noise_sd"])
        )

    return min(cls, key=objective)


def note_drawn(state: LearnerState, c: CaseInfo, core: Sequence[str]) -> None:
    state.n_drawn += 1
    state.n_abnormal_drawn += 0 if c.is_normal else 1
    state.seen_in_session.add(c.case_id)
    state.recent.append(c.case_id)
    labs = [lab for lab in c.labels if lab in core] or list(c.labels)
    state.last_label = labs[0] if labs and not c.is_normal else None


def assessment_order(case_ids: Sequence[str], seed: int = 0) -> list[str]:
    """Fixed order for an assessment set: sorted then shuffled with a fixed seed (normals interleaved)."""
    ids = sorted(case_ids)
    random.Random(seed).shuffle(ids)
    return ids


def review_candidates(
    misses: Sequence[tuple[str, int, float]], n_attempts: int, now: float, min_gap_cases: int, day_s: float = 86400
) -> list[str]:
    """Past misses (case_id, attempt_index_of_last_try, unix_time_of_last_try) eligible under the
    1-day / N-case spacing rule (eligible if ≥ min_gap_cases attempts since, or ≥ 1 day since)."""
    out = []
    for cid, idx, ts in misses:
        if n_attempts - idx >= min_gap_cases or now - ts >= day_s:
            out.append(cid)
    return out
