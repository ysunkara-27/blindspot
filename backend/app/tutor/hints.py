"""Deterministic hint ladder (SPEC §8.8). No LLM. Hints are disabled in Assessment mode by the backend.

Wording is symmetric for normal and abnormal films (QA gate W1 issue 8): each level has ONE template, so the text
alone cannot tell a learner whether the film is normal.

H1: "You haven't looked at the {a}, the {b} or the {c} yet."  /  "Compare each region with the same region on the other
    side."  At most H1_MAX_AREAS (3) areas: the unvisited review areas with the LEAST dwell so far, named in the fixed
    anatomical order of config review_areas (apices, hila, behind the heart, costophrenic angles, below the diaphragm,
    mediastinum). A search cue only: it depends on the learner's telemetry, never on the findings.
H2: "Look again at the patient's {side} side, in the {zone}."  /  "Look again at the {zone}."  (midline zones)
H3: "In the {zone}, check for this sign: {sign}. {Mimic} can look similar; {compare}."

Where the zone and sign come from:
- abnormal film, an unmarked focal finding: the hardest one's primary zone; sign = first key sign on its card.
- abnormal film, no unmarked focal finding but a pattern finding: its primary zone (else the least-dwelt zone where its
  card says it hides); sign = first key sign on its card.
- otherwise (normal film, or every focal finding already marked and no pattern): the hint zone with the LEAST dwell so
  far, a search cue rather than a truth cue (ties broken by a per-case hash); sign = first key sign of a card that
  hides in that zone (per-case hash pick). Hint zones = every zone some card says findings hide in, i.e. the same kind
  of zones an abnormal-film hint names (lung thirds included, not only the nine review areas).
- mimic: the first config zone_mimics entry for that zone (normal structures only) on every film.
A dwell-chosen zone is kept at H3 equal to the zone H2 named when the caller passes `previous` (the earlier hint texts),
so H2 -> H3 never jumps to a new area on normal films only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from backend.app.tutor import vocab
from backend.app.tutor.cards import load_cards, load_zone_mimics
from shared.contracts import Case, Finding, Mark, TeachingCard, TelemetryEvent

H1_ALL_VISITED = "Compare each region with the same region on the other side."
H1_PREFIX = "You haven't looked at "
H1_SUFFIX = " yet."
H1_MAX_AREAS = 3
# Spoken names for H1 where the config name is a mouthful ("retrocardiac region (behind the heart)").
H1_NAMES = {"retrocardiac": "area behind the heart"}
H2_PREFIX = "Look again at the "
H3_PREFIX = "In the "
GENERIC_SIGN = "an edge or shadow that normal anatomy does not explain"
GENERIC_MIMIC = "Normal overlapping structures"
COMPARE_SIDES = "compare with the same area on the other side"
COMPARE_MIDLINE = "trace the edges there with the loupe"
_LUNG_UNIONS = ("right_lung", "left_lung", "lungs")


def _get(e: Any, k: str) -> Any:
    return e.get(k) if isinstance(e, Mapping) else getattr(e, k, None)


def _inside(region: np.ndarray, x: float, y: float) -> bool:
    h, w = region.shape
    xi, yi = int(x), int(y)
    return 0 <= xi < w and 0 <= yi < h and bool(region[yi, xi])


def dwell_ms(events: Sequence[Any], region: np.ndarray, cfg: Mapping[str, Any]) -> float:
    """SPEC §7.1 attention-proxy dwell inside `region` (local copy used only if the backend engine is absent)."""
    total, still = 0.0, 0.0
    max_dt = float(cfg.get("max_dt_ms", 250))
    max_still = float(cfg.get("max_still_ms", 1500))
    zmin = float(cfg.get("zoom_dwell_min", 2.0))
    zw = float(cfg.get("zoom_dwell_weight", 0.5))
    for e0, e1 in zip(events, events[1:], strict=False):
        dt = min(float(_get(e1, "t")) - float(_get(e0, "t")), max_dt)
        x0, y0 = _get(e0, "x"), _get(e0, "y")
        if x0 is None or y0 is None:
            continue
        x1, y1 = _get(e1, "x"), _get(e1, "y")
        moved = x1 is None or y1 is None or (abs(x1 - x0) + abs(y1 - y0)) > 1.0
        still = 0.0 if moved else still + dt
        if still > max_still:
            continue
        if _inside(region, x0, y0):
            total += dt
        vp = _get(e0, "vp")
        if float(_get(e0, "zoom") or 1.0) >= zmin and vp is not None:
            if _inside(region, (vp[0] + vp[2]) / 2.0, (vp[1] + vp[3]) / 2.0):
                total += zw * dt
    return total


def _coverage(telemetry: Sequence[TelemetryEvent], zones: Mapping[str, np.ndarray], dcfg: Mapping[str, Any]) -> Any:
    from backend.app.search.coverage import review_coverage
    from backend.app.search.dwell import dwell_samples

    visit_ms = float(dcfg.get("visit_ms", 300))
    return review_coverage(dwell_samples(list(telemetry), dict(dcfg)), zones, vocab.review_area_ids(), visit_ms)


def unvisited_review_areas(
    telemetry: Sequence[TelemetryEvent], zones: Mapping[str, np.ndarray], scoring_cfg: Mapping[str, Any] | None = None
) -> list[str]:
    sc = scoring_cfg if scoring_cfg is not None else vocab.scoring_cfg()
    dcfg = dict(sc.get("dwell", {}))
    visit_ms = float(dcfg.get("visit_ms", 300))
    areas = vocab.review_area_ids()
    try:  # prefer the backend's coverage engine so hints and the reveal agree
        cov = _coverage(telemetry, zones, dcfg)
        return [a for a in cov.unvisited if a in zones]
    except Exception:  # noqa: BLE001 — engine missing or changed: fall back to the local SPEC §7.1 dwell
        return [a for a in areas if a in zones and dwell_ms(list(telemetry), zones[a], dcfg) < visit_ms]


def zone_dwell(
    telemetry: Sequence[TelemetryEvent], zones: Mapping[str, np.ndarray], scoring_cfg: Mapping[str, Any] | None = None
) -> dict[str, float]:
    """Dwell (ms, SPEC §7.1) per zone id, lung unions excluded."""
    sc = scoring_cfg if scoring_cfg is not None else vocab.scoring_cfg()
    dcfg = dict(sc.get("dwell", {}))
    try:
        return {z: float(v) for z, v in _coverage(telemetry, zones, dcfg).dwell_by_zone.items()}
    except Exception:  # noqa: BLE001
        return {z: dwell_ms(list(telemetry), m, dcfg) for z, m in zones.items() if z not in _LUNG_UNIONS}


def _join(names: list[str], last: str = "and") -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" {last} " + names[-1]


def h1_areas(unvisited: Sequence[str], dwell: Mapping[str, float], limit: int = H1_MAX_AREAS) -> list[str]:
    """At most `limit` unvisited review areas: those with the least dwell (ties: anatomical order), then listed in
    the fixed anatomical order (the order of config review_areas)."""
    order = {z: i for i, z in enumerate(vocab.review_area_ids())}
    known = [z for z in dict.fromkeys(unvisited) if z in order]
    pick = sorted(known, key=lambda z: (float(dwell.get(z, 0.0)), order[z]))[: max(1, int(limit))]
    return sorted(pick, key=order.__getitem__)


def h1_text(areas: Sequence[str]) -> str:
    """ "You haven't looked at the right apex, the left hilum or the area behind the heart yet." """
    if not areas:
        return H1_ALL_VISITED
    names = ["the " + H1_NAMES.get(z, vocab.zone_human(z)) for z in areas]
    return H1_PREFIX + _join(names, "or") + H1_SUFFIX


def _marked(f: Finding, marks: Sequence[Mark], tau: float) -> bool:
    x0, y0, x1, y1 = f.geometry.bbox
    return any(x0 - tau <= m.x <= x1 + tau and y0 - tau <= m.y <= y1 + tau for m in marks)


def hardest_unmarked(case: Case, marks: Sequence[Mark], scoring_cfg: Mapping[str, Any] | None = None) -> Finding | None:
    sc = scoring_cfg if scoring_cfg is not None else vocab.scoring_cfg()
    tau = float(sc.get("hit", {}).get("tolerance_frac", 0.02)) * case.width
    cand = [f for f in case.findings if f.kind == "focal" and not _marked(f, marks, tau)]
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


# --------------------------------------------------------------------------- symmetric wording
def hint_zones(cards: Mapping[str, TeachingCard]) -> list[str]:
    """Zones where some card says findings hide (config zone order)."""
    hide = {z for c in cards.values() for z in c.where_it_hides}
    return [z for z in vocab.zone_ids() if z in hide]


def _rank(case_id: str, key: str) -> str:
    return hashlib.sha256(f"{case_id}|{key}".encode()).hexdigest()


def _available(cands: Iterable[str], zones: Mapping[str, np.ndarray]) -> list[str]:
    cands = list(dict.fromkeys(cands))
    return [z for z in cands if z in zones] or cands


def least_dwelt(cands: Sequence[str], dwell: Mapping[str, float], case_id: str) -> str | None:
    """Zone with the least dwell so far; ties (e.g. never visited) broken by a per-case hash, not by truth."""
    if not cands:
        return None
    return min(cands, key=lambda z: (float(dwell.get(z, 0.0)), _rank(case_id, z)))


def h2_text(zone: str) -> str:
    side = vocab.side_of_zone(zone)
    where = vocab.zone_human(zone)
    if side:
        return f"{H2_PREFIX}patient's {side} side, in the {where}."
    return f"{H2_PREFIX}{where}."


def _clause(s: str) -> str:
    s = s.strip().rstrip(".")
    return s[:1].lower() + s[1:] if s and not (len(s) > 1 and s[1].isupper()) else s  # keep "AP", "PA"


def _cap(s: str) -> str:
    s = s.strip().rstrip(".")
    return s[:1].upper() + s[1:]


def h3_text(zone: str, sign: str, mimic: str) -> str:
    tail = COMPARE_SIDES if vocab.side_of_zone(zone) else COMPARE_MIDLINE
    where = vocab.zone_human(zone)
    return f"{H3_PREFIX}{where}, check for this sign: {_clause(sign)}. {_cap(mimic)} can look similar; {tail}."


def _previous_h2_zone(previous: Sequence[Any] | None) -> str | None:
    """Zone named by the earlier H2 (previous = hint texts in ladder order, or hint-log dicts {level, text})."""
    if not previous:
        return None
    text = None
    for i, p in enumerate(previous):
        lvl, txt = (p.get("level"), p.get("text")) if isinstance(p, Mapping) else (i + 1, p)
        if lvl == 2 and isinstance(txt, str):
            text = txt.strip()
    if not text:
        return None
    return next((z for z in vocab.zone_ids() if h2_text(z) == text), None)


def _focus(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    telemetry: Sequence[TelemetryEvent],
    zones: Mapping[str, np.ndarray],
    sc: Mapping[str, Any],
    cards: Mapping[str, TeachingCard],
    previous: Sequence[Any] | None,
) -> tuple[str | None, TeachingCard | None]:
    """(zone, card whose first key sign H3 uses) for H2/H3."""
    abnormal = not case.is_normal and bool(case.findings)
    target = hardest_unmarked(case, marks, sc) if abnormal else None
    if target is None and abnormal:
        target = next((f for f in case.findings if f.kind == "pattern"), None)
    if target is not None and target.primary_zone:
        return target.primary_zone, cards.get(target.label)
    prefer = _previous_h2_zone(previous) if level >= 3 else None
    dwell = zone_dwell(telemetry, zones, sc)
    if target is not None:  # finding without a zone: least-dwelt place where its card says it hides
        card = cards.get(target.label)
        cands = _available((card.where_it_hides if card else None) or hint_zones(cards), zones)
        return (prefer if prefer in cands else least_dwelt(cands, dwell, case.case_id)), card
    cands = _available(hint_zones(cards) or vocab.review_area_ids(), zones)
    zone = prefer if prefer in cands else least_dwelt(cands, dwell, case.case_id)
    if zone is None:
        return None, None
    hiding = sorted(
        (c for c in cards.values() if zone in c.where_it_hides), key=lambda c: _rank(case.case_id, zone + c.label)
    )
    return zone, (hiding[0] if hiding else None)


def hint(
    level: int,
    case: Case,
    marks: Sequence[Mark],
    telemetry: Sequence[TelemetryEvent],
    zones: Mapping[str, np.ndarray],
    cfg: Mapping[str, Any] | None = None,
    cards: dict[str, TeachingCard] | None = None,
    *,
    previous: Sequence[Any] | None = None,
    zone_mimics: Mapping[str, Any] | None = None,
) -> str:
    """Hint text for ladder step `level` (1..3). `cfg` is config/scoring.yaml (loaded if None).

    `previous`: the texts of the hints already given on this attempt (or hint-log dicts with "level"/"text"), so H3
    stays in the zone H2 named."""
    level = min(3, max(1, int(level)))
    sc = cfg if cfg is not None else vocab.scoring_cfg()
    if level == 1:
        un = unvisited_review_areas(telemetry, zones, sc)
        if not un:
            return H1_ALL_VISITED
        return h1_text(h1_areas(un, zone_dwell(telemetry, zones, sc)))
    cards = cards if cards is not None else load_cards()
    zone, card = _focus(level, case, marks, telemetry, zones, sc, cards, previous)
    if zone is None:
        return H1_ALL_VISITED
    if level == 2:
        return h2_text(zone)
    sign = card.key_signs[0] if card and card.key_signs else GENERIC_SIGN
    zm = zone_mimics if zone_mimics is not None else load_zone_mimics()
    mims = list((zm.get("entries") or {}).get(zone) or [])
    return h3_text(zone, sign, mims[0] if mims else GENERIC_MIMIC)
