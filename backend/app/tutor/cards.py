"""Teaching cards (content/teaching_cards/<label>.yaml) and zone mimics, plus the cached system-prompt block."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.app.tutor import vocab
from shared.contracts import ReviewStatus, TeachingCard

STATUS_ORDER: tuple[ReviewStatus, ...] = ("ai_draft", "student_reviewed", "radiologist_reviewed")
ZONE_MIMICS_DRAFT = "_zone_mimics_draft.yaml"


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


# --------------------------------------------------------------------------- zone mimics
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
    return list((zm.get("entries") or {}).get(zone or "", []))


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
- what_it_looks_like: one or two short signs from that label's card.
- overcalls: exactly one entry per FACTS outcome whose result is false_positive (use its mark id). possible_mimics:
  normal structures from ZONE MIMICS for that mark's zone, or the mimics on the card of the label the learner chose.
- verdict: all_found = every finding found; partly_found = some found or mislabeled, some missed; missed = no
  finding found; correct_normal = normal film called normal with no marks; overcall = normal film with marks;
  missed_normal_call = the learner called an abnormal film normal.
- search_coaching: use search.unvisited_review_areas and first_visits.
- calibration_note: only when a confident (4-5) mark or normal call was wrong; otherwise "".
- next_step: one concrete thing to do on the next film.
- Crowded films (more than 8 findings): keep each finding entry to a few words."""


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
    return "\n".join(parts).strip() + "\n"


def all_cards_text() -> str:
    return cards_block_text()


def content_hash(cards: dict[str, TeachingCard] | None = None, zone_mimics: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(cards_block_text(cards, zone_mimics).encode()).hexdigest()
