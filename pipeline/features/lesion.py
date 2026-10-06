"""Lesion features per focal finding — SPEC §4.5.

- contrast  = |mean(mask) − mean(ring)| / std(ring), ring = mask dilated 15 px minus mask (raw 8-bit intensities)
- edge_dist = distance from the finding centroid to the nearest lung boundary / width of that side's lung
              (unitless; never centimetres)
- model_prob = TXV DenseNet (densenet121-res224-all) image-level probability for the finding's label, null where
              the weights have no matching output (calcification, diffuse_nodule). NOTE: those weights were trained
              on NIH ChestX-ray14 among others, and ChestX-Det images come from NIH, so these probabilities are
              optimistic (possible train overlap). They are a weak difficulty feature only.
- Case.features: txv_prob_<label> for mapped labels, n_findings, n_focal.
zone_hardness and n_findings are derived again in difficulty.py from primary_zone / the case.

Run: python -m pipeline.features.lesion
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np

from pipeline.anatomy import common as C
from pipeline.anatomy.zones import dilate, extent

RING_PX = 15
MIN_RING_PX = 20


def ring_contrast(img: np.ndarray, mask: np.ndarray, ring_px: int = RING_PX) -> float | None:
    mask = np.asarray(mask, dtype=bool)
    e = extent(mask)
    if e is None:
        return None
    h, w = mask.shape
    x0, y0, x1, y1 = e
    sy = slice(max(0, y0 - ring_px - 1), min(h, y1 + ring_px + 2))
    sx = slice(max(0, x0 - ring_px - 1), min(w, x1 + ring_px + 2))
    m = mask[sy, sx]
    ring = dilate(m, ring_px) & ~m
    if np.count_nonzero(ring) < MIN_RING_PX:
        return None
    im = img[sy, sx].astype(np.float64)
    sd = float(im[ring].std())
    return float(abs(im[m].mean() - im[ring].mean()) / max(sd, 1.0))


def _boundary(m: np.ndarray) -> np.ndarray:
    er = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8), borderValue=0) > 0
    return m & ~er


def edge_distance(cxy: tuple[float, float], zones: Mapping[str, np.ndarray], side: str | None) -> float | None:
    """Distance from the centroid to the nearest lung boundary pixel / lung width of the finding's side."""
    lungs = zones["lungs"]
    b = _boundary(lungs)
    ys, xs = np.nonzero(b)
    if xs.size == 0:
        return None
    d = float(np.sqrt(np.min((xs - cxy[0]) ** 2 + (ys - cxy[1]) ** 2)))
    widths = []
    for s in ("right", "left") if side not in ("right", "left") else (side,):
        e = extent(zones[f"{s}_lung"])
        if e is not None:
            widths.append(e[2] - e[0] + 1)
    if not widths:
        return None
    return d / float(np.mean(widths))


def classifier_probs(extras: Mapping[str, Any]) -> dict[str, float]:
    """{label: prob} for labels in TXV_CLASSIFIER_MAP, from an anatomy npz's txv_probs/txv_pathologies."""
    if "txv_probs" not in extras or "txv_pathologies" not in extras:
        return {}
    names = [str(n) for n in extras["txv_pathologies"]]
    probs = np.asarray(extras["txv_probs"], dtype=float)
    out = {}
    for label, pname in C.TXV_CLASSIFIER_MAP.items():
        if pname in names:
            out[label] = float(probs[names.index(pname)])
    return out


def lesion_case(c: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from shared.rle import read_zones

    proc = C.processed_dir()
    feats: dict[str, float] = {
        "n_findings": float(len(c["findings"])),
        "n_focal": float(sum(f["kind"] == "focal" for f in c["findings"])),
    }
    probs: dict[str, float] = {}
    if c.get("anatomy_path") and (proc / c["anatomy_path"]).exists():
        _, extras = C.load_anatomy(proc / c["anatomy_path"], clean=False)
        probs = classifier_probs(extras)
        feats.update({f"txv_prob_{k}": round(v, 5) for k, v in probs.items()})
    per: dict[str, dict[str, Any]] = {}
    focal = [f for f in c["findings"] if f["kind"] == "focal"]
    if focal:
        img = cv2.imread(str(proc / c["image_path"]), cv2.IMREAD_GRAYSCALE)
        zones = read_zones(proc / c["zones_path"])[0] if c.get("zones_path") else None
        for f in focal:
            fm = C.read_mask_png(f["geometry"]["mask_path"], proc) if f["geometry"].get("mask_path") else None
            ctr = ring_contrast(img, fm) if fm is not None else None
            ed = edge_distance(tuple(f["centroid"]), zones, f.get("side")) if zones is not None else None
            mp = probs.get(f["label"])
            per[f["finding_id"]] = {
                "contrast": None if ctr is None else round(ctr, 4),
                "edge_dist": None if ed is None else round(ed, 4),
                "model_prob": None if mp is None else round(mp, 5),
            }
    return c["case_id"], {"features": feats, "per": per}


def main(argv: list[str] | None = None) -> None:
    from concurrent.futures import ProcessPoolExecutor

    ap = argparse.ArgumentParser(description="lesion features (SPEC §4.5)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    log = C.get_logger("lesion")
    cases = C.read_cases()
    if args.limit:
        cases = cases[: args.limit]
    t0 = time.time()
    res: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, (cid, r) in enumerate(ex.map(lesion_case, cases, chunksize=8)):
            res[cid] = r
            if (i + 1) % 500 == 0:
                log.info("lesion %d/%d (%.1f cases/s)", i + 1, len(cases), (i + 1) / (time.time() - t0))
    per_all = [v for r in res.values() for v in r["per"].values()]
    n_f = len(per_all)
    n_contrast = sum(v["contrast"] is not None for v in per_all)
    n_edge = sum(v["edge_dist"] is not None for v in per_all)
    n_prob = sum(v["model_prob"] is not None for v in per_all)

    def upd(d: dict[str, Any]) -> None:
        r = res.get(d["case_id"])
        if r is None:
            return
        feats = {k: v for k, v in d.get("features", {}).items() if not k.startswith("txv_prob_")}
        feats.update(r["features"])
        d["features"] = feats
        for f in d["findings"]:
            if f["finding_id"] in r["per"]:
                f.update(r["per"][f["finding_id"]])

    changed = C.update_cases(upd)
    log.info(
        "lesion done in %.0fs: focal=%d contrast=%d edge_dist=%d model_prob=%d (null where unmapped); lines changed=%d",
        time.time() - t0,
        n_f,
        n_contrast,
        n_edge,
        n_prob,
        changed,
    )


if __name__ == "__main__":
    main()
