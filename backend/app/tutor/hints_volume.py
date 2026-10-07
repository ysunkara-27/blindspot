"""Deterministic hint ladder for volumetric (CT / MR) cases. No LLM. Same symmetric no-leak rule as hints.py:
each level has ONE template, so the text alone cannot tell a learner whether the volume has a labelled finding.

H1: "You haven't looked at the upper third of the slices or the pancreas yet."  /  H1_ALL_VISITED
    At most 3 unvisited review areas (config `volumetric.review_areas[body_region]`): slab thirds from the slices the
    learner has scrolled through, organ zones from 3D zone masks when the caller has them. A search cue only.
H2: "Look again at the patient's {side} side, in the {organ/slab}."  /  "Look again at the {organ/slab}."
H3: "In the {zone}, check for this sign: {sign}. {Mimic} can look similar; scroll through every slice there and
    compare it with the other side."

Where the zone, side and sign come from:
- a labelled finding not yet marked (3D hit test: in-plane tolerance + ±slice_window slices): the hardest one's
  primary zone and side; sign = first key sign on its card (CT / MR language).
- otherwise (lesion-free slab, or every finding marked): the least-dwelt zone among the zones the modality's cards
  hide in (ties by a per-case hash), a side picked by the same hash from the same set of texts abnormal cases produce,
  and the first key sign of a card that hides there. A dwell-chosen zone is kept at H3 equal to the zone H2 named
  when `previous` holds the earlier hint texts.
- mimic: the first config `volumetric.zone_mimics` entry for that zone (normal structures only); the anatomy explainer's
  first mimic when the zone has none.

Dwell: per slice, each telemetry interval (capped at dwell.max_still_ms) is credited to the slice on screen; a slab
third's dwell is the sum over its slices; an organ zone's dwell counts intervals whose pointer voxel is inside its 3D
mask. The caller may pass precomputed `zone_dwell` instead.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from backend.app.tutor import vocab
from backend.app.tutor.cards import (
    AnatomyCard,
    anatomy_for_zone,
    cards_for_modality,
    load_anatomy,
    load_cards,
    load_volumetric_zone_mimics,
)
from shared.contracts import Case, Finding, Mark, TeachingCard, TelemetryEvent

H1_ALL_VISITED = "Compare each slice with the same level on the other side, then scroll on."
H1_PREFIX = "You haven't looked at "
H1_SUFFIX = " yet."
H1_MAX_AREAS = 3
H1_NAMES = {
    "superior_slab": "upper third of the slices",
    "mid_slab": "middle third of the slices",
    "inferior_slab": "lower third of the slices",
}
H2_PREFIX = "Look again at the "
H3_PREFIX = "In the "
GENERIC_SIGN = "an area whose attenuation or enhancement differs from the organ around it"
GENERIC_MIMIC = "Vessels seen end-on"
# Hint text never contains these words (backend QA: a hint must read the same on a lesion-free volume).
_LEAK_WORDS = re.compile(r"\bnormal\b|\btumou?rs?\b|\bnormally\b", re.I)
COMPARE = "scroll through every slice there and compare it with the other side"
SLABS = ("superior_slab", "mid_slab", "inferior_slab")
_SIDES = ("right", "left", None)


def _get(e: Any, k: str) -> Any:
    return e.get(k) if isinstance(e, Mapping) else getattr(e, k, None)


def _rank(case_id: str, key: str) -> str:
    return hashlib.sha256(f"{case_id}|{key}".encode()).hexdigest()


# --------------------------------------------------------------------------- dwell
def slab_of(z: int, nz: int) -> str:
    """Slab third of slice index z in a volume of nz slices (superior = lowest indices, as the contract orders z)."""
    if nz <= 0:
        return "mid_slab"
    third = max(1, -(-nz // 3))
    return SLABS[min(2, int(z) // third)]


def slice_dwell(telemetry: Sequence[Any], cfg: Mapping[str, Any] | None = None) -> dict[int, float]:
    """ms per slice index from telemetry (events carry `slice`; the current slice is the last one seen)."""
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    cap = float((sc.get("dwell") or {}).get("max_still_ms", 1500))
    out: dict[int, float] = {}
    cur: int | None = None
    for e0, e1 in zip(telemetry, telemetry[1:], strict=False):
        s0 = _get(e0, "slice")
        if s0 is not None:
            cur = int(s0)
        if cur is None:
            continue
        dt = min(max(0.0, float(_get(e1, "t")) - float(_get(e0, "t"))), cap)
        out[cur] = out.get(cur, 0.0) + dt
    last = _get(telemetry[-1], "slice") if telemetry else None
    if last is not None:
        out.setdefault(int(last), 0.0)
    return out


def _voxel(e: Any) -> tuple[int, int, int] | None:
    x, y, z = _get(e, "x"), _get(e, "y"), _get(e, "slice")
    if x is None or y is None or z is None:
        return None
    return int(x), int(y), int(z)


def zone_dwell(
    case: Case,
    telemetry: Sequence[Any],
    zones: Mapping[str, np.ndarray] | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """ms per volumetric zone: slab thirds from slice dwell; organ zones from 3D masks (z, y, x) when given."""
    nz = int(case.volume.shape[0]) if case.volume is not None else 0
    out: dict[str, float] = {z: 0.0 for z in SLABS}
    for z, ms in slice_dwell(telemetry, cfg).items():
        out[slab_of(z, nz)] += ms
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    cap = float((sc.get("dwell") or {}).get("max_still_ms", 1500))
    masks = {k: v for k, v in (zones or {}).items() if getattr(v, "ndim", 0) == 3}
    for k in masks:
        out.setdefault(k, 0.0)
    if masks:
        cur: int | None = None
        for e0, e1 in zip(telemetry, telemetry[1:], strict=False):
            s0 = _get(e0, "slice")
            if s0 is not None:
                cur = int(s0)
            x, y = _get(e0, "x"), _get(e0, "y")
            if cur is None or x is None or y is None:
                continue
            dt = min(max(0.0, float(_get(e1, "t")) - float(_get(e0, "t"))), cap)
            for k, m in masks.items():
                d, h, w = m.shape
                xi, yi = int(x), int(y)
                if 0 <= cur < d and 0 <= yi < h and 0 <= xi < w and bool(m[cur, yi, xi]):
                    out[k] += dt
    return out


def review_areas(case: Case, zones: Mapping[str, np.ndarray] | None = None) -> list[str]:
    """Coverage targets for this case: the slab thirds plus organ zones we can actually measure (3D mask given)."""
    cands = vocab.volumetric_review_area_ids(case.body_region)
    organs = {k for k, v in (zones or {}).items() if getattr(v, "ndim", 0) == 3}
    return [z for z in cands if z in SLABS or z in organs]


def unvisited(case: Case, dwell: Mapping[str, float], areas: Sequence[str], cfg: Mapping[str, Any] | None) -> list[str]:
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    visit_ms = float(((sc.get("volumetric") or {}).get("dwell") or {}).get("visit_ms", 300))
    return [z for z in areas if float(dwell.get(z, 0.0)) < visit_ms]


# --------------------------------------------------------------------------- texts
def _join(names: list[str], last: str = "and") -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" {last} " + names[-1]


def h1_areas(unvisited_areas: Sequence[str], dwell: Mapping[str, float], order: Sequence[str]) -> list[str]:
    rank = {z: i for i, z in enumerate(order)}
    known = [z for z in dict.fromkeys(unvisited_areas) if z in rank]
    pick = sorted(known, key=lambda z: (float(dwell.get(z, 0.0)), rank[z]))[:H1_MAX_AREAS]
    return sorted(pick, key=rank.__getitem__)


def h1_text(areas: Sequence[str]) -> str:
    if not areas:
        return H1_ALL_VISITED
    names = ["the " + H1_NAMES.get(z, vocab.zone_human(z)) for z in areas]
    return H1_PREFIX + _join(names, "or") + H1_SUFFIX


def _zone_name(zone: str) -> str:
    return H1_NAMES.get(zone, vocab.zone_human(zone))


def h2_text(zone: str, side: str | None) -> str:
    side = side or vocab.side_of_zone(zone)
    where = _zone_name(zone)
    if side in ("right", "left") and not vocab.side_of_zone(zone):
        return f"{H2_PREFIX}patient's {side} side, in the {where}."
    return f"{H2_PREFIX}{where}."


def _clause(s: str) -> str:
    s = s.strip().rstrip(".")
    return s[:1].lower() + s[1:] if s and not (len(s) > 1 and s[1].isupper()) else s  # keep "T1c", "CT"


def _cap(s: str) -> str:
    s = s.strip().rstrip(".")
    return s[:1].upper() + s[1:]


def h3_text(zone: str, sign: str, mimic: str) -> str:
    where = _zone_name(zone)
    return f"{H3_PREFIX}{where}, check for this sign: {_clause(sign)}. {_cap(mimic)} can look similar; {COMPARE}."


def _previous_h2(previous: Sequence[Any] | None, zones: Sequence[str]) -> tuple[str, str | None] | None:
    if not previous:
        return None
    text = None
    for i, p in enumerate(previous):
        lvl, txt = (p.get("level"), p.get("text")) if isinstance(p, Mapping) else (i + 1, p)
        if lvl == 2 and isinstance(txt, str):
            text = txt.strip()
    if not text:
        return None
    for z in zones:
        for side in _SIDES:
            if h2_text(z, side) == text:
                return z, side
    return None


# --------------------------------------------------------------------------- targets
def marked(f: Finding, marks: Sequence[Mark], tau: float, slice_window: int) -> bool:
    """3D hit test: inside the bbox ± tau in-plane and within ±slice_window of the slice range (marks without a
    slice count as in-plane hits)."""
    x0, y0, x1, y1 = f.geometry.bbox
    for m in marks:
        if not (x0 - tau <= m.x <= x1 + tau and y0 - tau <= m.y <= y1 + tau):
            continue
        if m.slice is None or not f.slice_range:
            return True
        z0, z1 = int(f.slice_range[0]), int(f.slice_range[-1])
        if z0 - slice_window <= int(m.slice) <= z1 + slice_window:
            return True
    return False


def hardest_unmarked(case: Case, marks: Sequence[Mark], cfg: Mapping[str, Any] | None = None) -> Finding | None:
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    vhit = (sc.get("volumetric") or {}).get("hit") or {}
    tau = float(vhit.get("tolerance_frac", 0.02)) * case.width
    win = int(vhit.get("slice_window", 2))
    cand = [f for f in case.findings if f.kind == "focal" and not marked(f, marks, tau, win)]
    if not cand:
        return None
    return max(
        cand,
        key=lambda f: (
            f.difficulty if f.difficulty is not None else case.difficulty_prior,
            vocab.zone_hardness(f.primary_zone),
            -f.area_frac,
            f.finding_id,
        ),
    )


_SIDE_ONLY = ("right_half", "left_half", "midline_volume")  # a side is not a place to look; H2 adds the side itself


def hint_zones(cards: Mapping[str, TeachingCard]) -> list[str]:
    """Volumetric zones some card of this modality says findings hide in (config zone order), slab thirds always
    included and the side-only zones excluded, so every H2 has the same shape on every case."""
    hide = {z for c in cards.values() for z in c.where_it_hides} | set(SLABS)
    return [z for z in vocab.volumetric_zone_ids() if z in hide and z not in _SIDE_ONLY]


def _tidy(item: str) -> str:
    """Config flow lists split "x (a, b)" at the inner comma: drop an unbalanced parenthesis tail or fragment."""
    item = item.strip()
    if "(" in item and ")" not in item:
        item = item.split("(", 1)[0].strip()
    if ")" in item and "(" not in item:
        item = ""
    return item


def _clean_pick(items: Sequence[str], default: str) -> str:
    """First item without a leaking word ("normal", "tumour"); else the default."""
    tidy = [t for t in (_tidy(x) for x in items) if t]
    return next((x for x in tidy if not _LEAK_WORDS.search(x)), default)


def _mimic(zone: str, anatomy: Mapping[str, AnatomyCard]) -> str:
    mims = list(load_volumetric_zone_mimics()["entries"].get(zone) or [])
    a = anatomy_for_zone(zone, dict(anatomy))
    if a and a.mimics:
        mims += list(a.mimics)
    return _clean_pick(mims, GENERIC_MIMIC)


def _focus(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    dwell: Mapping[str, float],
    sc: Mapping[str, Any],
    cards: Mapping[str, TeachingCard],
    previous: Sequence[Any] | None,
    target_info: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None, TeachingCard | None]:
    """(zone, side, card) for H2 / H3. `target_info` = the backend's hardest_unmarked dict (finding_id, label, side,
    zone, zones) when it computed the 3D hit test itself; else the local test runs."""
    abnormal = not case.is_normal and bool(case.findings)
    mcards = cards_for_modality(case.modality, dict(cards)) or dict(cards)
    same_region = {k: v for k, v in mcards.items() if vocab.labels().get(k, {}).get("body_region") == case.body_region}
    mcards = same_region or mcards
    cands = hint_zones(mcards) or list(SLABS)
    if target_info:
        zs = [target_info.get("zone"), *(target_info.get("zones") or [])]
        zone = next((z for z in zs if z and z not in _SIDE_ONLY), cands[0])
        side = target_info.get("side") if target_info.get("side") in ("right", "left") else None
        return zone, side, cards.get(str(target_info.get("label") or ""))
    target = hardest_unmarked(case, marks, sc) if abnormal and target_info is None else None
    if target is not None:
        zone = next((z for z in [target.primary_zone, *target.zones] if z and z not in _SIDE_ONLY), cands[0])
        side = target.side if target.side in ("right", "left") else None
        return zone, side, cards.get(target.label)
    prev = _previous_h2(previous, cands) if level >= 3 else None
    if prev is not None:
        zone, side = prev
    else:
        zone = min(cands, key=lambda z: (float(dwell.get(z, 0.0)), _rank(case.case_id, z)))
        side = _SIDES[int(_rank(case.case_id, "side")[:8], 16) % len(_SIDES)]
    hiding = sorted(
        (c for c in mcards.values() if zone in c.where_it_hides), key=lambda c: _rank(case.case_id, zone + c.label)
    )
    return zone, side, (hiding[0] if hiding else None)


def hint(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    telemetry: Sequence[TelemetryEvent],
    zones: Mapping[str, np.ndarray] | None = None,
    cfg: Mapping[str, Any] | None = None,
    cards: dict[str, TeachingCard] | None = None,
    *,
    previous: Sequence[Any] | None = None,
    zone_dwell_ms: Mapping[str, float] | None = None,
) -> str:
    """Hint text for ladder step `level` (1..3) on a CT / MR case. `zones`: optional 3D masks (z, y, x) per
    volumetric zone id (organ zones); `zone_dwell_ms`: precomputed dwell per zone (overrides telemetry)."""
    level = min(3, max(1, int(level)))
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    dwell = dict(zone_dwell_ms) if zone_dwell_ms is not None else zone_dwell(case, telemetry, zones, sc)
    if level == 1:
        areas = review_areas(case, zones)
        if zone_dwell_ms is not None:  # organ zones the backend measured dwell for
            areas += [z for z in vocab.volumetric_review_area_ids(case.body_region) if z in dwell and z not in areas]
        un = unvisited(case, dwell, areas, sc)
        return h1_text(h1_areas(un, dwell, areas))
    cards = cards if cards is not None else load_cards()
    zone, side, card = _focus(level, case, marks, dwell, sc, cards, previous)
    if zone is None:
        return H1_ALL_VISITED
    if level == 2:
        return h2_text(zone, side)
    sign = _clean_pick(card.key_signs if card else [], GENERIC_SIGN)
    return h3_text(zone, sign, _mimic(zone, load_anatomy()))


def hint_from_data(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    telemetry: Sequence[TelemetryEvent],
    data: Mapping[str, Any] | None,
    *,
    previous: Sequence[Any] | None = None,
    cfg: Mapping[str, Any] | None = None,
    cards: dict[str, TeachingCard] | None = None,
) -> str:
    """Same ladder, fed by the backend's hint_data dict: `unvisited_review_areas`, `dwell_by_zone`, `review_areas`
    (H1, search state only) and `hardest_unmarked` ({finding_id, label, side, zone, zones} or None; H2 / H3)."""
    if not data:
        return hint(level, case, marks, telemetry, None, cfg, cards, previous=previous)
    level = min(3, max(1, int(level)))
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    dwell = {str(k): float(v) for k, v in (data.get("dwell_by_zone") or {}).items()}
    if level == 1:
        areas = list(data.get("review_areas") or vocab.volumetric_review_area_ids(case.body_region))
        un = [z for z in (data.get("unvisited_review_areas") or []) if z in areas] or [
            z for z in areas if z not in dwell
        ]
        return h1_text(h1_areas(un, dwell, areas))
    cards = cards if cards is not None else load_cards()
    info = data.get("hardest_unmarked")
    zone, side, card = _focus(level, case, marks, dwell, sc, cards, previous, target_info=info or {})
    if zone is None:
        return H1_ALL_VISITED
    if level == 2:
        return h2_text(zone, side)
    sign = _clean_pick(card.key_signs if card else [], GENERIC_SIGN)
    return h3_text(zone, sign, _mimic(zone, load_anatomy()))
