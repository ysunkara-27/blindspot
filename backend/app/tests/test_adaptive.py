"""SPEC §9: Elo math and selection. Learners here are SYNTHETIC (seeded simulations) — test-only, never shown
in the UI or reported as real data."""

from __future__ import annotations

import math
import random

import pytest

from backend.app import config
from backend.app.adaptive.elo import NORMAL, apply_attempt, case_theta, global_theta, p_success, update
from backend.app.adaptive.selector import (
    CaseInfo,
    LearnerState,
    assessment_order,
    note_drawn,
    review_candidates,
    select_next,
    weakest_label,
)

ELO = config.adaptive()["elo"]
SEL = config.adaptive()["selection"]
CORE = [lab for lab in config.core_labels()]
FOCAL_CORE = [lab for lab in CORE if config.label_kind(lab) == "focal"]


def test_p_success():
    assert p_success(0, 0) == 0.5
    assert p_success(1, 0) == pytest.approx(1 / (1 + math.exp(-1)))
    assert p_success(-800, 0) == pytest.approx(0.0)


def test_update_matches_spec_formula():
    th, b = update(0.0, 0.0, 1.0, 0, 0, ELO)
    assert th == pytest.approx(ELO["k_learner"] * 0.5)
    assert b == pytest.approx(-ELO["k_case"] * 0.5)
    th2, _ = update(0.0, 0.0, 1.0, 10, 0, ELO)
    assert th2 == pytest.approx(ELO["k_learner"] / (1 + ELO["k_decay"] * 10) * 0.5)
    th3, b3 = update(0.0, 0.0, 0.0, 0, 0, ELO)
    assert th3 < 0 and b3 > 0


def test_apply_attempt_abnormal_and_normal():
    ab, b, log = apply_attempt({}, 0.5, 0, False, [("nodule", 1.0), ("mass", 0.0)], False, ELO)
    assert ab["nodule"][0] > 0 and ab["mass"][0] < 0 and ab["nodule"][1] == 1
    assert b > 0.5  # failed case looks harder
    ab2, b2, _ = apply_attempt({}, 0.0, 0, True, [], True, ELO)
    assert ab2[NORMAL][0] > 0 and b2 < 0


def test_case_theta_and_global():
    ab = {"nodule": (1.0, 3), "mass": (-1.0, 2), NORMAL: (0.5, 4)}
    assert case_theta(ab, ["nodule", "mass"], False, 0.0) == 0
    assert case_theta(ab, [], True, 0.0) == 0.5
    assert global_theta(ab) == pytest.approx(0.5 / 3)


def test_weakest_label():
    ab = {"nodule": (-1.0, 3), "mass": (0.5, 5), "effusion": (-2.0, 1)}
    assert weakest_label(ab, CORE, 0.0) == "nodule"  # effusion has < 2 attempts
    assert weakest_label({}, CORE, 0.0) == CORE[0]


# ---------------------------------------------------------------- synthetic simulation helpers
def synthetic_pool(seed: int, n: int = 600, include_other_splits: bool = True) -> list[CaseInfo]:
    rng = random.Random(seed)
    pool = []
    for i in range(n):
        normal = i % 2 == 0
        labels = () if normal else (rng.choice(FOCAL_CORE),)
        pool.append(CaseInfo(f"synthetic_{i}", normal, labels, rng.uniform(-2.5, 2.5)))
    if include_other_splits:
        for i in range(60):
            split = ("assess_A", "assess_B", "bench", "holdout")[i % 4]
            pool.append(CaseInfo(f"synthetic_x{i}", i % 3 == 0, () if i % 3 == 0 else ("nodule",), 0.0, split))
    return pool


def simulate(seed: int, n_cases: int = 40) -> tuple[float, list[CaseInfo]]:
    """One SYNTHETIC learner with a hidden true ability per label; outcomes drawn from the Rasch model."""
    rng = random.Random(seed)
    true_theta = {lab: rng.gauss(0.5, 0.8) for lab in FOCAL_CORE + [NORMAL]}
    pool = synthetic_pool(seed)
    b_est = {c.case_id: c.b for c in pool}
    state = LearnerState()
    successes, served = [], []
    for _ in range(n_cases):
        view = [CaseInfo(c.case_id, c.is_normal, c.labels, b_est[c.case_id], c.split) for c in pool]
        c = select_next(view, state, SEL, rng, core=CORE)
        note_drawn(state, c, CORE)
        served.append(c)
        lab = NORMAL if c.is_normal else c.labels[0]
        ok = rng.random() < p_success(true_theta[lab], c.b)
        successes.append(ok)
        fr = [] if c.is_normal else [(lab, 1.0 if ok else 0.0)]
        state.abilities, b_est[c.case_id], _ = apply_attempt(state.abilities, c.b, 0, c.is_normal, fr, ok, ELO)
    return sum(successes) / len(successes), served


def test_simulation_success_near_target():
    """§9.4: realised success within 0.6–0.8 after 40 cases (mean over 30 seeded synthetic learners)."""
    rates = [simulate(seed)[0] for seed in range(30)]
    mean = sum(rates) / len(rates)
    assert 0.6 <= mean <= 0.8, mean


def test_no_assessment_or_bench_case_in_practice():
    for seed in range(5):
        _, served = simulate(seed, 60)
        assert all(c.split == "practice" for c in served)
        assert len({c.case_id for c in served}) == len(served)  # no repeats within a session


def test_prevalence_within_5pct_over_200_draws():
    for prevalence in (0.5, 0.3, 0.7):
        for seed in range(5):
            rng = random.Random(seed)
            pool = synthetic_pool(seed, n=1000)
            state = LearnerState()
            n_abn = 0
            for _ in range(200):
                c = select_next(pool, state, SEL, rng, core=CORE, prevalence=prevalence)
                note_drawn(state, c, CORE)
                n_abn += not c.is_normal
            assert abs(n_abn / 200 - prevalence) <= 0.05, (prevalence, seed, n_abn)


def test_drill_mode_fixes_label():
    rng = random.Random(1)
    pool = synthetic_pool(1)
    state = LearnerState()
    for _ in range(30):
        c = select_next(pool, state, SEL, rng, core=CORE, drill_label="effusion", prevalence=0.7)
        note_drawn(state, c, CORE)
        assert c.is_normal or "effusion" in c.labels


def test_qa_flagged_excluded():
    pool = [
        CaseInfo("a", True, (), 0.0, qa_flags=("orientation_suspect",)),
        CaseInfo("b", True, (), 0.0, qa_flags=("synthetic",)),
    ]
    rng = random.Random(0)
    for _ in range(10):
        assert select_next(pool, LearnerState(), SEL, rng, core=CORE).case_id == "b"


def test_assessment_order_fixed():
    ids = [f"c{i}" for i in range(20)]
    assert assessment_order(ids) == assessment_order(list(reversed(ids)))
    assert sorted(assessment_order(ids)) == sorted(ids)


def test_review_spacing():
    misses = [("a", 9, 0.0), ("b", 5, 0.0), ("c", 9, -90000.0)]
    assert review_candidates(misses, 10, 1000.0, 3) == ["b", "c"]
