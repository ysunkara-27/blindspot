"""Reference bank ("what does X look like"): teaching-card text + a few outlined example films per label.

Examples are listed in config/reference_bank.yaml (written by pipeline/reference_bank.py, clinician-editable) and come
from the BENCH split only. Volumetric (CT / MR) picks live in <processed>/reference_bank_volumetric.json
({"labels": {label: [{case_id, finding_id}]}}; `build_volumetric_bank` writes it); when that file is absent the bench
volumetric cases are picked deterministically (sorted case ids, up to MAX_EXAMPLES per label). A volumetric example
ships its label volume (`mask_url`, bench cases only: never served as cases).
Bench cases are evaluation-only and are never served to learners, so their outlines are
not a ground-truth leak. Defence in depth: whatever the YAML says, an entry is dropped here unless its case exists in
this data bundle, is a bench case with no disqualifying QA flag, has its image on disk, and (for a label example)
carries that finding with that label. Nothing here raises: a missing or broken YAML gives labels with no examples.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from backend.app import config, tutor_bridge
from backend.app.adaptive.selector import qa_ok
from backend.app.cases import CaseRepository, get_repo, processed_root
from backend.app.settings import get_settings
from backend.app.volumes import provenance_badge, volume_url
from shared.contracts import VOLUME_LABELS, Case, Component, Measure, TeachingCard, Window

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


class ReferenceVolumeFinding(BaseModel):
    finding_id: str  # short id
    bbox: tuple[float, float, float, float]  # axial in-plane box (x0, y0, x1, y1)
    slice_range: list[int] | None
    centroid3: list[float] | None
    label_values: list[int] | None
    components: list[Component] | None
    measure: Measure | None
    relative_location: str | None
    side: str | None


class ReferenceVolumeExample(BaseModel):
    """A bench CT/MR case with its label volume: volume_url = voxels, mask_url = labels (bench only)."""

    case_id: str
    modality: str
    body_region: str | None
    volume_url: str
    mask_url: str
    shape: list[int]
    spacing: list[float]
    window: Window
    sequence: str | None
    labels: dict[str, str]  # mask value → id (organs and finding labels)
    measure_slice: int | None
    provenance: dict[str, Any] | None
    finding: ReferenceVolumeFinding


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
    modality: str = "cxr"  # the label's modality (taxonomy): cxr | ct | mr
    examples: list[ReferenceExample]
    volume_examples: list[ReferenceVolumeExample] = []


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
        "modality": config.label_modality(label),
        "examples": examples,
        "volume_examples": volume_examples(repo, label),
    }


# ------------------------------------------------------------------ volumetric examples
def volumetric_bank_path(repo: CaseRepository | None = None) -> Path:
    env = os.environ.get("BLINDSPOT_REFERENCE_BANK_VOLUMETRIC")
    if env:
        return Path(env)
    return (repo.root if repo else processed_root()) / "reference_bank_volumetric.json"


def load_volumetric_bank(repo: CaseRepository | None = None) -> dict[str, Any] | None:
    """Parsed JSON, or None when the file is missing/broken (then bench cases are picked automatically)."""
    p = volumetric_bank_path(repo)
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        if p.exists():
            log.warning("volumetric reference bank %s unreadable: %s", p, e)
        return None
    return doc if isinstance(doc, dict) else None


def auto_volumetric_picks(repo: CaseRepository, label: str, per_label: int = MAX_EXAMPLES) -> list[dict[str, Any]]:
    """Deterministic fallback: bench volumetric cases carrying `label`, sorted by case id."""
    out = []
    for c in sorted(repo.by_split(REFERENCE_SPLIT), key=lambda c: c.case_id):
        if c.volume is None or not qa_ok(c.qa_flags):
            continue
        f = next((f for f in c.findings if f.label == label), None)
        if f is not None:
            out.append({"case_id": c.case_id, "finding_id": f.finding_id})
        if len(out) >= per_label:
            break
    return out


def build_volumetric_bank(repo: CaseRepository, per_label: int = MAX_EXAMPLES) -> dict[str, Any]:
    """{"version": 1, "split": "bench", "labels": {label: [{case_id, finding_id}]}} for every volumetric label."""
    return {
        "version": 1,
        "split": REFERENCE_SPLIT,
        "labels": {lab: auto_volumetric_picks(repo, lab, per_label) for lab in VOLUME_LABELS},
    }


def write_volumetric_bank(repo: CaseRepository, path: Path | None = None) -> Path:
    p = path or volumetric_bank_path(repo)
    p.write_text(json.dumps(build_volumetric_bank(repo), indent=2) + "\n")
    return p


def mask_url(case_id: str) -> str:
    return f"{get_settings().api_prefix}/reference/{case_id}/maskvol"


def _volume_example(repo: CaseRepository, label: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    c = _usable_case(repo, entry.get("case_id"))
    fid = entry.get("finding_id")
    if c is None or c.volume is None or not isinstance(fid, str):
        return None
    f = repo.finding(c, fid)
    if f is None or f.label != label:
        log.warning("reference: %s is not a %s finding on %s; skipped", fid, label, c.case_id)
        return None
    p = repo.volume_path(c)
    if p is None or not p.exists():
        return None
    return {
        "case_id": c.case_id,
        "modality": c.modality,
        "body_region": c.body_region,
        "volume_url": volume_url(c.case_id),
        "mask_url": mask_url(c.case_id),
        "shape": [int(n) for n in c.volume.shape],
        "spacing": [float(x) for x in c.volume.spacing],
        "window": c.volume.window,
        "sequence": c.volume.sequence,
        "labels": dict(c.volume.labels),
        "measure_slice": f.measure.slice if f.measure else None,
        "provenance": provenance_badge(c),
        "finding": {
            "finding_id": f.short_id,
            "bbox": list(f.geometry.bbox),
            "slice_range": list(f.slice_range) if f.slice_range else None,
            "centroid3": list(f.centroid3) if f.centroid3 else None,
            "label_values": list(f.label_values) if f.label_values else None,
            "components": f.components,
            "measure": f.measure,
            "relative_location": f.relative_location,
            "side": f.side,
        },
    }


def volume_examples(repo: CaseRepository, label: str) -> list[dict[str, Any]]:
    if label not in VOLUME_LABELS:
        return []
    bank = load_volumetric_bank(repo)
    listed = _entries((bank.get("labels") or {}).get(label)) if bank else auto_volumetric_picks(repo, label)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in listed:
        ex = _volume_example(repo, label, e)
        if ex is None or ex["case_id"] in seen:
            continue
        seen.add(ex["case_id"])
        out.append(ex)
        if len(out) >= MAX_EXAMPLES:
            break
    return out


def reference_maskvol(case_id: str, repo: CaseRepository | None = None) -> bytes | None:
    """Gzipped label volume of a BENCH volumetric case (reference examples only); None otherwise."""
    repo = repo or get_repo()
    c = _usable_case(repo, case_id)
    p = repo.maskvol_path(c) if c and c.volume else None
    return p.read_bytes() if p and p.exists() else None


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


if (
    __name__ == "__main__"
):  # uv run python -m backend.app.reference [--processed DIR] → writes reference_bank_volumetric.json
    import argparse

    ap = argparse.ArgumentParser(
        description="Write <processed>/reference_bank_volumetric.json from the bench CT/MR cases."
    )
    ap.add_argument("--processed", type=Path, default=None)
    a = ap.parse_args()
    _repo = CaseRepository(a.processed) if a.processed else get_repo()
    _out = write_volumetric_bank(_repo)
    print(f"wrote {_out}: " + json.dumps({k: len(v) for k, v in json.loads(_out.read_text())["labels"].items()}))
