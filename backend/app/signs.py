"""Sign annotations drawn on the film after submit (clinician feedback, round 4): for every finding, the classic
radiological sign the tutor would point at — the visceral pleural line, the meniscus, the silhouette sign, the
cardiothoracic ratio — as geometry in image pixels, computed deterministically from the expert instance mask and the
anatomy masks (torchxrayvision: lungs, heart, diaphragm) or the zone masks when anatomy is missing.

Truth stays with the annotations: every sign is derived from the radiologist mask of THAT finding; nothing here
decides what is on the image. Text comes from the teaching card's key signs where possible, is at most 16 words,
and never states centimetres or millimetres (the only measured number is the automatic cardiothoracic ratio).

Shapes (shared/contracts.py Sign / SignGeometry; kinds polyline, polygon, circle, arrow, segment, band):
- X-ray: `points` are (x, y) in the canonical PNG pixel space; `plane` / `slice` are None.
- CT / MR: `points` are in-plane (x, y) voxel coordinates on the axial measure slice; plane "axial", slice set.
- circle: points = [centre], radius set · arrow: points = [tail, head] · segment: points = [a, b]
- band: a polyline with `radius` = half-width · polygon: closed outline (first point not repeated).

At most MAX_SIGNS per finding; ids are "<finding short id>:<sign key>".
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from backend.app import config
from backend.app.cases import CaseRepository, dilate
from shared.contracts import Case, Finding, Sign, SignGeometry, SignSchematic

log = logging.getLogger("blindspot.signs")

MAX_SIGNS = 3
MAX_WORDS = 16
MAX_POINTS = 40  # polylines / polygons are simplified down to this many vertices
BORDER_PX = 6  # "touches the heart / diaphragm" = boundary within this many pixels of the organ mask
LUNG_TOUCH_PX = 4  # pneumothorax: boundary within this distance of aerated lung = the visceral pleural line
DEPTH_SPLIT = 0.3  # outline vertices deeper into the lung than this fraction of the depth range face the lung
MIN_RUN_PX = 24  # a boundary run shorter than this (chord) is not drawn
CIRCLE_FACTOR = 1.3  # circle radius = 1.3 × the mask's equivalent radius
MIN_CIRCLE_PX = 12
ARROW_LEN_FRAC = 0.06  # arrow length as a fraction of the image width
BAND_HALF_PX = 8
CP_CIRCLE_FRAC = 0.03  # blunted-angle circle radius as a fraction of the image width
SMOOTH_WIN = 15  # moving-average window (px) for edge profiles (meniscus)
LARGE_EFFUSION_FRAC = 0.45  # fluid whose top reaches above this fraction of the lung's height has no meniscus to trace

# Anatomy npz target names (shared/rle.py) — patient-side after the pipeline's orientation check.
A_RIGHT_LUNG, A_LEFT_LUNG, A_HEART, A_DIAPHRAGM = "Right Lung", "Left Lung", "Heart", "Facies Diaphragmatica"

# Sign names: the vocabulary the tutor may use when it says "look at the … drawn on the film". The validator allows
# exactly the names FACTS lists in signs_drawn (and whatever the teaching cards already say).
SIGN_NAMES: dict[str, str] = {
    "pleural_line": "Visceral pleural line",
    "no_markings": "Air beyond the lung edge",
    "deep_sulcus": "Deep sulcus sign",
    "meniscus": "Meniscus",
    "blunted_angle": "Blunted costophrenic angle",
    "white_out": "Dense lower zone",
    "ctr_heart": "Heart width",
    "ctr_chest": "Chest width",
    "silhouette": "Silhouette sign",
    "opacity": "Patchy opacity",
    "volume_loss": "Volume loss",
    "round_opacity": "Round opacity",
    "dense_spot": "Dense spot",
    "cortical_break": "Break in the cortical line",
    "pleural_band": "Pleural band",
    "pattern": "Pattern extent",
    "flat_diaphragm": "Flattened diaphragm",
    "lesion": "Lesion outline",
    "pointer": "Pointer",
    "enhancing": "Enhancing component",
}

# Text per sign key (≤ 16 words; from the card's key signs where one fits). Never cm / mm.
SIGN_TEXT: dict[str, str] = {
    "pleural_line": "A thin white line parallel to the chest wall: the visceral pleura",
    "no_markings": "No lung markings beyond this line",
    "deep_sulcus": "Unusually deep, dark costophrenic angle (deep sulcus sign)",
    "meniscus": "A curved fluid edge that rises higher along the outer chest wall",
    "blunted_angle": "Blunting of the costophrenic angle: the sharp corner is filled in",
    "white_out": "A white lower zone that hides the outline of the diaphragm",
    "silhouette": "The heart/diaphragm border is lost where the opacity touches it",
    "opacity_consolidation": "Patchy opacity with ill-defined margins",
    "opacity_atelectasis": "A white area with volume loss; a fissure, hilum or diaphragm pulled toward it",
    "nodule": "Round, well-defined opacity; compare with vessels seen end-on",
    "mass": "A large, rounded white area with a visible edge",
    "calcification": "A very dense spot, as bright as nearby bone",
    "fracture": "Break in the cortical line; follow the rib around",
    "pleural_thickening": "A smooth white band along the inside of the chest wall",
    "flat_diaphragm": "Flattened diaphragm dome: over-inflated lungs",
    "pancreatic_tumour": "A hypoattenuating (darker) area inside the pancreas",
    "liver_tumour": "A rounded area darker or brighter than the liver around it",
    "brain_tumour": "A dark core inside a bright enhancing rim; oedema around it",
    "lung_tumour": "A soft-tissue density inside the air-filled lung with irregular edges",
    "colon_tumour": "Asymmetric thickening of the bowel wall that enhances with contrast",
    "pointer": "Compare this spot with the same level on the other side",
    "pointer_body": "Scroll a few slices up and down: a lesion keeps its shape, a vessel does not",
    "enhancing": "Enhancement on T1 after contrast: bright tissue normal brain does not show",
}

SCHEMATICS: dict[str, str] = {
    "pleural_line": "visceral_pleural_line",
    "deep_sulcus": "deep_sulcus",
    "meniscus": "meniscus_sign",
    "blunted_angle": "meniscus_sign",
    "ctr_heart": "cardiothoracic_ratio",
    "silhouette": "silhouette_sign",
    "opacity": "air_bronchogram",
    "round_opacity": "mass_vs_nodule",
    "cortical_break": "rib_fracture_cortex",
    "pleural_band": "pleural_thickening_band",
    "ct_lesion": "ct_hypoenhancing_mass",
    "mr_lesion": "mr_ring_enhancement",
    "enhancing": "mr_ring_enhancement",
}

Pt = tuple[float, float]
CTR_TEXT = (
    "Cardiothoracic ratio: heart width over chest width = {ctr:.2f} (measured automatically; PA vs AP not recorded)"
)


# ------------------------------------------------------------------ small geometry helpers (pure)
def clip_words(text: str, n: int = MAX_WORDS) -> str:
    w = text.split()
    return " ".join(w[:n]) if len(w) > n else text


def _pt(x: float, y: float) -> Pt:
    return (round(float(x), 1), round(float(y), 1))


def mask_centroid(m: np.ndarray) -> Pt | None:
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def equivalent_radius(m: np.ndarray) -> float:
    return float(np.sqrt(max(1.0, float(m.sum())) / np.pi))


def largest_contour(m: np.ndarray) -> np.ndarray | None:
    """(N, 2) int points of the largest external contour, in order; None for an empty mask."""
    cnts, _ = cv2.findContours(np.ascontiguousarray(m, dtype=np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    return c.reshape(-1, 2)


def simplify(points: np.ndarray, closed: bool, max_points: int = MAX_POINTS) -> list[Pt]:
    """approxPolyDP with a growing epsilon until ≤ max_points vertices."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) <= 2:
        return [_pt(x, y) for x, y in pts.reshape(-1, 2)]
    peri = cv2.arcLength(pts, closed)
    eps = max(0.5, 0.004 * peri)
    approx = cv2.approxPolyDP(pts, eps, closed)
    while len(approx) > max_points:
        eps *= 1.5
        approx = cv2.approxPolyDP(pts, eps, closed)
    return [_pt(x, y) for x, y in approx.reshape(-1, 2)]


def longest_run(contour: np.ndarray, ok: np.ndarray) -> np.ndarray | None:
    """The longest circular run of contour vertices whose `ok[i]` is True (ordered, as an open polyline)."""
    n = len(contour)
    ok = np.asarray(ok, dtype=bool)
    if n == 0 or ok.shape != (n,):
        return None
    if ok.all():
        return contour
    if not ok.any():
        return None
    start = int(np.argmin(ok))  # rotate so the sequence starts at a False vertex
    idx = (np.arange(n) + start) % n
    ok_r = ok[idx]
    best, cur = (0, 0), None
    for i, v in enumerate(ok_r):
        if v and cur is None:
            cur = i
        if (not v or i == n - 1) and cur is not None:
            end = i + 1 if v else i
            if end - cur > best[1] - best[0]:
                best = (cur, end)
            cur = None
    if best[1] - best[0] < 2:
        return None
    return contour[idx[best[0] : best[1]]]


def run_length(points: np.ndarray) -> float:
    if points is None or len(points) < 2:
        return 0.0
    d = np.diff(points.astype(float), axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def boundary_run(m: np.ndarray, keep: np.ndarray, min_len: float = MIN_RUN_PX) -> list[Pt] | None:
    """Simplified polyline of the longest stretch of M's outline whose pixels lie in `keep`; None when too short."""
    c = largest_contour(m)
    if c is None:
        return None
    run = longest_run(c, keep[c[:, 1], c[:, 0]])
    if run is None or run_length(run) < min_len:
        return None
    return simplify(run, closed=False)


def signed_depth(lung: np.ndarray) -> np.ndarray:
    """Signed distance into the lung mask: positive inside (distance to its edge), negative outside."""
    inside = cv2.distanceTransform(lung.astype(np.uint8), cv2.DIST_L2, 3)
    outside = cv2.distanceTransform((~lung).astype(np.uint8), cv2.DIST_L2, 3)
    return inside - outside


def lung_facing_run(m: np.ndarray, lung: np.ndarray, facing_lung: bool, min_len: float = MIN_RUN_PX) -> list[Pt] | None:
    """The half of M's outline that faces the aerated lung (facing_lung) or the chest wall (not facing_lung), decided
    by the signed depth into the lung mask: the pleural space of a pneumothorax is often segmented as lung, so the
    chest-wall side is simply the shallower side. Only outline pixels adjacent to lung-not-M count as lung-facing."""
    c = largest_contour(m)
    if c is None:
        return None
    depth = signed_depth(lung)[c[:, 1], c[:, 0]]
    lo, hi = float(depth.min()), float(depth.max())
    adjacent = dilate(lung & ~m, LUNG_TOUCH_PX)[c[:, 1], c[:, 0]]
    if facing_lung:
        ok = (depth >= lo + DEPTH_SPLIT * (hi - lo)) & adjacent
    else:
        ok = (depth <= hi - DEPTH_SPLIT * (hi - lo)) | ~adjacent
    run = longest_run(c, ok)
    if run is None or run_length(run) < min_len:
        return None
    return simplify(run, closed=False)


def top_edge(m: np.ndarray, smooth: int = SMOOTH_WIN) -> list[Pt] | None:
    """Per-column top-most pixel of M across its x-extent, moving-average smoothed, simplified."""
    if not m.any():
        return None
    has = m.any(axis=0)
    xs = np.flatnonzero(has)
    ys = np.array([int(np.argmax(m[:, x])) for x in xs], dtype=float)
    if len(xs) < 3:
        return None
    k = max(1, min(smooth, len(ys)))
    ys = np.convolve(np.pad(ys, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, mode="valid")
    return simplify(np.stack([xs, ys], axis=1), closed=False)


def side_edge(m: np.ndarray, lateral_left: bool) -> list[Pt] | None:
    """Per-row extreme pixel of M on one side (lateral_left: the smallest x per row), simplified."""
    if not m.any():
        return None
    rows = np.flatnonzero(m.any(axis=1))
    if len(rows) < 3:
        return None
    xs = []
    for y in rows:
        cols = np.flatnonzero(m[y])
        xs.append(cols.min() if lateral_left else cols.max())
    return simplify(np.stack([np.asarray(xs, float), rows.astype(float)], axis=1), closed=False)


def hull_polygon(m: np.ndarray) -> list[Pt] | None:
    ys, xs = np.nonzero(m)
    if xs.size < 3:
        return None
    pts = np.stack([xs, ys], axis=1).astype(np.int32)
    if len(pts) > 20000:
        pts = pts[:: len(pts) // 20000 + 1]
    hull = cv2.convexHull(np.ascontiguousarray(pts)).reshape(-1, 2)
    return simplify(hull, closed=True, max_points=24)


def outline_polygon(m: np.ndarray) -> list[Pt] | None:
    c = largest_contour(m)
    return simplify(c, closed=True, max_points=24) if c is not None and len(c) >= 3 else None


def principal_axis(m: np.ndarray) -> list[Pt] | None:
    """Long axis of M (PCA of mask pixels): the segment between the extreme projections, through the centroid."""
    ys, xs = np.nonzero(m)
    if xs.size < 3:
        return None
    pts = np.stack([xs, ys], axis=1).astype(float)
    c = pts.mean(axis=0)
    cov = np.cov((pts - c).T)
    w, v = np.linalg.eigh(cov)
    axis = v[:, int(np.argmax(w))]
    proj = (pts - c) @ axis
    a, b = c + axis * proj.min(), c + axis * proj.max()
    mid = (a + b) / 2
    return [_pt(*a), _pt(*mid), _pt(*b)]


def point_inside(m: np.ndarray, p: Pt) -> Pt:
    """`p` when it lies on M, else the M pixel nearest to it."""
    x, y = int(round(p[0])), int(round(p[1]))
    h, w = m.shape
    if 0 <= y < h and 0 <= x < w and m[y, x]:
        return p
    ys, xs = np.nonzero(m)
    if xs.size == 0:
        return p
    k = int(np.argmin((xs - p[0]) ** 2 + (ys - p[1]) ** 2))
    return float(xs[k]), float(ys[k])


def _is_right(f: Finding, cx: float, width: int) -> bool:
    """Patient RIGHT = image left (CLAUDE.md non-negotiable 3)."""
    if f.side == "right":
        return True
    if f.side == "left":
        return False
    return cx < width / 2


def _in_zone(zones: dict[str, np.ndarray], zone: str, p: Pt) -> bool:
    z = zones.get(zone)
    if z is None:
        return False
    x, y = int(round(p[0])), int(round(p[1]))
    return 0 <= y < z.shape[0] and 0 <= x < z.shape[1] and bool(z[y, x])


def _words(s: str) -> int:
    return len(s.split())


# ------------------------------------------------------------------ anatomy access
class Anatomy:
    """Lungs / heart / diaphragm as bool masks: anatomy npz first, zones as the fallback (None when neither)."""

    def __init__(self, masks: dict[str, np.ndarray] | None, zones: dict[str, np.ndarray]):
        self.masks = masks or {}
        self.zones = zones
        self.from_anatomy = bool(masks)

    def lung(self, right: bool) -> np.ndarray | None:
        m = self.masks.get(A_RIGHT_LUNG if right else A_LEFT_LUNG)
        return m if m is not None else self.zones.get("right_lung" if right else "left_lung")

    def lungs(self) -> np.ndarray | None:
        r, left = self.lung(True), self.lung(False)
        if r is None or left is None:
            return self.zones.get("lungs")
        return r | left

    def heart(self) -> np.ndarray | None:
        m = self.masks.get(A_HEART)
        return m if m is not None else self.zones.get("cardiac_silhouette")

    def diaphragm(self) -> np.ndarray | None:
        return self.masks.get(A_DIAPHRAGM)  # no zone stands in for the diaphragm contour


# ------------------------------------------------------------------ sign builders (X-ray)
def _sign(
    fid: str,
    key: str,
    kind: str,
    points: Sequence[Pt],
    text: str,
    *,
    radius: float | None = None,
    name: str | None = None,
    schematic: str | None = None,
    plane: str | None = None,
    slice_: int | None = None,
) -> Sign:
    return Sign(
        id=f"{fid}:{key}",
        name=name or SIGN_NAMES.get(key, key.replace("_", " ").capitalize()),
        text=clip_words(text),
        geometry=SignGeometry(
            kind=kind,  # type: ignore[arg-type]
            points=[_pt(*p) for p in points],
            radius=round(float(radius), 1) if radius is not None else None,
            plane=plane,
            slice=slice_,
        ),
        schematic=schematic,
    )


def _pneumothorax(fid: str, f: Finding, m: np.ndarray, an: Anatomy, width: int) -> list[Sign]:
    out: list[Sign] = []
    c = mask_centroid(m)
    if c is None:
        return out
    right = _is_right(f, c[0], width)
    lung = an.lung(right)
    line = None
    if lung is not None and (lung & ~m).any():
        line = lung_facing_run(m, lung, facing_lung=True)
    if line is None:  # no lung mask: keep the medial and inferior edges of M (the side facing the lung)
        h, w = m.shape
        yy, xx = np.mgrid[0:h, 0:w]
        line = boundary_run(m, ((xx > c[0]) if right else (xx < c[0])) | (yy > c[1]))
    if line:
        sch = SCHEMATICS["pleural_line"]
        out.append(_sign(fid, "pleural_line", "polyline", line, SIGN_TEXT["pleural_line"], schematic=sch))
    # arrow from inside M pointing laterally (toward the chest wall: image left for the patient's right)
    tail = point_inside(m, c)
    dx = -1.0 if right else 1.0
    length = ARROW_LEN_FRAC * width
    head = (min(max(tail[0] + dx * length, 0.0), width - 1.0), tail[1])
    out.append(_sign(fid, "no_markings", "arrow", [tail, head], SIGN_TEXT["no_markings"]))
    side = "right" if right else "left"
    cp = an.zones.get(f"{side}_costophrenic_angle")
    if _in_zone(an.zones, f"{side}_lower_zone", c) and cp is not None and (m & cp).any():
        pts = bottom_edge(m & cp) or side_edge(m & cp, lateral_left=right)
        if pts:
            sch = SCHEMATICS["deep_sulcus"]
            out.append(
                _sign(fid, "deep_sulcus", "band", pts, SIGN_TEXT["deep_sulcus"], radius=BAND_HALF_PX, schematic=sch)
            )
    return out[:MAX_SIGNS]


def bottom_edge(m: np.ndarray) -> list[Pt] | None:
    """Per-column bottom-most pixel of M (the top edge of the vertically flipped mask), simplified."""
    edge = top_edge(m[::-1])
    return [_pt(x, m.shape[0] - 1 - y) for x, y in edge] if edge else None


def _effusion(fid: str, f: Finding, m: np.ndarray, an: Anatomy, width: int) -> list[Sign]:
    out: list[Sign] = []
    c = mask_centroid(m)
    if c is None:
        return out
    right = _is_right(f, c[0], width)
    side = "right" if right else "left"
    edge = top_edge(m)
    lung = an.lung(right)
    large = False
    if edge and lung is not None and lung.any():
        rows = np.flatnonzero(lung.any(axis=1))
        top, bottom = float(rows.min()), float(rows.max())
        large = min(y for _, y in edge) < top + LARGE_EFFUSION_FRAC * (bottom - top)
    if edge and not large:
        out.append(_sign(fid, "meniscus", "polyline", edge, SIGN_TEXT["meniscus"], schematic=SCHEMATICS["meniscus"]))
    elif edge:  # fluid reaching the upper half of the hemithorax: no meniscus to trace, outline the white-out
        poly = outline_polygon(m)
        if poly:
            out.append(_sign(fid, "white_out", "polygon", poly, SIGN_TEXT["white_out"]))
    cp = an.zones.get(f"{side}_costophrenic_angle")
    if cp is not None and (m & cp).any():
        ys, xs = np.nonzero(m & cp)
        # the costophrenic corner: lowest, most lateral pixel of M inside the angle
        score = ys + (-(xs) if right else xs)
        k = int(np.argmax(score))
        centre = (float(xs[k]), float(ys[k]))
        sch = SCHEMATICS["blunted_angle"]
        out.append(
            _sign(
                fid,
                "blunted_angle",
                "circle",
                [centre],
                SIGN_TEXT["blunted_angle"],
                radius=CP_CIRCLE_FRAC * width,
                schematic=sch,
            )
        )
    return out[:MAX_SIGNS]


def heart_width_segment(heart: np.ndarray) -> tuple[Pt, Pt] | None:
    """Widest row of the heart mask: (leftmost, rightmost) at that row."""
    if heart is None or not heart.any():
        return None
    rows = np.flatnonzero(heart.any(axis=1))
    best, best_w = None, -1
    for y in rows:
        cols = np.flatnonzero(heart[y])
        wdt = int(cols.max() - cols.min())
        if wdt > best_w:
            best_w, best = wdt, (float(cols.min()), float(y), float(cols.max()))
    if best is None:
        return None
    x0, y, x1 = best
    return (x0, y), (x1, y)


def thoracic_width_segment(right_lung: np.ndarray, left_lung: np.ndarray) -> tuple[Pt, Pt] | None:
    """Outer lung edges at the row of the widest inner thoracic span (right lung's outer edge to left lung's)."""
    if right_lung is None or left_lung is None:
        return None
    rows = np.flatnonzero(right_lung.any(axis=1) & left_lung.any(axis=1))
    best, best_w = None, -1
    for y in rows:
        r, left = np.flatnonzero(right_lung[y]), np.flatnonzero(left_lung[y])
        x0, x1 = int(r.min()), int(left.max())
        if x1 - x0 > best_w:
            best_w, best = x1 - x0, (float(x0), float(y), float(x1))
    if best is None:
        return None
    x0, y, x1 = best
    return (x0, y), (x1, y)


def _cardiomegaly(fid: str, case: Case, m: np.ndarray, an: Anatomy) -> list[Sign]:
    heart = an.heart() if an.from_anatomy else None
    if heart is None or not heart.any():
        heart = m  # the expert outline of the enlarged heart
    hs = heart_width_segment(heart)
    ts = thoracic_width_segment(an.lung(True), an.lung(False))
    if hs is None or ts is None:
        return []
    hw, tw = hs[1][0] - hs[0][0], ts[1][0] - ts[0][0]
    ctr = case.cardiothoracic_ratio if case.cardiothoracic_ratio is not None else (hw / tw if tw > 0 else None)
    if ctr is None:
        return []
    text = CTR_TEXT.format(ctr=ctr)
    return [
        _sign(fid, "ctr_heart", "segment", hs, text, schematic=SCHEMATICS["ctr_heart"]),
        _sign(fid, "ctr_chest", "segment", ts, text),
    ]


def _opacity(fid: str, f: Finding, m: np.ndarray, an: Anatomy) -> list[Sign]:
    organs = [x for x in (an.heart(), an.diaphragm()) if x is not None]
    if organs:
        near = dilate(np.logical_or.reduce(organs), BORDER_PX)
        line = boundary_run(m, near)
        if line:
            return [
                _sign(fid, "silhouette", "polyline", line, SIGN_TEXT["silhouette"], schematic=SCHEMATICS["silhouette"])
            ]
    poly = outline_polygon(m)
    if not poly:
        return []
    if f.label == "atelectasis":
        return [_sign(fid, "volume_loss", "polygon", poly, SIGN_TEXT["opacity_atelectasis"])]
    return [_sign(fid, "opacity", "polygon", poly, SIGN_TEXT["opacity_consolidation"], schematic=SCHEMATICS["opacity"])]


def _round(fid: str, f: Finding, m: np.ndarray) -> list[Sign]:
    c = mask_centroid(m)
    if c is None:
        return []
    r = max(MIN_CIRCLE_PX, CIRCLE_FACTOR * equivalent_radius(m))
    if f.label == "calcification":
        return [_sign(fid, "dense_spot", "circle", [c], SIGN_TEXT["calcification"], radius=r)]
    sch = SCHEMATICS["round_opacity"] if f.label == "mass" else None
    return [_sign(fid, "round_opacity", "circle", [c], SIGN_TEXT[f.label], radius=r, schematic=sch)]


def _fracture(fid: str, m: np.ndarray) -> list[Sign]:
    axis = principal_axis(m)
    if not axis:
        return []
    return [
        _sign(fid, "cortical_break", "polyline", axis, SIGN_TEXT["fracture"], schematic=SCHEMATICS["cortical_break"])
    ]


def _pleural_thickening(fid: str, f: Finding, m: np.ndarray, an: Anatomy, width: int) -> list[Sign]:
    c = mask_centroid(m)
    if c is None:
        return []
    right = _is_right(f, c[0], width)
    lung = an.lung(right)
    pts = None
    if lung is not None and (lung & ~m).any():
        pts = lung_facing_run(m, lung, facing_lung=False)  # the chest-wall side
    if not pts:
        pts = side_edge(m, lateral_left=right)
    if not pts:
        return []
    sch = SCHEMATICS["pleural_band"]
    return [
        _sign(fid, "pleural_band", "band", pts, SIGN_TEXT["pleural_thickening"], radius=BAND_HALF_PX, schematic=sch)
    ]


def _pattern(fid: str, f: Finding, m: np.ndarray, an: Anatomy, card_sign: str | None, width: int) -> list[Sign]:
    out: list[Sign] = []
    hull = hull_polygon(m)
    if hull:
        out.append(_sign(fid, "pattern", "polygon", hull, card_sign or "Where the pattern is heaviest"))
    if f.label == "emphysema":
        dia = an.diaphragm()
        if dia is not None and dia.any():
            c = mask_centroid(m)
            right = _is_right(f, c[0], width) if c else True
            lung = an.lung(right)
            if lung is not None and lung.any():
                xs = np.flatnonzero(lung.any(axis=0))
                x0, x1 = xs[int(0.15 * len(xs))], xs[int(0.85 * len(xs))]  # central part of the dome only
                cols = np.zeros(lung.shape[1], bool)
                cols[x0 : x1 + 1] = True
                edge = top_edge(dia & cols[None, :], smooth=25)
                if edge and len(edge) >= 2:  # a level line at the dome's apex across the central dome
                    apex_y = min(y for _, y in edge)
                    seg = [(float(x0), apex_y), (float(x1), apex_y)]
                    out.append(_sign(fid, "flat_diaphragm", "segment", seg, SIGN_TEXT["flat_diaphragm"]))
    return out[:MAX_SIGNS]


# ------------------------------------------------------------------ sign builders (CT / MR)
def _volume_signs(fid: str, f: Finding, case: Case, repo: CaseRepository) -> list[Sign]:
    fm = repo.finding_volmask(case.case_id, f.finding_id)
    if fm is None or not fm.any():
        return []
    nz, ny, nx = fm.shape
    z = f.measure.slice if f.measure is not None else (int(round(f.centroid3[2])) if f.centroid3 else None)
    if z is None or not (0 <= z < nz) or not fm[z].any():
        zs = np.flatnonzero(fm.any(axis=(1, 2)))
        z = int(zs[len(zs) // 2]) if zs.size else None
        if z is None:
            return []
    sl = fm[z]
    c = mask_centroid(sl)
    if c is None:
        return []
    r = max(6.0, CIRCLE_FACTOR * equivalent_radius(sl))
    key = "mr_lesion" if case.modality == "mr" else "ct_lesion"
    text = SIGN_TEXT.get(f.label, "The lesion on its widest slice")
    out = [_sign(fid, "lesion", "circle", [c], text, radius=r, schematic=SCHEMATICS[key], plane="axial", slice_=z)]
    # arrow from outside, pointing at the lesion along the direction away from the slice centre
    vx, vy = c[0] - nx / 2, c[1] - ny / 2
    n = float(np.hypot(vx, vy))
    ux, uy = (vx / n, vy / n) if n > 1e-6 else (-0.7071, -0.7071)
    head = (c[0] + ux * r, c[1] + uy * r)
    tail = (c[0] + ux * (r + max(12.0, 0.12 * max(nx, ny))), c[1] + uy * (r + max(12.0, 0.12 * max(nx, ny))))
    tail = (min(max(tail[0], 0.0), nx - 1.0), min(max(tail[1], 0.0), ny - 1.0))
    ptext = SIGN_TEXT["pointer" if case.body_region == "brain" else "pointer_body"]
    out.append(_sign(fid, "pointer", "arrow", [tail, head], ptext, plane="axial", slice_=z))
    if case.body_region == "brain" and f.components:
        enh = next((comp for comp in f.components if "enhanc" in comp.name.lower()), None)
        mv = repo.maskvol(case.case_id)
        if enh is not None and mv is not None:
            em = (mv[z] == enh.label_value) & sl
            ce = mask_centroid(em)
            if ce is not None:
                re_ = max(4.0, CIRCLE_FACTOR * equivalent_radius(em))
                sch = SCHEMATICS["enhancing"]
                out.append(
                    _sign(
                        fid,
                        "enhancing",
                        "circle",
                        [ce],
                        SIGN_TEXT["enhancing"],
                        radius=re_,
                        schematic=sch,
                        plane="axial",
                        slice_=z,
                    )
                )
    return out[:MAX_SIGNS]


# ------------------------------------------------------------------ entry points
def _card_first_sign(label: str) -> str | None:
    try:
        from backend.app.tutor_bridge import load_cards

        c = load_cards().get(label)
        if c and c.key_signs:
            s = c.key_signs[0].split("(")[0].strip().rstrip(",;")
            return s
    except Exception:  # noqa: BLE001
        return None
    return None


def signs_for_finding(case: Case, f: Finding, repo: CaseRepository, anatomy: Anatomy | None = None) -> list[Sign]:
    """Deterministic signs for one finding (≤ MAX_SIGNS). Never raises: a failure gives []."""
    fid = f.short_id
    try:
        if case.volume is not None:
            return _volume_signs(fid, f, case, repo)
        m = repo.mask(case.case_id, f.finding_id)
        if m is None or not m.any():
            return []
        an = anatomy if anatomy is not None else load_anatomy(case, repo)
        w = case.width
        lab = f.label
        if lab == "pneumothorax":
            return _pneumothorax(fid, f, m, an, w)
        if lab == "effusion":
            return _effusion(fid, f, m, an, w)
        if lab == "cardiomegaly":
            return _cardiomegaly(fid, case, m, an)
        if lab in ("consolidation", "atelectasis"):
            return _opacity(fid, f, m, an)
        if lab in ("nodule", "mass", "calcification"):
            return _round(fid, f, m)
        if lab == "fracture":
            return _fracture(fid, m)
        if lab == "pleural_thickening":
            return _pleural_thickening(fid, f, m, an, w)
        if lab in ("emphysema", "fibrosis", "diffuse_nodule"):
            return _pattern(fid, f, m, an, _card_first_sign(lab), w)
        return []
    except Exception:  # noqa: BLE001 — signs are decoration on the reveal; never break scoring
        log.exception("signs for %s failed", f.finding_id)
        return []


def load_anatomy(case: Case, repo: CaseRepository) -> Anatomy:
    masks = None
    if case.volume is None:
        try:
            masks = repo.anatomy(case.case_id)
        except Exception:  # noqa: BLE001
            masks = None
    try:
        zones, _ = repo.zones(case.case_id) if case.volume is None else ({}, {})
    except Exception:  # noqa: BLE001
        zones = {}
    return Anatomy(masks, zones)


def signs_for_case(case: Case, repo: CaseRepository) -> dict[str, list[Sign]]:
    """{finding short id: signs} for every finding of the case (empty lists allowed)."""
    an = load_anatomy(case, repo) if case.volume is None else None
    return {f.short_id: signs_for_finding(case, f, repo, an) for f in case.findings}


def sign_names(signs: Sequence[Sign]) -> list[str]:
    return [s.name for s in signs]


def check_sign(s: Sign) -> list[str]:
    """Shape sanity used by tests and the QA script."""
    errs: list[str] = []
    g = s.geometry
    if _words(s.text) > MAX_WORDS:
        errs.append(f"{s.id}: text has {_words(s.text)} words")
    if g.kind == "circle" and (len(g.points) != 1 or not g.radius):
        errs.append(f"{s.id}: circle needs one centre and a radius")
    if g.kind in ("arrow", "segment") and len(g.points) != 2:
        errs.append(f"{s.id}: {g.kind} needs two points")
    if g.kind in ("polyline", "band") and len(g.points) < 2:
        errs.append(f"{s.id}: {g.kind} needs ≥ 2 points")
    if g.kind == "polygon" and len(g.points) < 3:
        errs.append(f"{s.id}: polygon needs ≥ 3 points")
    if len(g.points) > MAX_POINTS:
        errs.append(f"{s.id}: {len(g.points)} points > {MAX_POINTS}")
    if any(not np.isfinite(x) or not np.isfinite(y) for x, y in g.points):
        errs.append(f"{s.id}: non-finite point")
    return errs


def draw_signs(img: np.ndarray, signs: Sequence[Sign], scale: float = 1.0) -> np.ndarray:
    """QA rendering (BGR): cyan geometry, amber arrows; the name near the first point."""
    out = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    cyan, amber = (221, 201, 53), (46, 169, 240)
    for s in signs:
        g = s.geometry
        pts = np.array([[x * scale, y * scale] for x, y in g.points], dtype=np.int32)
        if g.kind == "circle":
            cv2.circle(out, tuple(int(v) for v in pts[0]), int((g.radius or 1) * scale), cyan, 2)
        elif g.kind == "arrow":
            cv2.arrowedLine(out, tuple(int(v) for v in pts[0]), tuple(int(v) for v in pts[1]), amber, 2, tipLength=0.25)
        elif g.kind == "segment":
            cv2.line(out, tuple(int(v) for v in pts[0]), tuple(int(v) for v in pts[1]), amber, 2)
        elif g.kind == "band":
            cv2.polylines(out, [pts.reshape(-1, 1, 2)], False, cyan, max(2, int(2 * (g.radius or 4) * scale)))
        elif g.kind == "polygon":
            cv2.polylines(out, [pts.reshape(-1, 1, 2)], True, cyan, 2)
        else:
            cv2.polylines(out, [pts.reshape(-1, 1, 2)], False, cyan, 2)
        x, y = int(pts[0][0]), int(pts[0][1])
        cv2.putText(
            out, s.name, (max(2, x - 20), max(12, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, amber, 1, cv2.LINE_AA
        )
    return out


def as_dicts(signs: Sequence[Sign]) -> list[dict[str, Any]]:
    return [s.model_dump(exclude_none=True) for s in signs]


# ------------------------------------------------------------------ schematics (content/signs/<id>.yaml)
def _signature(directory: Path) -> tuple[tuple[str, int], ...]:
    return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(directory.glob("*.yaml")))


@lru_cache(maxsize=4)
def _load_schematics(directory: str, _sig: tuple) -> dict[str, SignSchematic]:
    out: dict[str, SignSchematic] = {}
    for p in sorted(Path(directory).glob("*.yaml")):
        try:
            sch = SignSchematic.model_validate(yaml.safe_load(p.read_text()))
        except Exception as e:  # noqa: BLE001 — one broken file never hides the others
            log.warning("sign schematic %s skipped: %s", p.name, e)
            continue
        if sch.id != p.stem:
            log.warning("sign schematic %s: id %r does not match the file name; skipped", p.name, sch.id)
            continue
        out[sch.id] = sch
    return out


def load_schematics(directory: Path | None = None) -> dict[str, SignSchematic]:
    """Generic sign schematics keyed by id (re-read when a file changes)."""
    d = Path(directory) if directory else config.signs_dir()
    if not d.exists():
        return {}
    return dict(_load_schematics(str(d), _signature(d)))


# The sign a learner should know first for each label; it leads the list (the rest follow in file order).
PRIMARY_SCHEMATIC: dict[str, str] = {
    "pneumothorax": "visceral_pleural_line",
    "effusion": "meniscus_sign",
    "consolidation": "silhouette_sign",
    "atelectasis": "silhouette_sign",
    "cardiomegaly": "cardiothoracic_ratio",
    "nodule": "mass_vs_nodule",
    "mass": "mass_vs_nodule",
    "fracture": "rib_fracture_cortex",
    "pleural_thickening": "pleural_thickening_band",
    "pancreatic_tumour": "ct_hypoenhancing_mass",
    "liver_tumour": "ct_hypoenhancing_mass",
    "brain_tumour": "mr_ring_enhancement",
}


def schematics_for_label(label: str, schematics: dict[str, SignSchematic] | None = None) -> list[str]:
    """Schematic ids whose `labels` include this label: the label's primary sign first, then file order."""
    sch = schematics if schematics is not None else load_schematics()
    ids = [sid for sid, s in sch.items() if label in s.labels]
    primary = PRIMARY_SCHEMATIC.get(label)
    if primary in ids:
        ids.remove(primary)
        ids.insert(0, primary)
    return ids
