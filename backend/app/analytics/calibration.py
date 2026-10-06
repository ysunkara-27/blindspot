"""SPEC §10.1 calibration: accuracy by confidence level (marks and normal calls) + confident misses."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def calibration(records: Sequence[dict[str, Any]], confident_at: int = 4) -> dict[str, Any]:
    bins = {c: {"confidence": c, "n": 0, "correct": 0} for c in range(1, 6)}
    confident_misses = 0
    for r in records:
        res = {o["target"]: o["result"] for o in r["outcomes"]}
        for m in r["marks"]:
            o = res.get(m["mark_id"])
            if o is None or o == "duplicate":
                continue
            b = bins[int(m["confidence"])]
            b["n"] += 1
            ok = o == "true_positive"
            b["correct"] += ok
            confident_misses += (not ok) and m["confidence"] >= confident_at
        if r["declared_normal"] and r.get("normal_confidence"):
            b = bins[int(r["normal_confidence"])]
            b["n"] += 1
            b["correct"] += r["is_normal"]
            confident_misses += (not r["is_normal"]) and r["normal_confidence"] >= confident_at
    out = []
    for b in bins.values():
        out.append({**b, "accuracy": b["correct"] / b["n"] if b["n"] else None})
    return {"bins": out, "n": sum(b["n"] for b in out), "confident_misses": confident_misses}
