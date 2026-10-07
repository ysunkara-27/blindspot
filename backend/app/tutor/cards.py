"""Teaching cards (content/teaching_cards/<label>.yaml) and zone mimics, plus the cached system-prompt block."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from backend.app.tutor import vocab
from shared.contracts import CardReview, ReviewStatus, TeachingCard

STATUS_ORDER: tuple[ReviewStatus, ...] = ("ai_draft", "student_reviewed", "radiologist_reviewed")
ZONE_MIMICS_DRAFT = "_zone_mimics_draft.yaml"
ANATOMY_PREFIX = "_anatomy_"


class AnatomyCard(BaseModel):
    """Anatomy explainer (content/teaching_cards/_anatomy_<name>.yaml): used by hints and ask-the-tutor on CT / MR
    cases, never as a finding. Names normal structures only."""

    model_config = ConfigDict(extra="forbid")
    anatomy: str
    display_name: str
    zones: list[str] = []
    modality: str | None = None
    body_region: str | None = None
    one_liner: str
    landmarks: list[str] = []
    mimics: list[str] = []
    review: CardReview


# --------------------------------------------------------------------------- cards
def _signature(directory: Path) -> tuple[tuple[str, int], ...]:
    return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(directory.glob("*.yaml")))


def load_cards(directory: Path | None = None) -> dict[str, TeachingCard]:
    """All cards keyed by label, schema-validated. Re-reads when a file changes (review write-back)."""
    d = Path(directory) if directory else vocab.CARDS_DIR
    return dict(_load_cards_cached(str(d), _signature(d)))


@lru_cache(maxsize=8)
def _load_cards_cached(directory: str, _sig: tuple) -> dict[str, TeachingCard]:
    out: dict[str, TeachingCard] = {}
    for p in sorted(Path(directory).glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        card = TeachingCard.model_validate(yaml.safe_load(p.read_text()))
        if card.label != p.stem:
            raise ValueError(f"{p.name}: label {card.label!r} does not match the file name")
        out[card.label] = card
    return out


def load_anatomy(directory: Path | None = None) -> dict[str, AnatomyCard]:
    """Anatomy explainers keyed by anatomy id (files `_anatomy_*.yaml`). Re-read when a file changes."""
    d = Path(directory) if directory else vocab.CARDS_DIR
    return dict(_load_anatomy_cached(str(d), _signature(d)))


@lru_cache(maxsize=8)
def _load_anatomy_cached(directory: str, _sig: tuple) -> dict[str, AnatomyCard]:
    out: dict[str, AnatomyCard] = {}
    for p in sorted(Path(directory).glob(f"{ANATOMY_PREFIX}*.yaml")):
        card = AnatomyCard.model_validate(yaml.safe_load(p.read_text()))
        if p.stem != ANATOMY_PREFIX + card.anatomy:
            raise ValueError(f"{p.name}: anatomy {card.anatomy!r} does not match the file name")
        out[card.anatomy] = card
    return out


def anatomy_for_zone(zone: str | None, anatomy: dict[str, AnatomyCard] | None = None) -> AnatomyCard | None:
    cards = anatomy if anatomy is not None else load_anatomy()
    return next((c for c in cards.values() if zone and zone in c.zones), None)


def cards_for_modality(modality: str | None, cards: dict[str, TeachingCard] | None = None) -> dict[str, TeachingCard]:
    """Cards whose label belongs to this modality (taxonomy `modality`, default cxr)."""
    cards = cards if cards is not None else load_cards()
    m = modality or "cxr"
    return {k: v for k, v in cards.items() if (v.modality or vocab.modality_of_label(k)) == m}


# --------------------------------------------------------------------------- zone mimics
def load_volumetric_zone_mimics() -> dict[str, Any]:
    """{"status", "entries": {zone: [str, ...]}} from config `volumetric.zone_mimics` (CT / MR zones)."""
    cfg = vocab.volumetric_cfg().get("zone_mimics") or {}
    return {"status": cfg.get("status", "ai_draft"), "entries": dict(cfg.get("entries") or {})}


def load_zone_mimics() -> dict[str, Any]:
    """{"status": ..., "entries": {zone: [str, ...]}} from config; the tutor draft if config is still empty."""
    cfg = vocab.review_areas_cfg().get("zone_mimics") or {}
    if cfg.get("entries"):
        return {"status": cfg.get("status", "ai_draft"), "entries": dict(cfg["entries"])}
    p = vocab.CARDS_DIR / ZONE_MIMICS_DRAFT
    if p.exists():
        doc = (yaml.safe_load(p.read_text()) or {}).get("zone_mimics", {})
        return {"status": doc.get("status", "ai_draft"), "entries": dict(doc.get("entries") or {})}
    return {"status": "ai_draft", "entries": {}}


def zone_mimics_for(zone: str | None, zone_mimics: dict[str, Any] | None = None) -> list[str]:
    zm = zone_mimics if zone_mimics is not None else load_zone_mimics()
    out = list((zm.get("entries") or {}).get(zone or "", []))
    if not out and zone in vocab.volumetric_zone_ids():
        out = list(load_volumetric_zone_mimics()["entries"].get(zone, []))
    return out


def all_zone_mimics(zone_mimics: dict[str, Any] | None = None) -> dict[str, Any]:
    """X-ray zone mimics plus the volumetric ones in a single {"status", "entries"} (ids are disjoint)."""
    zm = zone_mimics if zone_mimics is not None else load_zone_mimics()
    vz = load_volumetric_zone_mimics()
    entries = {**(vz.get("entries") or {}), **(zm.get("entries") or {})}
    statuses = [_status_of(zm.get("status")), _status_of(vz.get("status"))]
    return {"status": min(statuses, key=STATUS_ORDER.index), "entries": entries}


# --------------------------------------------------------------------------- provenance
def _status_of(s: str | None) -> ReviewStatus:
    return s if s in STATUS_ORDER else "ai_draft"  # type: ignore[return-value]


def lowest_provenance(
    labels: Iterable[str],
    cards: dict[str, TeachingCard] | None = None,
    *,
    include_zone_mimics: bool = False,
) -> ReviewStatus:
    """Lowest review status among the cards used (SPEC §11.2). No cards → ai_draft."""
    cards = cards if cards is not None else load_cards()
    statuses = [cards[lab].review.status for lab in labels if lab in cards]
    if include_zone_mimics:
        statuses.append(_status_of(load_zone_mimics().get("status")))
    if not statuses:
        return "ai_draft"
    return min(statuses, key=STATUS_ORDER.index)


# --------------------------------------------------------------------------- system block
FIELD_GUIDE = """OUTPUT FIELD GUIDE (applies to every debrief)
- findings: exactly one entry per FACTS finding id (F1, F2, ...); copy each result from FACTS outcomes.
- where_to_look: build it from that finding's relative_location and zone names in FACTS (plain words, never ids
  with underscores). For a pattern finding, start from its relative_location when FACTS gives one (e.g. "cardiac
  silhouette", "left lung, mainly the lower zone") and say what to compare (for cardiomegaly: heart width against
  inner chest width, using ctr if given).
- what_it_looks_like: one or two short signs from that label's card. NEVER an empty list: every finding, found or
  missed, focal or pattern, gets at least one sign.
- why: one full sentence of at least 6 words about what the learner did at that finding (searched, passed over,
  judged normal, mislabeled, found). Never a stub such as "Never examined." or "Pattern missed."
- overcalls: exactly one entry per FACTS outcome whose result is false_positive (use its mark id). possible_mimics:
  normal structures from ZONE MIMICS for that mark's zone, or the mimics on the card of the label the learner chose.
- verdict: all_found = every finding found; partly_found = some found or mislabeled, some missed; missed = no
  finding found; correct_normal = normal film called normal with no marks; overcall = normal film with marks;
  missed_normal_call = the learner called an abnormal film normal.
- search_coaching: use search.unvisited_review_areas and first_visits.
- calibration_note: only when a confident (4-5) mark or normal call was wrong; otherwise "".
- next_step: one concrete thing to do on the next film.
- Crowded films (5 or more findings): keep each entry short (zone name, one sign, one short sentence), but still
  one sign and a why of at least 6 words for every finding.
- If the user message has a DRILL FOCUS line, lead the headline with that finding type; still list every finding.
- CT / MR volumes (FACTS case.modality ct or mr): where_to_look = the finding's relative_location from FACTS (organ or
  slab, patient's side, slice range) in plain words. Sizes only as FACTS gives them (size_mm, the learner's
  measurement, the size_verdict) and always in mm. Outcomes with result unmatched get an overcall entry too: say the
  reference does not label that spot and that public datasets are not exhaustive; never call it wrong or false and
  never guess what it is; possible_mimics from ZONE MIMICS for that mark's zone (or [] when the zone is unknown)."""


def _card_text(c: TeachingCard) -> str:
    lines = [
        f"## {c.label} ({c.display_name}, {c.kind})",
        f"One-liner: {c.one_liner}",
        "Key signs:",
        *[f"- {s}" for s in c.key_signs],
        "Where it hides: " + ", ".join(vocab.zone_human(z) for z in c.where_it_hides),
        "Mimics:",
        *[f"- {m}" for m in c.mimics],
        "Commonly confused with: " + (", ".join(vocab.display(x) for x in c.commonly_confused_with) or "none"),
        f"Search tip: {c.search_tip}",
    ]
    return "\n".join(lines)


def cards_block_text(cards: dict[str, TeachingCard] | None = None, zone_mimics: dict[str, Any] | None = None) -> str:
    """Deterministic text for the cached second system block. Excludes review metadata and URLs so card
    approvals do not invalidate the prompt cache."""
    cards = cards if cards is not None else load_cards()
    zm = zone_mimics if zone_mimics is not None else load_zone_mimics()
    parts = [FIELD_GUIDE, "", "TEACHING CARDS (all labels; the labels for this case are named in FACTS)", ""]
    for label in sorted(cards):
        parts += [_card_text(cards[label]), ""]
    parts.append("ZONE MIMICS (normal structures often mistaken for abnormalities, by zone)")
    for z in sorted((zm.get("entries") or {})):
        parts.append(f"- {vocab.zone_human(z)}: " + "; ".join(zm["entries"][z]))
    vz = load_volumetric_zone_mimics()
    if vz.get("entries"):
        parts += ["", "ZONE MIMICS ON CT / MR VOLUMES (by volumetric zone)"]
        for z in sorted(vz["entries"]):
            parts.append(f"- {vocab.zone_human(z)}: " + "; ".join(vz["entries"][z]))
    anatomy = load_anatomy()
    if anatomy:
        parts += ["", "ANATOMY ON CT / MR VOLUMES (normal structures; never findings)"]
        for a in sorted(anatomy):
            parts += [_anatomy_text(anatomy[a]), ""]
    return "\n".join(parts).strip() + "\n"


def _anatomy_text(a: AnatomyCard) -> str:
    lines = [f"## {a.display_name} ({', '.join(vocab.zone_human(z) for z in a.zones) or a.anatomy})", a.one_liner]
    lines += ["Landmarks:", *[f"- {x}" for x in a.landmarks]]
    if a.mimics:
        lines += ["Looks like a finding but is normal:", *[f"- {m}" for m in a.mimics]]
    return "\n".join(lines)


def all_cards_text() -> str:
    return cards_block_text()


def content_hash(cards: dict[str, TeachingCard] | None = None, zone_mimics: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(cards_block_text(cards, zone_mimics).encode()).hexdigest()
