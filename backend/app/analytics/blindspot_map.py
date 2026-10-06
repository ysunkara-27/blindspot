"""SPEC §10.1 blind-spot map: finding centroids in a canonical chest frame (normalised by the union lung bbox)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

FOUND = ("found", "mislabeled")


def normalise(xy: Sequence[float], lungs_bbox: Sequence[float] | None, width: float = 1024) -> tuple[float, float]:
    if not lungs_bbox:
        return xy[0] / width, xy[1] / width
    x0, y0, x1, y1 = lungs_bbox
    return round((xy[0] - x0) / max(1.0, x1 - x0), 4), round((xy[1] - y0) / max(1.0, y1 - y0), 4)


def blindspot_points(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    pts = []
    for r in records:
        res = {o["target"]: o["result"] for o in r["outcomes"]}
        bbox = (r.get("search") or {}).get("lungs_bbox")
        for f in r["findings"]:
            if f["kind"] != "focal" or f["id"] not in res:
                continue
            x, y = normalise(f["centroid"], bbox)
            pts.append({"x": x, "y": y, "label": f["label"], "result": res[f["id"]], "found": res[f["id"]] in FOUND})
    return {
        "frame": "x, y normalised to the union lung bounding box; x = 0 is the image left (patient right)",
        "n": len(pts),
        "n_missed": sum(not p["found"] for p in pts),
        "points": pts,
    }
