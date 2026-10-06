"""SPEC §10.2 cohort metrics: learner metrics aggregated across learners + per-label difficulty table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.app import config
from backend.app.analytics.blindspot_map import blindspot_points
from backend.app.analytics.calibration import calibration
from backend.app.analytics.froc import froc_curve
from backend.app.analytics.learner import LOCALIZED, case_level_stats, miss_type_windows, review_area_habit


def label_difficulty(records: Sequence[dict[str, Any]], b_by_case: dict[str, float]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for r in records:
        res = {o["target"]: o["result"] for o in r["outcomes"]}
        b = b_by_case.get(r["case_id"], r.get("b0", 0.0))
        for f in r["findings"]:
            a = agg.setdefault(f["label"], {"n": 0, "localized": 0, "b_sum": 0.0})
            a["n"] += 1
            a["localized"] += res.get(f["id"]) in (*LOCALIZED, "pattern_found")
            a["b_sum"] += b
    return [
        {
            "label": lab,
            "display": config.display(lab),
            "n": a["n"],
            "empirical_success": a["localized"] / a["n"],
            "mean_b": round(a["b_sum"] / a["n"], 3),
        }
        for lab, a in sorted(agg.items())
    ]


def cohort_dashboard(records: Sequence[dict[str, Any]], b_by_case: dict[str, float]) -> dict[str, Any]:
    recs = sorted(records, key=lambda r: r["submitted_at"] or "")
    learners = sorted({r["learner_id"] for r in recs})
    per_learner = []
    for lid in learners:
        lr = [r for r in recs if r["learner_id"] == lid]
        st = case_level_stats(lr)
        per_learner.append(
            {
                "learner_id": lid,
                "n": st["n"],
                "sensitivity": st["sensitivity"],
                "specificity": st["specificity"],
                "score_mean": st["score_mean"],
            }
        )
    return {
        "n_attempts": len(recs),
        "n_learners": len(learners),
        "summary": case_level_stats(recs),
        "miss_type_mix": miss_type_windows(recs),
        "calibration": calibration(recs),
        "froc": froc_curve(recs),
        "blindspot_map": blindspot_points(recs),
        "review_area_habit": review_area_habit(recs),
        "label_difficulty": label_difficulty(recs, b_by_case),
        "learners": per_learner,
    }
