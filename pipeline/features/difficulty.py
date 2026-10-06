"""Difficulty prior b0 — SPEC §4.5 (a heuristic prior; Elo corrects it from real attempts).

b0 = 0.9·z(−log area_frac) + 0.6·z(−contrast) + 0.5·z(zone_hardness) + 0.4·z(n_findings) + 0.6·z(1 − model_prob)
z-scores are fit over all focal findings in `practice`; a missing feature contributes 0.
Finding.difficulty = clip(b0, ±2.5); Case.difficulty_prior = max over its focal findings; normal cases and
pattern-only cases = 0. zone_hardness = config hardness of the finding's primary_zone; n_findings = all findings
(focal + pattern) in the case.

Outputs: cases.jsonl (difficulty, difficulty_prior), data/qa/anatomy_difficulty_params.json,
data/qa/difficulty_prior.png (per-label distribution).
Run: python -m pipeline.features.difficulty
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Any

import numpy as np

from pipeline.anatomy import common as C

WEIGHTS: dict[str, float] = {
    "neg_log_area": 0.9,
    "neg_contrast": 0.6,
    "hardness": 0.5,
    "n_findings": 0.4,
    "one_minus_p": 0.6,
}
CLIP = 2.5


def raw_features(finding: dict[str, Any], case: dict[str, Any]) -> dict[str, float | None]:
    area = max(float(finding.get("area_frac") or 0.0), 1e-7)
    con = finding.get("contrast")
    mp = finding.get("model_prob")
    return {
        "neg_log_area": -math.log(area),
        "neg_contrast": None if con is None else -float(con),
        "hardness": C.hardness(finding.get("primary_zone")),
        "n_findings": float(len(case["findings"])),
        "one_minus_p": None if mp is None else 1.0 - float(mp),
    }


def fit_z(rows: list[dict[str, float | None]]) -> dict[str, tuple[float, float]]:
    params: dict[str, tuple[float, float]] = {}
    for k in WEIGHTS:
        v = np.array([r[k] for r in rows if r.get(k) is not None], dtype=float)
        if v.size == 0:
            params[k] = (0.0, 1.0)
        else:
            sd = float(v.std())
            params[k] = (float(v.mean()), sd if sd > 1e-9 else 1.0)
    return params


def b0(raw: dict[str, float | None], params: dict[str, tuple[float, float]]) -> float:
    s = 0.0
    for k, w in WEIGHTS.items():
        v = raw.get(k)
        if v is None:
            continue  # missing → z = 0
        mu, sd = params[k]
        s += w * (v - mu) / sd
    return float(np.clip(s, -CLIP, CLIP))


def plot_per_label(per_label: dict[str, list[float]], path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2, grid, series = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"
    labels = sorted(per_label, key=lambda k: float(np.median(per_label[k])))
    fig, ax = plt.subplots(figsize=(8.5, 0.48 * len(labels) + 1.6), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    rng = np.random.default_rng(0)
    for i, lab in enumerate(labels):
        v = np.array(per_label[lab])
        ax.scatter(v, i + rng.uniform(-0.18, 0.18, v.size), s=6, color=series, alpha=0.25, linewidths=0)
        q1, med, q3 = np.percentile(v, [25, 50, 75])
        ax.plot([q1, q3], [i, i], color=ink, lw=2, solid_capstyle="round")
        ax.plot([med, med], [i - 0.28, i + 0.28], color=ink, lw=2)
    ax.set_yticks(range(len(labels)), [f"{lab.replace('_', ' ')}  (n={len(per_label[lab])})" for lab in labels])
    ax.axvline(0, color=ink2, lw=0.8, ls=(0, (2, 3)))
    ax.set_xlim(-CLIP - 0.1, CLIP + 0.1)
    ax.set_xlabel("difficulty prior b0 per focal finding (z-units; higher = harder)", color=ink2)
    ax.set_title(
        "Difficulty prior by label — all focal findings (dots), IQR bar + median tick",
        color=ink,
        loc="left",
        fontsize=11,
    )
    ax.tick_params(colors=ink2, length=0)
    ax.grid(axis="x", color=grid, lw=0.6)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="difficulty prior b0 (SPEC §4.5)")
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--overlays", type=int, default=20, help="re-render QA overlays with b0/CTR (0 = skip)")
    args = ap.parse_args(argv)
    log = C.get_logger("difficulty")
    cases = C.read_cases()
    train_rows = [
        raw_features(f, c) for c in cases if c["split"] == "practice" for f in c["findings"] if f["kind"] == "focal"
    ]
    params = fit_z(train_rows)
    log.info("z params from %d practice focal findings: %s", len(train_rows), params)
    fd: dict[str, float] = {}
    cd: dict[str, float] = {}
    per_label: dict[str, list[float]] = {}
    for c in cases:
        vals = []
        for f in c["findings"]:
            if f["kind"] != "focal":
                continue
            v = round(b0(raw_features(f, c), params), 3)
            fd[f["finding_id"]] = v
            vals.append(v)
            per_label.setdefault(f["label"], []).append(v)
        cd[c["case_id"]] = 0.0 if (c["is_normal"] or not vals) else max(vals)

    def upd(d: dict[str, Any]) -> None:
        if d["case_id"] not in cd:
            return
        d["difficulty_prior"] = cd[d["case_id"]]
        for f in d["findings"]:
            if f["finding_id"] in fd:
                f["difficulty"] = fd[f["finding_id"]]

    changed = C.update_cases(upd)
    summary = {
        lab: {
            "n": len(v),
            "mean": round(float(np.mean(v)), 3),
            "median": round(float(np.median(v)), 3),
            "p10": round(float(np.percentile(v, 10)), 3),
            "p90": round(float(np.percentile(v, 90)), 3),
        }
        for lab, v in sorted(per_label.items())
    }
    qa = C.qa_dir()
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "anatomy_difficulty_params.json").write_text(
        json.dumps(
            {
                "weights": WEIGHTS,
                "clip": CLIP,
                "z_params_mean_sd": params,
                "n_practice_focal": len(train_rows),
                "per_label": summary,
            },
            indent=2,
        )
    )
    if not args.no_plot:
        plot_per_label(per_label, qa / "difficulty_prior.png")
    if args.overlays:
        from pipeline.anatomy.overlay import write_overlays

        write_overlays(n=args.overlays)
    log.info(
        "difficulty done: %d focal findings, %d cases; lines changed=%d; per label: %s",
        len(fd),
        len(cd),
        changed,
        json.dumps({k: (v["n"], v["median"]) for k, v in summary.items()}),
    )


if __name__ == "__main__":
    main()
