"""Cardiothoracic ratio — SPEC §4.6.

CTR = max horizontal width of the Heart mask (over rows) / max row-wise distance between the outer edges of the
two lungs (rows where both lungs are present). Name-agnostic for the lungs (uses image extremes), so it does
not depend on the Left/Right channel naming.

Debrief caveat (tutor): "measured automatically; the projection (PA vs AP) is not recorded for these images,
and AP films exaggerate heart size." Values outside [0.25, 0.85] are treated as segmentation failures →
null (+ qa flag `ctr_implausible` only on cardiomegaly cases). Cases with anatomy_failed / no anatomy → null.

Run: python -m pipeline.features.ctr
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from pipeline.anatomy import common as C

CTR_RANGE = (0.25, 0.85)


def _row_extents(m: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    has = m.any(axis=1)
    first = np.argmax(m, axis=1)
    last = m.shape[1] - 1 - np.argmax(m[:, ::-1], axis=1)
    return has, first, last


def cardiothoracic_ratio(heart: np.ndarray, right_lung: np.ndarray, left_lung: np.ndarray) -> float | None:
    heart, rl, ll = (np.asarray(a, dtype=bool) for a in (heart, right_lung, left_lung))
    hh, hf, hl = _row_extents(heart)
    if not hh.any():
        return None
    heart_w = float((hl - hf + 1)[hh].max())
    rh, rf, rlast = _row_extents(rl)
    lh, lf, llast = _row_extents(ll)
    both = rh & lh
    if not both.any():
        return None
    outer_left = np.minimum(rf, lf)  # image-left outer edge (whichever lung is there)
    outer_right = np.maximum(rlast, llast)
    thor_w = float((outer_right - outer_left + 1)[both].max())
    return heart_w / thor_w if thor_w > 0 else None


def ctr_case(c: dict[str, Any]) -> tuple[str, float | None, bool]:
    """(case_id, CTR rounded or None, out_of_range)."""
    p = C.processed_dir() / C.anatomy_rel(c["case_id"])
    if not p.exists() or "anatomy_failed" in c.get("qa_flags", []):
        return c["case_id"], None, False
    masks, _ = C.load_anatomy(p)
    v = cardiothoracic_ratio(masks["Heart"], masks["Right Lung"], masks["Left Lung"])
    if v is not None and not (CTR_RANGE[0] <= v <= CTR_RANGE[1]):
        return c["case_id"], None, True
    return c["case_id"], None if v is None else round(v, 3), False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="cardiothoracic ratio (SPEC §4.6)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    log = C.get_logger("ctr")
    cases = C.read_cases()
    if args.limit:
        cases = cases[: args.limit]
    by_id = {c["case_id"]: c for c in cases}
    res: dict[str, float | None] = {}
    implausible: set[str] = set()
    n_out_of_range = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for cid, v, out_of_range in ex.map(ctr_case, cases, chunksize=8):
            res[cid] = v
            if out_of_range:
                n_out_of_range += 1
                # flag only where CTR is taught (cardiomegaly); any qa flag removes a case from assessment pools
                if any(f["label"] == "cardiomegaly" for f in by_id[cid]["findings"]):
                    implausible.add(cid)

    def upd(d: dict[str, Any]) -> None:
        if d["case_id"] not in res:
            return
        d["cardiothoracic_ratio"] = res[d["case_id"]]
        if d["case_id"] in implausible:
            C.add_flag(d, "ctr_implausible")
        else:
            C.remove_flag(d, "ctr_implausible")

    changed = C.update_cases(upd)
    # sanity: CTR should be higher in cases labelled cardiomegaly by the radiologists
    lab = {c["case_id"]: any(f["label"] == "cardiomegaly" for f in c["findings"]) for c in cases}
    cm = [v for k, v in res.items() if v is not None and lab[k]]
    no = [v for k, v in res.items() if v is not None and not lab[k]]
    auc = None
    if cm and no:
        a, b = np.array(cm), np.array(no)
        auc = float(((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean()))
    stats = {
        "n_cases": len(res),
        "n_with_ctr": sum(v is not None for v in res.values()),
        "n_out_of_range_set_null": n_out_of_range,
        "n_flagged_ctr_implausible_cardiomegaly": len(implausible),
        "cardiomegaly": {
            "n": len(cm),
            "mean": float(np.mean(cm)) if cm else None,
            "median": float(np.median(cm)) if cm else None,
        },
        "no_cardiomegaly": {
            "n": len(no),
            "mean": float(np.mean(no)) if no else None,
            "median": float(np.median(no)) if no else None,
        },
        "auc_ctr_vs_cardiomegaly_label": auc,
        "frac_ctr_gt_0.5_cardiomegaly": float(np.mean(np.array(cm) > 0.5)) if cm else None,
        "frac_ctr_gt_0.5_no_cardiomegaly": float(np.mean(np.array(no) > 0.5)) if no else None,
    }
    out = C.qa_dir() / "anatomy_ctr_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2))
    log.info("ctr done: %s; lines changed=%d", json.dumps(stats), changed)


if __name__ == "__main__":
    main()
