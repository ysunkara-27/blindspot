"""Zones and review areas from TXV anatomy masks — SPEC §4.3.

Convention (CLAUDE.md non-negotiable 3): patient RIGHT is displayed on the image LEFT. Zone ids name the
PATIENT's side. Input mask names are the patient-side TXV names ("Right Lung" = patient's right lung,
expected at small x) — orientation.py verifies that before zones are derived.

Zones are approximate anatomical regions (thirds of each lung's own extent, bands, dilations). They are
NOT lobes, rib levels, or distances; never describe them as such.

Batch entry point: `python -m pipeline.anatomy.zones` — writes data/processed/zones/<case_id>.json (RLE),
a small preview PNG, and fills finding locations (locate.py) + Case.anatomy_path/zones_path in cases.jsonl.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import cv2
import numpy as np

from pipeline.anatomy.common import zone_ids

LUNG_FAIL_FRAC = 0.03  # lung area < 3% of the image → anatomy_failed → approximate zones
APEX_FRAC = 0.18
CP_HEIGHT_FRAC = 0.18
CP_LATERAL_FRAC = 0.45
PERIPHERY_FRAC = 0.08  # of that lung's width
HILUM_DILATE_FRAC = 0.015  # of image width
SUBDIAPH_FRAC = 0.08  # of image height

SIDES = ("right", "left")


# --------------------------------------------------------------------------- small helpers
def _b(m: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
    if m is None:
        return np.zeros(shape, dtype=bool)
    m = np.asarray(m, dtype=bool)
    if m.shape != shape:
        raise ValueError(f"mask shape {m.shape} != {shape}")
    return m


def centroid(m: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def extent(m: np.ndarray) -> tuple[int, int, int, int] | None:
    """Inclusive (x0, y0, x1, y1) of a mask, or None if empty."""
    rows = np.flatnonzero(m.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(m.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def dilate(m: np.ndarray, r: float) -> np.ndarray:
    """Euclidean dilation by radius r (px)."""
    if r <= 0 or not m.any():
        return m.copy()
    d = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return d <= r


def inner_distance(m: np.ndarray) -> np.ndarray:
    """Distance (px) of each mask pixel to the nearest non-mask pixel; the image border counts as outside."""
    p = np.pad(m.astype(np.uint8), 1)
    d = cv2.distanceTransform(p, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return d[1:-1, 1:-1]


def lung_side_masks(zones: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {"right": zones["right_lung"], "left": zones["left_lung"]}


# --------------------------------------------------------------------------- core
def _lung_zones(lung: np.ndarray, side: str, yy: np.ndarray, xx: np.ndarray) -> dict[str, np.ndarray]:
    z: dict[str, np.ndarray] = {}
    ext = extent(lung)
    if ext is None:
        empty = np.zeros_like(lung)
        for k in ("upper_zone", "mid_zone", "lower_zone", "apex", "costophrenic_angle", "periphery"):
            z[f"{side}_{k}"] = empty.copy()
        return z
    x0, y0, x1, y1 = ext
    h = y1 - y0 + 1
    w = x1 - x0 + 1
    t1, t2 = y0 + h / 3.0, y0 + 2.0 * h / 3.0
    z[f"{side}_upper_zone"] = lung & (yy < t1)
    z[f"{side}_mid_zone"] = lung & (yy >= t1) & (yy < t2)
    z[f"{side}_lower_zone"] = lung & (yy >= t2)
    z[f"{side}_apex"] = lung & (yy < y0 + APEX_FRAC * h)
    # lateral = smaller x for the patient-right lung (image left), larger x for the patient-left lung
    lateral = (xx < x0 + CP_LATERAL_FRAC * w) if side == "right" else (xx >= x1 + 1 - CP_LATERAL_FRAC * w)
    z[f"{side}_costophrenic_angle"] = lung & (yy >= y1 + 1 - CP_HEIGHT_FRAC * h) & lateral
    z[f"{side}_periphery"] = lung & (inner_distance(lung) <= PERIPHERY_FRAC * w)
    return z


def _subdiaphragmatic(diaphragm: np.ndarray, lungs: np.ndarray, yy: np.ndarray, height: int) -> tuple[np.ndarray, bool]:
    """Band from the top edge of the diaphragm mask down SUBDIAPH_FRAC·H, within the lungs' x-range.

    Columns without diaphragm pixels are interpolated; with no diaphragm at all, the per-column lung
    bottom edge stands in for the diaphragm top (returns missing=True).
    """
    shape = lungs.shape
    lx = np.flatnonzero(lungs.any(axis=0))
    if lx.size == 0:
        return np.zeros(shape, dtype=bool), True
    cols = np.arange(lx[0], lx[-1] + 1)
    missing = not diaphragm.any()
    src = lungs if missing else diaphragm
    has = src[:, cols].any(axis=0)
    if missing:
        top = shape[0] - 1 - np.argmax(src[::-1, cols], axis=0)  # lung bottom edge
    else:
        top = np.argmax(src[:, cols], axis=0)  # first diaphragm row
    if not has.any():
        return np.zeros(shape, dtype=bool), True
    top = np.interp(cols, cols[has], top[has].astype(float))
    full_top = np.full(shape[1], np.inf)
    full_top[cols] = top
    band = (yy >= full_top[None, :]) & (yy < full_top[None, :] + SUBDIAPH_FRAC * height)
    return band, missing


def derive_zones(masks: dict[str, np.ndarray], width: int, height: int) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """SPEC §4.3. `masks` keyed by patient-side TXV names; missing structures are treated as empty.

    Returns (zones, meta). zones has every zone id in config/review_areas.yaml plus "right_lung",
    "left_lung", "lungs". meta: approximate, midline_x, flags, lung_area_frac, lung_extent.
    If either lung covers < 3% of the image, returns fixed-fraction approximate zones (approximate=True,
    flag "anatomy_failed").
    """
    shape = (int(height), int(width))
    rl = _b(masks.get("Right Lung"), shape)
    ll = _b(masks.get("Left Lung"), shape)
    area = float(width * height)
    fr, fl = rl.sum() / area, ll.sum() / area
    if fr < LUNG_FAIL_FRAC or fl < LUNG_FAIL_FRAC:
        zones, meta = approximate_zones(width, height)
        meta["flags"] = ["anatomy_failed"]
        meta["lung_area_frac"] = {"right": round(float(fr), 4), "left": round(float(fl), 4)}
        return zones, meta
    zones, meta = _derive(masks, width, height)
    meta["lung_area_frac"] = {"right": round(float(fr), 4), "left": round(float(fl), 4)}
    return zones, meta


def _derive(masks: dict[str, np.ndarray], width: int, height: int) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    shape = (int(height), int(width))
    g = {k: _b(masks.get(k), shape) for k in masks}
    get = lambda k: g.get(k, np.zeros(shape, dtype=bool))  # noqa: E731
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    flags: list[str] = []

    # midline = spine centroid x (fallback W/2, also when the spine centroid is implausible)
    xm = width / 2.0
    sc = centroid(get("Spine"))
    if sc is None:
        flags.append("spine_missing")
    elif not (0.25 * width <= sc[0] <= 0.75 * width):
        flags.append("spine_implausible")
    else:
        xm = sc[0]

    rl, ll = get("Right Lung"), get("Left Lung")
    z: dict[str, np.ndarray] = {}
    z.update(_lung_zones(rl, "right", yy, xx))
    z.update(_lung_zones(ll, "left", yy, xx))

    r_hil = dilate(get("Right Hilus Pulmonis"), HILUM_DILATE_FRAC * width)
    l_hil = dilate(get("Left Hilus Pulmonis"), HILUM_DILATE_FRAC * width)
    z["right_hilum"], z["left_hilum"] = r_hil, l_hil

    heart = get("Heart")
    lh = centroid(get("Left Hilus Pulmonis"))
    if lh is not None:
        hy = lh[1]
    else:
        flags.append("left_hilum_missing")
        rh = centroid(get("Right Hilus Pulmonis"))
        le = extent(ll)
        hy = rh[1] if rh is not None else ((le[1] + le[3]) / 2.0 if le else height / 2.0)
    z["retrocardiac"] = heart & (xx > xm) & (yy > hy)
    z["cardiac_silhouette"] = heart.copy()
    z["mediastinum"] = get("Mediastinum") | get("Aorta") | get("Weasand")
    sub, dia_missing = _subdiaphragmatic(get("Facies Diaphragmatica"), rl | ll, yy, height)
    if dia_missing:
        flags.append("diaphragm_missing")
    z["subdiaphragmatic"] = sub
    z["right_clavicle"] = get("Right Clavicle").copy()
    z["left_clavicle"] = get("Left Clavicle").copy()
    z["spine"] = get("Spine").copy()

    out = {k: z[k] for k in zone_ids()}
    out["right_lung"] = rl.copy()
    out["left_lung"] = ll.copy()
    out["lungs"] = rl | ll
    meta = {
        "approximate": False,
        "midline_x": float(xm),
        "flags": flags,
        "lung_extent": {"right": extent(rl), "left": extent(ll)},
    }
    return out, meta


def template_anatomy(width: int, height: int) -> dict[str, np.ndarray]:
    """Fixed-fraction stand-in anatomy (image halves and thirds) for when segmentation fails."""
    W, H = int(width), int(height)
    yy, xx = np.mgrid[0:H, 0:W]

    def box(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
        return (xx >= x0 * W) & (xx < x1 * W) & (yy >= y0 * H) & (yy < y1 * H)

    heart = (((xx - 0.55 * W) / (0.16 * W)) ** 2 + ((yy - 0.62 * H) / (0.13 * H)) ** 2) <= 1.0
    r_hil = ((xx - 0.40 * W) ** 2 + (yy - 0.42 * H) ** 2) <= (0.03 * W) ** 2
    l_hil = ((xx - 0.60 * W) ** 2 + (yy - 0.42 * H) ** 2) <= (0.03 * W) ** 2
    return {
        "Right Lung": box(0.08, 0.10, 0.48, 0.78),
        "Left Lung": box(0.52, 0.10, 0.92, 0.78),
        "Right Hilus Pulmonis": r_hil,
        "Left Hilus Pulmonis": l_hil,
        "Heart": heart,
        "Mediastinum": box(0.44, 0.08, 0.56, 0.55),
        "Facies Diaphragmatica": box(0.08, 0.78, 0.92, 0.86),
        "Right Clavicle": box(0.15, 0.10, 0.47, 0.15),
        "Left Clavicle": box(0.53, 0.10, 0.85, 0.15),
        "Spine": box(0.47, 0.0, 0.53, 1.0),
    }


def approximate_zones(width: int, height: int) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    zones, meta = _derive(template_anatomy(width, height), width, height)
    meta["approximate"] = True
    meta["midline_x"] = width / 2.0
    meta["flags"] = []
    return zones, meta


# --------------------------------------------------------------------------- previews
_PREVIEW_ORDER = [  # later entries paint over earlier ones
    ("right_upper_zone", (70, 110, 200)),
    ("right_mid_zone", (90, 150, 220)),
    ("right_lower_zone", (120, 180, 240)),
    ("left_upper_zone", (200, 120, 70)),
    ("left_mid_zone", (220, 150, 90)),
    ("left_lower_zone", (240, 180, 120)),
    ("cardiac_silhouette", (90, 60, 160)),
    ("mediastinum", (130, 130, 130)),
    ("spine", (180, 180, 180)),
    ("subdiaphragmatic", (60, 160, 160)),
    ("right_apex", (40, 200, 40)),
    ("left_apex", (40, 200, 40)),
    ("right_costophrenic_angle", (0, 220, 255)),
    ("left_costophrenic_angle", (0, 220, 255)),
    ("right_hilum", (0, 120, 255)),
    ("left_hilum", (0, 120, 255)),
    ("retrocardiac", (60, 0, 220)),
]


def zones_preview(zones: dict[str, np.ndarray], size: int = 256) -> np.ndarray:
    """BGR colour map of the zones (for /dev); image left = patient right."""
    h, w = next(iter(zones.values())).shape
    img = np.zeros((h, w, 3), np.uint8)
    for k, col in _PREVIEW_ORDER:
        if k in zones:
            img[zones[k]] = col
    return cv2.resize(img, (size, int(round(size * h / w))), interpolation=cv2.INTER_NEAREST)


# --------------------------------------------------------------------------- batch job
def process_case(c: dict[str, Any], previews: bool = True) -> tuple[str, dict[str, Any]]:
    """Derive + write zones for one case and locate its focal findings. Returns (case_id, result)."""
    from pipeline.anatomy import common as C
    from pipeline.anatomy.locate import locate_finding
    from shared.rle import write_zones

    proc = C.processed_dir()
    cid, W, H = c["case_id"], int(c["width"]), int(c["height"])
    npz = proc / C.anatomy_rel(cid)
    if npz.exists():
        masks, _ = C.load_anatomy(npz)
        zones, meta = derive_zones(masks, W, H)
        has_anat = True
    else:
        zones, meta = approximate_zones(W, H)
        meta["flags"] = ["anatomy_missing"]
        has_anat = False
    approx = bool(meta["approximate"])
    zpath = proc / C.zones_rel(cid)
    write_zones(zpath, cid, zones, approximate=approx, midline_x=meta["midline_x"])
    if previews:
        cv2.imwrite(str(zpath.with_suffix(".png")), zones_preview(zones))
    locs: dict[str, dict[str, Any]] = {}
    for f in c["findings"]:
        if f["kind"] != "focal":
            continue
        mp = f["geometry"].get("mask_path")
        if mp:
            fm = C.read_mask_png(mp, proc)
        else:
            x0, y0, x1, y1 = f["geometry"]["bbox"]
            fm = np.zeros((H, W), bool)
            fm[int(y0) : int(np.ceil(y1)), int(x0) : int(np.ceil(x1))] = True
        locs[f["finding_id"]] = locate_finding(fm, zones, meta["midline_x"], f["label"])
    return cid, {
        "anatomy_path": C.anatomy_rel(cid) if has_anat else None,
        "zones_path": C.zones_rel(cid),
        "approx": approx,
        "has_anat": has_anat,
        "flags": meta["flags"],
        "locs": locs,
    }


def _process_star(args: tuple[dict[str, Any], bool]) -> tuple[str, dict[str, Any]]:
    return process_case(*args)


def main(argv: list[str] | None = None) -> None:
    from concurrent.futures import ProcessPoolExecutor

    from pipeline.anatomy import common as C

    ap = argparse.ArgumentParser(description="Derive zones + finding locations for every case (SPEC §4.3-4.4)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-previews", action="store_true")
    ap.add_argument("--overlays", type=int, default=20, help="random QA overlays to write (0 = none)")
    args = ap.parse_args(argv)
    log = C.get_logger("zones")
    cases = C.read_cases()
    if args.limit:
        cases = cases[: args.limit]
    t0 = time.time()
    results: dict[str, dict[str, Any]] = {}
    jobs = [(c, not args.no_previews) for c in cases]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, (cid, r) in enumerate(ex.map(_process_star, jobs, chunksize=8)):
            results[cid] = r
            if (i + 1) % 500 == 0:
                el = time.time() - t0
                eta = (len(cases) - i - 1) * el / (i + 1)
                log.info("zones %d/%d  %.1f cases/s  eta %.0fs", i + 1, len(cases), (i + 1) / el, eta)
    n_seg = sum(r["has_anat"] and not r["approx"] for r in results.values())
    n_approx = sum(r["has_anat"] and r["approx"] for r in results.values())
    n_missing = sum(not r["has_anat"] for r in results.values())

    managed_flags = {"anatomy_failed", "anatomy_missing"}

    def upd(d: dict[str, Any]) -> None:
        r = results.get(d["case_id"])
        if r is None:
            return
        d["anatomy_path"] = r["anatomy_path"]
        d["zones_path"] = r["zones_path"]
        d["zones_approximate"] = r["approx"]
        d["qa_flags"] = [f for f in d.get("qa_flags", []) if f not in managed_flags]
        for fl in r["flags"]:
            if fl in managed_flags:
                C.add_flag(d, fl)
        for f in d["findings"]:
            loc = r["locs"].get(f["finding_id"])
            if loc:
                f.update(loc)

    changed = C.update_cases(upd)
    log.info(
        "zones done: %d cases in %.0fs; segmented=%d approximate(failed)=%d no_anatomy=%d; lines changed=%d",
        len(cases),
        time.time() - t0,
        n_seg,
        n_approx,
        n_missing,
        changed,
    )
    if args.overlays:
        from pipeline.anatomy.overlay import write_overlays

        write_overlays(n=args.overlays)


if __name__ == "__main__":
    main()
