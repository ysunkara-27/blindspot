"""SPEC §10.1 learner metrics from parsed attempt records (services.parse_attempt). Every block reports n."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from backend.app import config
from backend.app.analytics.blindspot_map import blindspot_points
from backend.app.analytics.calibration import calibration
from backend.app.analytics.froc import froc_curve
from backend.app.search.misstype import BUCKET

BUCKETS = ("search", "recognition", "decision", "interpretation", "overcall")
LOCALIZED = ("found", "mislabeled")


def _focal_results(r: dict[str, Any]) -> list[str]:
    res = {o["target"]: o["result"] for o in r["outcomes"]}
    return [res[f["id"]] for f in r["findings"] if f["kind"] == "focal" and f["id"] in res]


def miss_counts(r: dict[str, Any]) -> Counter:
    return Counter(BUCKET[o["result"]] for o in r["outcomes"] if o["result"] in BUCKET)


def case_level_stats(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    abn = [r for r in records if not r["is_normal"]]
    nor = [r for r in records if r["is_normal"]]

    def detected(r):
        return any(o["result"] in (*LOCALIZED, "pattern_found") for o in r["outcomes"])

    def clean(r):
        return not any(o["result"] in ("false_positive", "pattern_false") for o in r["outcomes"])

    focal = [x for r in records for x in _focal_results(r)]
    fp = sum(o["result"] == "false_positive" for r in records for o in r["outcomes"])
    mix = Counter()
    for r in records:
        mix.update(miss_counts(r))
    return {
        "n": len(records),
        "n_abnormal": len(abn),
        "n_normal": len(nor),
        "sensitivity": sum(map(detected, abn)) / len(abn) if abn else None,
        "specificity": sum(map(clean, nor)) / len(nor) if nor else None,
        "localization_fraction": sum(x in LOCALIZED for x in focal) / len(focal) if focal else None,
        "n_focal_findings": len(focal),
        "false_positives_per_image": fp / len(records) if records else 0.0,
        "miss_type_mix": {b: int(mix.get(b, 0)) for b in BUCKETS},
        "score_mean": round(sum(r["score"] for r in records) / len(records), 1) if records else 0.0,
    }


def learning_curve(records: Sequence[dict[str, Any]], window: int = 10) -> dict[str, Any]:
    pts = []
    for i in range(len(records)):
        w = records[max(0, i - window + 1) : i + 1]
        pts.append(
            {
                "attempt": i + 1,
                "success_rate": sum(r["success"] for r in w) / len(w),
                "window_n": len(w),
                "score": records[i]["score"],
            }
        )
    per_label: dict[str, list[dict[str, Any]]] = {}
    seq: dict[str, list[float]] = {}
    for r in records:
        res = {o["target"]: o["result"] for o in r["outcomes"]}
        for f in r["findings"]:
            ok = res.get(f["id"]) in (*LOCALIZED, "pattern_found")
            seq.setdefault(f["label"], []).append(1.0 if ok else 0.0)
        if r["is_normal"]:
            seq.setdefault("normal", []).append(1.0 if r["success"] else 0.0)
    for lab, s in seq.items():
        per_label[lab] = [
            {
                "attempt": i + 1,
                "success_rate": sum(s[max(0, i - window + 1) : i + 1]) / len(s[max(0, i - window + 1) : i + 1]),
            }
            for i in range(len(s))
        ]
    return {"window": window, "n": len(records), "overall": pts, "per_label": per_label}


def miss_type_windows(records: Sequence[dict[str, Any]], size: int = 10) -> dict[str, Any]:
    out = []
    for start in range(0, len(records), size):
        chunk = records[start : start + size]
        c = Counter()
        for r in chunk:
            c.update(miss_counts(r))
        out.append(
            {"from": start + 1, "to": start + len(chunk), "n": len(chunk), **{b: int(c.get(b, 0)) for b in BUCKETS}}
        )
    return {"window": size, "n": len(records), "windows": out}


def review_area_habit(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    areas = config.review_area_ids()
    n = len(records)
    out = []
    for a in areas:
        k = sum(a in (r.get("search") or {}).get("visited_review_areas", []) for r in records)
        out.append({"area": a, "human": config.zone_human(a), "visited_pct": round(100 * k / n, 1) if n else None})
    return {"n": n, "areas": out}


def learner_dashboard(
    records: Sequence[dict[str, Any]], abilities: dict[str, tuple[float, int]] | None = None
) -> dict[str, Any]:
    recs = sorted(records, key=lambda r: r["submitted_at"] or "")
    return {
        "n_attempts": len(recs),
        "summary": case_level_stats(recs),
        "learning_curve": learning_curve(recs),
        "miss_type_mix": miss_type_windows(recs),
        "calibration": calibration(recs),
        "froc": froc_curve(recs),
        "blindspot_map": blindspot_points(recs),
        "review_area_habit": review_area_habit(recs),
        "abilities": [{"label": k, "theta": round(t, 3), "n": n} for k, (t, n) in sorted((abilities or {}).items())],
        "empty_message": "Read 5 cases to see your first learning curve." if len(recs) < 5 else None,
    }
