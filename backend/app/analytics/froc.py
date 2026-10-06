"""SPEC §6.4 / §10.1 FROC: lesion localization fraction vs non-lesion localizations per image, per confidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def froc_rows(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-mark rows (case_id, mark_id, confidence, is_lesion_localization); duplicates excluded."""
    out = []
    for r in records:
        res = {o["target"]: o for o in r["outcomes"]}
        for m in r["marks"]:
            o = res.get(m["mark_id"])
            if o is None or o["result"] == "duplicate":
                continue
            out.append(
                {
                    "case_id": r["case_id"],
                    "mark_id": m["mark_id"],
                    "confidence": m["confidence"],
                    "is_lesion_localization": o["result"] == "true_positive",
                }
            )
    return out


def froc_curve(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n_images = len(records)
    n_lesions = sum(sum(1 for f in r["findings"] if f["kind"] == "focal") for r in records)
    rows = froc_rows(records)
    points = []
    for c in (5, 4, 3, 2, 1):
        ll = sum(1 for x in rows if x["is_lesion_localization"] and x["confidence"] >= c)
        nl = sum(1 for x in rows if not x["is_lesion_localization"] and x["confidence"] >= c)
        points.append(
            {
                "threshold": c,
                "llf": ll / n_lesions if n_lesions else None,
                "nlf": nl / n_images if n_images else None,
                "n_ll": ll,
                "n_nl": nl,
            }
        )
    return {"n_images": n_images, "n_lesions": n_lesions, "n_marks": len(rows), "points": points}
