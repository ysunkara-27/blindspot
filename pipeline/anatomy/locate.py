"""Finding locations (SPEC §4.4) and the mark→finding spatial relation (used by the backend at scoring time).

Pure functions over boolean masks (H, W) and a zones dict as returned by derive_zones / shared.rle.read_zones.
All text is templated and deterministic. Zones are approximate anatomical regions: never lobes, rib levels,
or centimetres (pixel spacing is unknown for ChestX-Det).

Patient RIGHT is on the image LEFT: a pixel with x < midline_x is on the patient's right.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from pipeline.anatomy.common import adjacency, human, review_areas, zone_ids
from pipeline.anatomy.zones import centroid, dilate, extent

OVERLAP_MIN = 0.15  # zone counts for a finding at >= 15% of the finding's mask
MAX_ZONES = 3
BILATERAL_MIN = 0.25  # both sides >= 25% of the mask → bilateral (or midline)
PRIMARY_TIE = 0.05  # overlaps within 0.05 of the max are a tie, broken by specificity (rank, then area)
TOUCH_FRAC = 0.01  # "touches" a neighbouring review area = within 1% of image width
MIN_SHIFT = 0.05  # relative shifts below 5% of lung height/width are "about the same"
MIDLINE_ZONES = frozenset({"mediastinum", "spine"})
# DECISION (PROGRESS.md): pleural/parenchymal basal processes are intrathoracic. On these films the TXV
# aerated-lung mask stops at the top of a basal opacity and the TXV diaphragm edge rises to meet it, so the
# expert mask spills into the "area just below the diaphragm" band. For these labels that band is never a
# zone/primary and the only diaphragm phrase allowed is "just above the diaphragm". Nodules, masses,
# calcifications and fractures keep it (lung hidden behind the dome is the classic blind spot).
NOT_SUBDIAPHRAGMATIC_LABELS = frozenset(
    {"effusion", "pleural_thickening", "consolidation", "atelectasis", "pneumothorax"}
)

LUNG_THIRDS: dict[str, tuple[str, int]] = {
    f"{s}_{p}_zone": (s, i) for s in ("right", "left") for i, p in enumerate(("upper", "mid", "lower"))
}
_LUNG_BASED_H3 = set(LUNG_THIRDS) | {"right_periphery", "left_periphery"}
_NON_LATERAL = {"mediastinum", "cardiac_silhouette", "subdiaphragmatic", "spine"}


def zone_rank(z: str) -> int:
    """Lower = more specific/teachable; used only to break ties in primary zone and point lookup."""
    if z in review_areas():
        return 0
    if z in LUNG_THIRDS:
        return 1
    if z.endswith("_periphery"):
        return 3
    if z in ("right_lung", "left_lung", "lungs"):
        return 4
    return 2


def _ids(zones: Mapping[str, np.ndarray]) -> list[str]:
    return [z for z in zone_ids() if z in zones]


def _crop_box(mask: np.ndarray, pad: int = 0) -> tuple[slice, slice]:
    e = extent(mask)
    if e is None:
        return slice(0, 0), slice(0, 0)
    h, w = mask.shape
    x0, y0, x1, y1 = e
    return slice(max(0, y0 - pad), min(h, y1 + pad + 1)), slice(max(0, x0 - pad), min(w, x1 + pad + 1))


def zone_overlaps(mask: np.ndarray, zones: Mapping[str, np.ndarray]) -> dict[str, float]:
    """overlap(zone) = |mask ∩ zone| / |mask| for every config zone present."""
    mask = np.asarray(mask, dtype=bool)
    n = int(mask.sum())
    if n == 0:
        return {z: 0.0 for z in _ids(zones)}
    sy, sx = _crop_box(mask)
    m = mask[sy, sx]
    return {z: float(np.count_nonzero(m & zones[z][sy, sx]) / n) for z in _ids(zones)}


def _area(zones: Mapping[str, np.ndarray], z: str, cache: dict[str, int]) -> int:
    if z not in cache:
        cache[z] = int(np.count_nonzero(zones[z]))
    return cache[z]


def nearest_zone(xy: tuple[float, float], zones: Mapping[str, np.ndarray]) -> str | None:
    """Zone nearest to a point (0 if inside); ties → most specific."""
    x, y = xy
    best: tuple[float, int, int, str] | None = None
    areas: dict[str, int] = {}
    for z in _ids(zones):
        ys, xs = np.nonzero(zones[z])
        if xs.size == 0:
            continue
        d = float(np.min((xs - x) ** 2 + (ys - y) ** 2))
        key = (round(d, 3), zone_rank(z), _area(zones, z, areas), z)
        if best is None or key < best:
            best = key
    return best[3] if best else None


def zone_at(x: float, y: float, zones: Mapping[str, np.ndarray], *, nearest: bool = False) -> str | None:
    """Most specific config zone containing image point (x, y) — for learner marks. None if outside all zones
    (or the nearest zone when nearest=True)."""
    first = next(iter(zones.values()))
    h, w = first.shape
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return nearest_zone((x, y), zones) if nearest else None
    inside = [z for z in _ids(zones) if zones[z][yi, xi]]
    if not inside:
        return nearest_zone((x, y), zones) if nearest else None
    areas: dict[str, int] = {}
    return min(inside, key=lambda z: (zone_rank(z), _area(zones, z, areas), z))


def choose_zones(
    overlaps: Mapping[str, float],
    zones: Mapping[str, np.ndarray],
    cxy: tuple[float, float],
    exclude: frozenset[str] = frozenset(),
) -> tuple[list[str], str | None]:
    """zones = overlap >= 0.15, primary first then by overlap desc, max 3.

    Nothing >= 0.15 → the zone it overlaps most (if it touches any), else the nearest zone by centroid.
    """
    areas: dict[str, int] = {}
    ov = {z: o for z, o in overlaps.items() if z not in exclude}
    cand = {z: o for z, o in ov.items() if o >= OVERLAP_MIN}
    if not cand:
        touching = {z: o for z, o in ov.items() if o > 0}
        if touching:
            best = min(touching, key=lambda z: (-touching[z], zone_rank(z), _area(zones, z, areas), z))
            return [best], best
        nz = nearest_zone(cxy, {z: m for z, m in zones.items() if z not in exclude})
        return ([nz], nz) if nz else ([], None)
    mx = max(cand.values())
    tied = [z for z, o in cand.items() if o >= mx - PRIMARY_TIE]
    primary = min(tied, key=lambda z: (zone_rank(z), -cand[z], _area(zones, z, areas), z))
    rest = sorted((z for z in cand if z != primary), key=lambda z: (-cand[z], zone_rank(z), _area(zones, z, areas), z))
    return [primary, *rest[: MAX_ZONES - 1]], primary


def side_fractions(mask: np.ndarray, midline_x: float) -> tuple[float, float]:
    """(fraction of mask on the patient's right = image x < midline, fraction on the left)."""
    xs = np.nonzero(mask)[1]
    if xs.size == 0:
        return 0.0, 0.0
    r = float(np.count_nonzero(xs < midline_x) / xs.size)
    return r, 1.0 - r


def finding_side(mask: np.ndarray, midline_x: float, primary_zone: str | None = None) -> str:
    r, lf = side_fractions(mask, midline_x)
    if r >= BILATERAL_MIN and lf >= BILATERAL_MIN:
        return "midline" if primary_zone in MIDLINE_ZONES else "bilateral"
    return "right" if r > lf else "left"


def _zone_side(z: str) -> str | None:
    if z.startswith("right_"):
        return "right"
    if z.startswith("left_"):
        return "left"
    return None


def _third_word(t: float, words: tuple[str, str, str]) -> str:
    return words[0] if t < 1 / 3 else (words[1] if t < 2 / 3 else words[2])


def horizontal_third(cx: float, lung_ext: tuple[int, int, int, int], side: str) -> str:
    """lateral/central/medial third of that lung's x-extent (lateral = small x for the patient-right lung)."""
    x0, _, x1, _ = lung_ext
    t = (cx - x0) / max(1.0, x1 - x0 + 1)
    t = min(max(t, 0.0), 0.999)
    return _third_word(t, ("lateral", "central", "medial") if side == "right" else ("medial", "central", "lateral"))


def vertical_part(cy: float, zone_mask: np.ndarray) -> str | None:
    e = extent(zone_mask)
    if e is None:
        return None
    _, y0, _, y1 = e
    t = min(max((cy - y0) / max(1.0, y1 - y0 + 1), 0.0), 0.999)
    return _third_word(t, ("upper", "middle", "lower"))


def _neighbour_phrase(
    mask: np.ndarray,
    cxy: tuple[float, float],
    primary: str,
    overlaps: Mapping[str, float],
    zones: Mapping[str, np.ndarray],
    midline_x: float,
    label: str | None = None,
) -> tuple[str | None, str | None]:
    """('just above the right costophrenic angle', 'vertical'|'horizontal'|'into') for the adjacent review
    area the mask touches most, or (None, None)."""
    intrathoracic = label in NOT_SUBDIAPHRAGMATIC_LABELS
    adj = adjacency().get(primary, frozenset())
    cands = [a for a in review_areas() if a != primary and a in adj and a in zones]
    if not cands:
        return None, None
    w = mask.shape[1]
    r = TOUCH_FRAC * w
    sy, sx = _crop_box(mask, pad=int(np.ceil(r)) + 1)
    touch = dilate(mask[sy, sx], r)
    best: tuple[int, str, np.ndarray] | None = None
    for a in cands:
        contact = touch & zones[a][sy, sx]
        n = int(np.count_nonzero(contact))
        if n and (best is None or n > best[0]):
            best = (n, a, contact)
    if best is None:
        return None, None
    _, a, contact = best
    h = human(a)
    if a == "subdiaphragmatic" and intrathoracic:
        return "just above the diaphragm", "vertical"
    if overlaps.get(a, 0.0) >= OVERLAP_MIN:
        return ("extending below the diaphragm" if a == "subdiaphragmatic" else f"extending into the {h}"), "into"
    if a == "subdiaphragmatic":
        return "just above the diaphragm", "vertical"
    ys, xs = np.nonzero(contact)
    ccx, ccy = float(xs.mean()) + sx.start, float(ys.mean()) + sy.start
    dx, dy = ccx - cxy[0], ccy - cxy[1]
    if abs(dy) >= abs(dx):
        return (f"just above the {h}" if dy > 0 else f"just below the {h}"), "vertical"
    on_right = cxy[0] < midline_x
    contact_more_lateral = (dx < 0) if on_right else (dx > 0)
    return (f"just medial to the {h}" if contact_more_lateral else f"just lateral to the {h}"), "horizontal"


def relative_location(
    mask: np.ndarray,
    primary: str | None,
    side: str,
    zones: Mapping[str, np.ndarray],
    midline_x: float,
    overlaps: Mapping[str, float] | None = None,
    label: str | None = None,
) -> str | None:
    """Deterministic, e.g. 'right lower zone, lateral third, just above the right costophrenic angle'."""
    if primary is None:
        return None
    c = centroid(mask)
    if c is None:
        return None
    overlaps = overlaps if overlaps is not None else zone_overlaps(mask, zones)
    parts = [human(primary)]
    zs = _zone_side(primary)
    if primary in _LUNG_BASED_H3 and zs:
        le = extent(zones[f"{zs}_lung"])
        if le is not None:
            parts.append(f"{horizontal_third(c[0], le, zs)} third")
    phrase, kind = _neighbour_phrase(mask, c, primary, overlaps, zones, midline_x, label)
    if primary in _LUNG_BASED_H3 and kind != "vertical":
        vp = vertical_part(c[1], zones[primary])
        if vp:
            parts.append(f"{vp} part")
    if primary in _NON_LATERAL and side in ("right", "left"):
        parts.append(f"{side} side")
    if phrase:
        parts.append(phrase)
    return ", ".join(parts)


def locate_finding(
    mask: np.ndarray, zones: Mapping[str, np.ndarray], midline_x: float, label: str | None = None
) -> dict[str, Any]:
    """side, zones, primary_zone, relative_location for one finding mask (Finding field names).

    label (canonical id) only matters for NOT_SUBDIAPHRAGMATIC_LABELS."""
    mask = np.asarray(mask, dtype=bool)
    c = centroid(mask)
    if c is None:
        return {"side": None, "zones": [], "primary_zone": None, "relative_location": None}
    ov = zone_overlaps(mask, zones)
    excl = frozenset({"subdiaphragmatic"}) if label in NOT_SUBDIAPHRAGMATIC_LABELS else frozenset()
    zlist, primary = choose_zones(ov, zones, c, excl)
    side = finding_side(mask, midline_x, primary)
    return {
        "side": side,
        "zones": zlist,
        "primary_zone": primary,
        "relative_location": relative_location(mask, primary, side, zones, midline_x, ov, label),
    }


# --------------------------------------------------------------------------- mark → finding relation
def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)


def _lung_box(zones: Mapping[str, np.ndarray], side: str) -> tuple[int, int, int, int] | None:
    key = {"right": "right_lung", "left": "left_lung"}.get(side, "lungs")
    return extent(zones[key]) if key in zones else None


def _where(zone: str | None) -> str:
    return f"the {human(zone)}" if zone else "an area outside the lung fields"


def _steps_text(steps: int) -> str:
    if steps == 0:
        return "at the same zone level"
    n = {1: "one zone", 2: "two zones"}.get(abs(steps), f"{abs(steps)} zones")
    return f"{n} {'lower' if steps > 0 else 'higher'}"


def spatial_relation(
    mark_xy: tuple[float, float],
    finding: Any,
    zones: Mapping[str, np.ndarray],
    midline_x: float,
    *,
    finding_name: str | None = None,
) -> dict[str, Any]:
    """Where a learner's mark sits relative to a focal finding, in patient-side anatomical terms.

    finding: shared.contracts.Finding or a dict with centroid, side, primary_zone, label.
    Returns {text, same_side, mark_side, mark_zone, finding_zone, zone_steps, dy_lung_heights,
    dlat_lung_widths, direction}. dy > 0 = finding lower than the mark; dlat > 0 = finding more lateral.
    Shifts are in units of that lung's height/width (never centimetres).
    """
    mx, my = float(mark_xy[0]), float(mark_xy[1])
    fx, fy = (float(v) for v in _get(finding, "centroid"))
    name = finding_name or str(_get(finding, "label") or "finding").replace("_", " ")
    f_side = _get(finding, "side") or ("right" if fx < midline_x else "left")
    m_side = "right" if mx < midline_x else "left"
    f_zone = _get(finding, "primary_zone") or zone_at(fx, fy, zones, nearest=True)
    m_zone = zone_at(mx, my, zones)
    h_img, w_img = next(iter(zones.values())).shape
    xi, yi = int(round(mx)), int(round(my))
    inside = 0 <= xi < w_img and 0 <= yi < h_img
    m_in_lung = {s: bool(inside and f"{s}_lung" in zones and zones[f"{s}_lung"][yi, xi]) for s in ("right", "left")}
    out: dict[str, Any] = {
        "same_side": None,
        "mark_side": m_side,
        "mark_zone": m_zone,
        "finding_zone": f_zone,
        "zone_steps": None,
        "dy_lung_heights": None,
        "dlat_lung_widths": None,
        "direction": None,
    }
    if f_side in ("right", "left") and m_side != f_side:
        out["same_side"] = False
        other = "in the other lung" if m_in_lung[m_side] else "on the other side"
        out["text"] = f"The {name} is {other}: your mark was in {_where(m_zone)}; the {name} is in {_where(f_zone)}."
        return out
    box = _lung_box(zones, f_side)
    if box is None:
        out["text"] = f"Your mark was in {_where(m_zone)}; the {name} is in {_where(f_zone)}."
        return out
    x0, y0, x1, y1 = box
    lh, lw = float(y1 - y0 + 1), float(x1 - x0 + 1)
    if f_side not in ("right", "left"):  # bilateral/midline: half the union box ≈ one lung's width
        lw /= 2.0
    dy = (fy - my) / lh
    if f_side == "right":
        dlat = (mx - fx) / lw
    elif f_side == "left":
        dlat = (fx - mx) / lw
    else:
        dlat = (abs(fx - midline_x) - abs(mx - midline_x)) / lw

    def third(y: float) -> int:
        return int(min(2, max(0, np.floor(3 * (y - y0) / lh))))

    steps = third(fy) - third(my)
    words = []
    if abs(dy) >= MIN_SHIFT:
        words.append("lower" if dy > 0 else "higher")
    if abs(dlat) >= MIN_SHIFT:
        words.append("more lateral" if dlat > 0 else "more medial")
    direction = " and ".join(words) if words else "very close to your mark"
    out.update(
        same_side=True if f_side in ("right", "left") else None,
        zone_steps=int(steps),
        dy_lung_heights=round(float(dy), 2),
        dlat_lung_widths=round(float(dlat), 2),
        direction=direction,
    )
    detail = []
    if abs(dy) >= MIN_SHIFT:
        detail.append(f"about {abs(dy):.1f} lung-heights {'lower' if dy > 0 else 'higher'}")
    if abs(dlat) >= MIN_SHIFT:
        detail.append(f"{abs(dlat):.1f} lung-widths {'more lateral' if dlat > 0 else 'more medial'}")
    det = f" ({' and '.join(detail)})" if detail else ", very close to your mark"
    if out["same_side"]:
        lead = "Same lung: your mark" if m_in_lung[f_side] else "Same side: your mark"
    else:
        lead = "Your mark"
    out["text"] = f"{lead} was in {_where(m_zone)}; the {name} is {_steps_text(steps)}, in {_where(f_zone)}{det}."
    return out
