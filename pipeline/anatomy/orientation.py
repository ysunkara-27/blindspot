"""Orientation check — SPEC §4.2.

Display convention: patient RIGHT appears on the image LEFT. Expected per case:
x(Right Lung) < x(Left Lung) and x(Heart) > W/2 − 0.05·W.

Global decision: if >= 80% of evaluable cases satisfy x(Right Lung) < x(Left Lung), the TXV channel names are
patient-side → keep. If >= 80% satisfy the reverse, swap every Left/Right channel name globally (rewrites the
"targets" array in each npz; idempotent because the next run then sees patient-side names). Otherwise
"undecided" → keep names, and the per-case flags still catch violations.
Per-case violations → qa flag `orientation_suspect` (splits exclude flagged cases from practice/assessment).

Run: python -m pipeline.anatomy.orientation   → data/qa/orientation_report.json
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np

from pipeline.anatomy import common as C
from pipeline.anatomy.zones import centroid

AGREE_FRAC = 0.80
HEART_MARGIN = 0.05
FLAG = "orientation_suspect"


def swap_name(name: str) -> str:
    if name.startswith("Left "):
        return "Right " + name[5:]
    if name.startswith("Right "):
        return "Left " + name[6:]
    return name


def case_orientation(masks: dict[str, np.ndarray], width: int) -> dict[str, Any]:
    """Centroid x of the lungs and heart + the two checks. None where a structure is empty."""
    cx = {
        k: (c[0] if (c := centroid(masks[k])) is not None else None)
        for k in ("Right Lung", "Left Lung", "Heart")
        if k in masks
    }
    rx, lx, hx = cx.get("Right Lung"), cx.get("Left Lung"), cx.get("Heart")
    lungs_ok = None if (rx is None or lx is None) else bool(rx < lx)
    heart_ok = None if hx is None else bool(hx > width / 2 - HEART_MARGIN * width)
    heart_image_right = None if hx is None else bool(hx > width / 2)
    sc = centroid(masks["Spine"]) if "Spine" in masks else None
    heart_right_of_spine = None if (hx is None or sc is None) else bool(hx > sc[0])
    return {
        "right_lung_x": rx,
        "left_lung_x": lx,
        "heart_x": hx,
        "lungs_ok": lungs_ok,
        "heart_ok": heart_ok,
        "heart_image_right": heart_image_right,
        "heart_right_of_spine": heart_right_of_spine,
        "suspect": (lungs_ok is False) or (heart_ok is False),
    }


def decide_global(lungs_ok: list[bool]) -> tuple[str, float]:
    """('keep' | 'swap' | 'undecided', fraction with x(Right Lung) < x(Left Lung))."""
    if not lungs_ok:
        return "undecided", float("nan")
    frac = float(np.mean(lungs_ok))
    if frac >= AGREE_FRAC:
        return "keep", frac
    if 1 - frac >= AGREE_FRAC:
        return "swap", frac
    return "undecided", frac


def _rewrite_targets_swapped(path) -> None:
    d = np.load(path, allow_pickle=False)
    data = {k: d[k] for k in d.files}
    d.close()
    data["targets"] = np.array([swap_name(str(t)) for t in data["targets"]])
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(tmp, **data)
    tmp.replace(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="report only; no swaps, no flags written")
    args = ap.parse_args(argv)
    log = C.get_logger("orientation")
    proc = C.processed_dir()
    cases = C.read_cases()
    recs: dict[str, dict[str, Any]] = {}
    for c in cases:
        p = proc / C.anatomy_rel(c["case_id"])
        if not p.exists():
            continue
        masks, _ = C.load_anatomy(p)
        recs[c["case_id"]] = case_orientation(masks, int(c["width"]))
    if not recs:
        log.warning("no anatomy npz files found under %s — run segment first", proc / "anatomy")
        return
    decision, frac = decide_global([r["lungs_ok"] for r in recs.values() if r["lungs_ok"] is not None])
    log.info(
        "orientation: %d cases with anatomy; frac x(Right Lung)<x(Left Lung) = %.4f → %s", len(recs), frac, decision
    )
    swapped = False
    if decision == "swap" and not args.dry_run:
        for cid in recs:
            _rewrite_targets_swapped(proc / C.anatomy_rel(cid))
        swapped = True
        # recompute per-case checks with patient-side names
        for cid in list(recs):
            masks, _ = C.load_anatomy(proc / C.anatomy_rel(cid))
            recs[cid] = case_orientation(masks, int(next(c for c in cases if c["case_id"] == cid)["width"]))
        log.warning("SWAPPED Left/Right channel names globally in %d npz files", len(recs))

    suspects = sorted(cid for cid, r in recs.items() if r["suspect"])
    non_flagged = [r for cid, r in recs.items() if not r["suspect"] and r["heart_image_right"] is not None]
    heart_right_frac = float(np.mean([r["heart_image_right"] for r in non_flagged])) if non_flagged else float("nan")
    all_heart = [r["heart_image_right"] for r in recs.values() if r["heart_image_right"] is not None]
    spine_nf = [r["heart_right_of_spine"] for r in non_flagged if r["heart_right_of_spine"] is not None]
    by_split: dict[str, dict[str, int]] = {}
    split_of = {c["case_id"]: c["split"] for c in cases}
    for cid, r in recs.items():
        s = by_split.setdefault(split_of.get(cid, "?"), {"n": 0, "suspect": 0})
        s["n"] += 1
        s["suspect"] += int(r["suspect"])
    report = {
        "convention": "patient RIGHT is displayed on the image LEFT; zone ids name the patient's side",
        "n_cases_with_anatomy": len(recs),
        "n_lungs_evaluable": sum(r["lungs_ok"] is not None for r in recs.values()),
        "frac_right_lung_left_of_left_lung": frac,
        "agree_threshold": AGREE_FRAC,
        "decision": decision,
        "txv_names_are_patient_side": decision in ("keep", "swap"),
        "swapped_channel_names": swapped,
        "heart_check": f"x(Heart) > W/2 - {HEART_MARGIN}*W",
        "heart_on_image_right_frac_all": float(np.mean(all_heart)) if all_heart else None,
        "heart_on_image_right_frac_non_flagged": heart_right_frac,
        "heart_right_of_spine_midline_frac_non_flagged": float(np.mean(spine_nf)) if spine_nf else None,
        "n_suspect": len(suspects),
        "n_lungs_reversed": sum(r["lungs_ok"] is False for r in recs.values()),
        "n_heart_left": sum(r["heart_ok"] is False for r in recs.values()),
        "by_split": by_split,
        "suspect_case_ids": suspects,
        "per_case_sample": {cid: recs[cid] for cid in suspects[:50]},
    }
    out = C.qa_dir() / "orientation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info(
        "suspect=%d (lungs reversed %d, heart left %d); heart on image right: %.4f of non-flagged → %s",
        report["n_suspect"],
        report["n_lungs_reversed"],
        report["n_heart_left"],
        heart_right_frac,
        out,
    )
    if args.dry_run:
        return
    sus = set(suspects)

    def upd(d: dict[str, Any]) -> None:
        if d["case_id"] not in recs:
            return
        if d["case_id"] in sus:
            C.add_flag(d, FLAG)
        else:
            C.remove_flag(d, FLAG)

    n = C.update_cases(upd)
    log.info("cases.jsonl updated (%d lines changed)", n)


if __name__ == "__main__":
    main()
