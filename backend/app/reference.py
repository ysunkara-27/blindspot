"""Reference bank ("what does X look like"): teaching-card text + a few outlined example films per label.

Examples are listed in config/reference_bank.yaml (written by pipeline/reference_bank.py, clinician-editable) and come
from the BENCH split only. Bench cases are evaluation-only and are never served to learners, so their outlines are
not a ground-truth leak. Defence in depth: whatever the YAML says, an entry is dropped here unless its case exists in
this data bundle, is a bench case with no disqualifying QA flag, has its image on disk, and (for a label example)
carries that finding with that label. Nothing here raises: a missing or broken YAML gives labels with no examples.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from backend.app import config, tutor_bridge
from backend.app.adaptive.selector import qa_ok
from backend.app.cases import CaseRepository, get_repo
from backend.app.settings import get_settings
from shared.contracts import Case, TeachingCard

log = logging.getLogger("blindspot.reference")
REFERENCE_SPLIT = "bench"
MAX_EXAMPLES = 3


# ------------------------------------------------------------------ response models (GET /api/reference)
class ReferenceFinding(BaseModel):
    finding_id: str  # short id, e.g. "F1"
    polygon: list[tuple[float, float]] | None
    bbox: tuple[float, float, float, float]
    relative_location: str | None
    side: str | None


class ReferenceNormal(BaseModel):
    case_id: str
    image_url: str
    width: int
    height: int


class ReferenceExample(ReferenceNormal):
    finding: ReferenceFinding


class ReferenceLabel(BaseModel):
    label: str
    display: str
    kind: str
    one_liner: str
    key_signs: list[str]
    mimics: list[str]
    commonly_confused_with: list[str]
    search_tip: str
    radiopaedia_url: str | None
    review_status: str
    examples: list[ReferenceExample]


class ReferenceBank(BaseModel):
    labels: list[ReferenceLabel]
    normal_examples: list[ReferenceNormal]


# ------------------------------------------------------------------ bank file
def bank_path() -> Path:
    env = os.environ.get("BLINDSPOT_REFERENCE_BANK")
    return Path(env) if env else config.CONFIG_DIR / "reference_bank.yaml"


@lru_cache(maxsize=8)
def _read_bank(path: str, _mtime_ns: int) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as e:
        log.warning("reference bank %s unreadable: %s", path, e)
        return {}
    return doc if isinstance(doc, dict) else {}


def load_bank(path: Path | None = None) -> dict[str, Any]:
    """Parsed YAML ({} when missing or malformed). Re-read when the file changes (clinician edits)."""
    p = Path(path) if path else bank_path()
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return {}
    return _read_bank(str(p), mtime)


def _entries(x: Any) -> list[dict[str, Any]]:
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []


# ------------------------------------------------------------------ building the payload
def image_url(case_id: str) -> str:
    """Same URL the reading room uses (base-path aware); see services.image_url."""
    return f"{get_settings().api_prefix}/cases/{case_id}/image"


def _usable_case(repo: CaseRepository, case_id: Any) -> Case | None:
    """The case if it may be shown as a reference example, else None (logged at debug; never raises)."""
    c = repo.get(case_id) if isinstance(case_id, str) else None
    if c is None:
        log.debug("reference: case %r not in this data bundle; skipped", case_id)
        return None
    if c.split != REFERENCE_SPLIT:
        log.warning("reference: %s is in split %r, not %r; refused", c.case_id, c.split, REFERENCE_SPLIT)
        return None
    if not qa_ok(c.qa_flags):
        log.warning("reference: %s has qa_flags %s; refused", c.case_id, c.qa_flags)
        return None
    try:
        if not repo.image_path(c).exists():
            log.debug("reference: image for %s missing; skipped", c.case_id)
            return None
    except OSError:
        return None
    return c


def _shape(c: Case) -> dict[str, Any]:
    return {"case_id": c.case_id, "image_url": image_url(c.case_id), "width": c.width, "height": c.height}


def _example(repo: CaseRepository, label: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    c = _usable_case(repo, entry.get("case_id"))
    fid = entry.get("finding_id")
    if c is None or not isinstance(fid, str):
        return None
    f = repo.finding(c, fid)
    if f is None or f.label != label:
        log.warning("reference: %s is not a %s finding on %s; skipped", fid, label, c.case_id)
        return None
    return {
        **_shape(c),
        "finding": {
            "finding_id": f.short_id,
            "polygon": [list(p) for p in f.geometry.polygon] if f.geometry.polygon else None,
            "bbox": list(f.geometry.bbox),
            "relative_location": f.relative_location,
            "side": f.side,
        },
    }


def _label_entry(
    repo: CaseRepository, label: str, card: TeachingCard | None, listed: list[dict[str, Any]]
) -> dict[str, Any]:
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in listed:
        ex = _example(repo, label, e)
        if ex is None or ex["case_id"] in seen:
            continue
        seen.add(ex["case_id"])
        examples.append(ex)
        if len(examples) >= MAX_EXAMPLES:
            break
    return {
        "label": label,
        "display": config.display(label),
        "kind": config.label_kind(label),
        "one_liner": card.one_liner if card else "",
        "key_signs": list(card.key_signs) if card else [],
        "mimics": list(card.mimics) if card else [],
        "commonly_confused_with": list(card.commonly_confused_with) if card else [],
        "search_tip": card.search_tip if card else "",
        "radiopaedia_url": card.radiopaedia_url if card else None,
        "review_status": card.review.status if card else "ai_draft",
        "examples": examples,
    }


def _cards() -> dict[str, TeachingCard]:
    try:
        from backend.app.tutor.cards import load_cards

        d = config.cards_dir()
        return load_cards(d) if d.exists() else {}
    except Exception:  # noqa: BLE001 — tutor module missing or a broken card: fall back to the bridge loader
        log.exception("reference: tutor.cards.load_cards failed")
        try:
            return tutor_bridge.load_cards()
        except Exception:  # noqa: BLE001
            return {}


def label_ids() -> list[str]:
    return list(config.labels())


def _listed(bank: dict[str, Any]) -> dict[str, Any]:
    labels = bank.get("labels")
    return labels if isinstance(labels, dict) else {}


def reference_label(label: str, repo: CaseRepository | None = None) -> dict[str, Any] | None:
    """One `labels[]` entry, or None for a label outside the taxonomy."""
    if label not in config.labels():
        return None
    return _label_entry(repo or get_repo(), label, _cards().get(label), _entries(_listed(load_bank()).get(label)))


def reference(repo: CaseRepository | None = None) -> dict[str, Any]:
    """{labels: [...13 in taxonomy order...], normal_examples: [...]}."""
    repo = repo or get_repo()
    bank = load_bank()
    listed = _listed(bank)
    cards = _cards()
    labels = [_label_entry(repo, lab, cards.get(lab), _entries(listed.get(lab))) for lab in label_ids()]
    normals: list[dict[str, Any]] = []
    for e in _entries(bank.get("normal")):
        c = _usable_case(repo, e.get("case_id"))
        if c is None or not c.is_normal or c.findings or any(n["case_id"] == c.case_id for n in normals):
            continue
        normals.append(_shape(c))
        if len(normals) >= MAX_EXAMPLES:
            break
    return {"labels": labels, "normal_examples": normals}
