"""Seeded splits for Blindspot (SPEC §3.5). Rewrites the `split` field of cases.jsonl in place and writes
data/processed/splits.json.

Run:  uv run python -m pipeline.splits               # initial build (label mix + size-proxy balance)
      uv run python -m pipeline.splits --rebalance   # after M2: re-match assess_A/B on difficulty_prior

Rules
- HF test split  -> assess_A, assess_B (20 each: 8 normal + 12 abnormal, identical label mix, no qa-flagged
  cases, single-focal-finding cases preferred), everything else in test -> bench (evaluation only).
- HF train split -> practice, with a seeded 5% stratified holdout.
- Assessment and bench cases never appear in practice (validate_splits asserts disjointness + coverage).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shared.contracts import Case

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BLINDSPOT_DATA_DIR", REPO_ROOT / "data"))
OUT_DIR = DATA_DIR / "processed"

SEED = 20261008
SPLIT_NAMES = ("practice", "holdout", "assess_A", "assess_B", "bench")
FORM_NORMALS = 8
FORM_ABNORMALS = 12
HOLDOUT_FRAC = 0.05
B0_TOLERANCE = 0.1  # |mean b0(A) - mean b0(B)| after --rebalance (SPEC §3.5)

# Per-form label mix for the 12 abnormal cases, keyed on the case's "primary" label (its single focal finding,
# else its single pattern finding). Core curriculum labels (SPEC §3.4). If a label lacks candidates the
# shortfall is filled from FILL_ORDER. DECISION logged in docs/PROGRESS.md.
FORM_LABEL_MIX: dict[str, int] = {
    "pneumothorax": 2,
    "effusion": 2,
    "consolidation": 2,
    "nodule": 2,
    "atelectasis": 1,
    "mass": 1,
    "fracture": 1,
    "cardiomegaly": 1,
}
FILL_ORDER = ["effusion", "consolidation", "nodule", "pneumothorax", "fracture", "atelectasis", "mass", "cardiomegaly"]


# --------------------------------------------------------------------------- io
def load_cases(path: Path) -> list[Case]:
    with path.open() as fh:
        return [Case.model_validate_json(line) for line in fh if line.strip()]


def write_cases(path: Path, cases: list[Case]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in cases))
    os.replace(tmp, path)


# --------------------------------------------------------------------------- case descriptors
def focal(c: Case) -> list:
    return [f for f in c.findings if f.kind == "focal"]


# Salience order for choosing the label a multi-label case "stands for" in the form label mix: the finding a
# reader is most likely to be examined on (rare, high-stakes, or easily missed) wins over a co-existing common one,
# e.g. pneumothorax + effusion counts as a pneumothorax case. DECISION logged in docs/PROGRESS.md.
SALIENCE = [
    "pneumothorax",
    "mass",
    "fracture",
    "nodule",
    "atelectasis",
    "calcification",
    "pleural_thickening",
    "effusion",
    "consolidation",
    "cardiomegaly",
    "emphysema",
    "fibrosis",
    "diffuse_nodule",
]
MAX_ASSESS_TIER = 4


def preference_tier(c: Case) -> int:
    """Lower is preferred for assessment forms.
    0 = exactly one finding, focal
    1 = one focal finding + pattern finding(s)
    2 = several instances of ONE focal label (e.g. bilateral effusion, multiple rib fractures), +/- patterns
    3 = a single pattern finding only (e.g. cardiomegaly)
    4 = exactly two focal findings with different labels
    5 = anything busier (never used in assessment forms)"""
    fs = focal(c)
    nf, nt = len(fs), len(c.findings)
    if nf == 1:
        return 0 if nt == 1 else 1
    if nf > 1 and len({f.label for f in fs}) == 1:
        return 2
    if nf == 0 and nt == 1:
        return 3
    if nf == 2:
        return 4
    return 5


def primary_label(c: Case) -> str | None:
    """The label the case stands for in the form label mix: the most salient focal label, else the most salient
    pattern label. None for normals."""
    if c.is_normal or not c.findings:
        return None
    labels = {f.label for f in (focal(c) or c.findings)}
    return min(labels, key=SALIENCE.index)


def size_proxy(c: Case) -> float:
    """Pre-M2 difficulty proxy: smaller focal targets are harder. -log10(min focal area); 0 for normals."""
    fs = focal(c) or c.findings
    if not fs:
        return 0.0
    return -math.log10(max(min(f.area_frac for f in fs), 1e-6))


def b0(c: Case) -> float:
    return float(c.difficulty_prior)


# --------------------------------------------------------------------------- assessment forms
@dataclass
class Forms:
    A: list[str]
    B: list[str]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def eligible_for_assessment(c: Case) -> bool:
    return c.source_split == "test" and not c.qa_flags


def plan_label_mix(pool: dict[str, list[Case]], per_form: dict[str, int] = FORM_LABEL_MIX) -> dict[str, int]:
    """Clamp the target mix to available candidates (2 per slot), refilling shortfalls in FILL_ORDER."""
    plan = {k: min(v, len(pool.get(k, [])) // 2) for k, v in per_form.items()}
    short = sum(per_form.values()) - sum(plan.values())
    for lab in FILL_ORDER * FORM_ABNORMALS:
        if short <= 0:
            break
        if len(pool.get(lab, [])) // 2 > plan.get(lab, 0):
            plan[lab] = plan.get(lab, 0) + 1
            short -= 1
    if short > 0:
        raise RuntimeError(f"not enough eligible abnormal test cases to fill two forms (short {short})")
    return {k: v for k, v in plan.items() if v}


def build_forms(
    cases: list[Case], seed: int = SEED, key: Callable[[Case], float] = size_proxy, restarts: int = 200
) -> tuple[Forms, dict]:
    """Pick 2x(8 normal + 12 abnormal) from eligible test cases with identical label mix; within each label
    stratum, choose and assign cases so that mean key(A) ~ mean key(B)."""
    rng = random.Random(seed)
    elig = sorted((c for c in cases if eligible_for_assessment(c)), key=lambda c: c.case_id)
    normals = [c for c in elig if c.is_normal]
    if len(normals) < 2 * FORM_NORMALS:
        raise RuntimeError(f"only {len(normals)} eligible normal test cases; need {2 * FORM_NORMALS}")
    pool: dict[str, list[Case]] = defaultdict(list)
    for c in elig:
        if not c.is_normal and preference_tier(c) <= MAX_ASSESS_TIER:
            pool[primary_label(c)].append(c)  # type: ignore[index]
    plan = plan_label_mix(pool)

    # candidates per stratum: best tier first, then seeded shuffle; keep a margin of extras for swapping
    strata: dict[str, list[Case]] = {}
    for lab, k in plan.items():
        cs = pool[lab][:]
        rng.shuffle(cs)
        cs.sort(key=preference_tier)
        top_tier = preference_tier(cs[2 * k - 1])  # never use a worse tier than needed
        strata[lab] = [c for c in cs if preference_tier(c) <= top_tier]
    ns = normals[:]
    rng.shuffle(ns)
    strata["__normal__"] = ns
    plan = {**plan, "__normal__": FORM_NORMALS}

    best: tuple[float, Forms] | None = None
    for _ in range(restarts):
        A: list[Case] = []
        B: list[Case] = []
        for lab in sorted(plan):
            k = plan[lab]
            chosen = rng.sample(strata[lab], 2 * k)
            A += chosen[:k]
            B += chosen[k:]
        A, B = _swap_improve(A, B, strata, plan, key, rng)
        gap = abs(_mean([key(c) for c in A]) - _mean([key(c) for c in B]))
        if best is None or gap < best[0] - 1e-12:
            best = (gap, Forms(sorted(c.case_id for c in A), sorted(c.case_id for c in B)))
        if gap < 1e-3:
            break
    assert best is not None
    return best[1], {"plan": plan, "gap": best[0]}


def _label_of(c: Case) -> str:
    return "__normal__" if c.is_normal else primary_label(c)  # type: ignore[return-value]


def _swap_improve(A, B, strata, plan, key, rng, iters: int = 400):
    """Greedy local search: swap same-stratum cases between forms or with unused candidates if it shrinks
    |mean key(A) - mean key(B)|. Label mix is invariant under these moves."""

    def gap(a, b):
        return abs(_mean([key(c) for c in a]) - _mean([key(c) for c in b]))

    cur = gap(A, B)
    for _ in range(iters):
        lab = rng.choice(sorted(plan))
        a_idx = [i for i, c in enumerate(A) if _label_of(c) == lab]
        b_idx = [i for i, c in enumerate(B) if _label_of(c) == lab]
        used = {c.case_id for c in A + B}
        spare = [c for c in strata[lab] if c.case_id not in used]
        move = rng.random()
        A2, B2 = A[:], B[:]
        if move < 0.5 and a_idx and b_idx:
            i, j = rng.choice(a_idx), rng.choice(b_idx)
            A2[i], B2[j] = B[j], A[i]
        elif spare:
            target, idx = (A2, a_idx) if rng.random() < 0.5 else (B2, b_idx)
            if not idx:
                continue
            target[rng.choice(idx)] = rng.choice(spare)
        else:
            continue
        g = gap(A2, B2)
        if g < cur:
            A, B, cur = A2, B2, g
    return A, B


# --------------------------------------------------------------------------- holdout + assembly
def pick_holdout(train: list[Case], frac: float = HOLDOUT_FRAC, seed: int = SEED) -> set[str]:
    """Stratified (normal vs primary label) seeded holdout; total = round(frac * n)."""
    rng = random.Random(seed + 1)
    strata: dict[str, list[str]] = defaultdict(list)
    for c in sorted(train, key=lambda c: c.case_id):
        strata["__normal__" if c.is_normal else (primary_label(c) or "__none__")].append(c.case_id)
    target = round(frac * len(train))
    chosen: list[str] = []
    rema: list[tuple[float, str, list[str]]] = []
    for lab in sorted(strata):
        ids = strata[lab]
        rng.shuffle(ids)
        exact = frac * len(ids)
        k = int(exact)
        chosen += ids[:k]
        rema.append((exact - k, lab, ids[k:]))
    for _, _, ids in sorted(rema, key=lambda t: (-t[0], t[1])):
        if len(chosen) >= target:
            break
        if ids:
            chosen.append(ids[0])
    return set(chosen)


def assign(cases: list[Case], forms: Forms, holdout: set[str]) -> dict[str, list[str]]:
    a, b = set(forms.A), set(forms.B)
    out: dict[str, list[str]] = {k: [] for k in SPLIT_NAMES}
    for c in sorted(cases, key=lambda c: c.case_id):
        if c.case_id in a:
            out["assess_A"].append(c.case_id)
        elif c.case_id in b:
            out["assess_B"].append(c.case_id)
        elif c.source_split == "test":
            out["bench"].append(c.case_id)
        elif c.case_id in holdout:
            out["holdout"].append(c.case_id)
        else:
            out["practice"].append(c.case_id)
    return out


def validate_splits(splits: dict[str, list[str]], cases: list[Case]) -> None:
    """Disjoint, complete, assessment/bench from test only, practice/holdout from train only, form shape."""
    seen: dict[str, str] = {}
    for name, ids in splits.items():
        if name not in SPLIT_NAMES:
            raise AssertionError(f"unknown split {name}")
        for cid in ids:
            if cid in seen:
                raise AssertionError(f"{cid} in both {seen[cid]} and {name}")
            seen[cid] = name
    by_id = {c.case_id: c for c in cases}
    missing = set(by_id) - set(seen)
    extra = set(seen) - set(by_id)
    if missing or extra:
        raise AssertionError(f"split coverage: {len(missing)} unassigned, {len(extra)} unknown ids")
    for name, ids in splits.items():
        want = "test" if name in ("assess_A", "assess_B", "bench") else "train"
        bad = [i for i in ids if by_id[i].source_split != want]
        if bad:
            raise AssertionError(f"{name} contains {len(bad)} cases from source_split != {want}: {bad[:3]}")
    for form in ("assess_A", "assess_B"):
        cs = [by_id[i] for i in splits[form]]
        n_norm = sum(c.is_normal for c in cs)
        if (n_norm, len(cs) - n_norm) != (FORM_NORMALS, FORM_ABNORMALS):
            raise AssertionError(f"{form}: {n_norm} normal / {len(cs) - n_norm} abnormal")
        if any(c.qa_flags for c in cs):
            raise AssertionError(f"{form} contains qa-flagged cases")
    mix_a = Counter(primary_label(by_id[i]) for i in splits["assess_A"])
    mix_b = Counter(primary_label(by_id[i]) for i in splits["assess_B"])
    if mix_a != mix_b:
        raise AssertionError(f"label mix differs: A={dict(mix_a)} B={dict(mix_b)}")


def form_summary(ids: list[str], by_id: dict[str, Case]) -> dict:
    cs = [by_id[i] for i in ids]
    return {
        "n": len(cs),
        "normals": sum(c.is_normal for c in cs),
        "label_mix": dict(sorted(Counter(primary_label(c) or "normal" for c in cs).items())),
        "tiers": dict(sorted(Counter(preference_tier(c) for c in cs if not c.is_normal).items())),
        "mean_size_proxy": round(_mean([size_proxy(c) for c in cs]), 4),
        "mean_difficulty_prior": round(_mean([b0(c) for c in cs]), 4),
    }


def apply_splits(cases: list[Case], splits: dict[str, list[str]]) -> list[Case]:
    where = {cid: name for name, ids in splits.items() for cid in ids}
    return [c.model_copy(update={"split": where[c.case_id]}) for c in cases]


# --------------------------------------------------------------------------- entry points
def build(cases: list[Case], seed: int = SEED) -> tuple[dict[str, list[str]], dict]:
    forms, info = build_forms(cases, seed=seed, key=size_proxy)
    holdout = pick_holdout([c for c in cases if c.source_split == "train"], seed=seed)
    splits = assign(cases, forms, holdout)
    validate_splits(splits, cases)
    return splits, {"method": "label_mix+size_proxy", **info}


def rebalance(cases: list[Case], prev: dict[str, list[str]], seed: int = SEED) -> tuple[dict[str, list[str]], dict]:
    """Re-match A/B on difficulty_prior (b0). Keeps the current forms if already within B0_TOLERANCE.
    Practice/holdout membership never changes; only test cases move between A, B and bench."""
    by_id = {c.case_id: c for c in cases}
    if not any(c.difficulty_prior for c in cases):
        raise SystemExit("difficulty_prior is 0 for every case — run M2 (`make features`) before --rebalance")
    gap_prev = abs(_mean([b0(by_id[i]) for i in prev["assess_A"]]) - _mean([b0(by_id[i]) for i in prev["assess_B"]]))
    if gap_prev <= B0_TOLERANCE:
        # still validate: eligibility may have changed if M2 added qa flags
        try:
            validate_splits(prev, cases)
            return prev, {"method": "difficulty_prior (kept)", "gap": gap_prev}
        except AssertionError:
            pass
    forms, info = build_forms(cases, seed=seed, key=b0, restarts=500)
    holdout = set(prev.get("holdout", [])) or pick_holdout([c for c in cases if c.source_split == "train"], seed=seed)
    splits = assign(cases, forms, holdout)
    validate_splits(splits, cases)
    if info["gap"] > B0_TOLERANCE:
        print(f"WARNING: best b0 gap {info['gap']:.3f} > {B0_TOLERANCE}", flush=True)
    return splits, {"method": "difficulty_prior", **info, "gap_before": gap_prev}


def run(rebalance_mode: bool, seed: int = SEED, out_dir: Path = OUT_DIR) -> dict:
    cases_path = out_dir / "cases.jsonl"
    cases = load_cases(cases_path)
    splits_path = out_dir / "splits.json"
    if rebalance_mode:
        if not splits_path.exists():
            raise SystemExit("no splits.json — run `python -m pipeline.splits` first")
        splits, info = rebalance(cases, json.loads(splits_path.read_text())["splits"], seed)
    else:
        splits, info = build(cases, seed)
    by_id = {c.case_id: c for c in cases}
    doc = {
        "version": 1,
        "seed": seed,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": info["method"],
        "counts": {k: len(v) for k, v in splits.items()},
        "forms": {f: form_summary(splits[f], by_id) for f in ("assess_A", "assess_B")},
        "plan": info.get("plan"),
        "gap": info.get("gap"),
        "splits": splits,
    }
    tmp = splits_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    os.replace(tmp, splits_path)
    write_cases(cases_path, apply_splits(cases, splits))
    print(json.dumps({k: doc[k] for k in ("method", "counts", "forms", "gap")}, indent=2), flush=True)
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build or rebalance Blindspot splits")
    ap.add_argument("--rebalance", action="store_true", help="re-match assess_A/B on difficulty_prior (after M2)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args(argv)
    run(a.rebalance, a.seed, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
