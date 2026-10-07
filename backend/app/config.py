"""YAML config access. Every threshold and weight used by the engines comes from config/*.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.app.settings import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "config"


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / name).read_text()) or {}


@lru_cache
def scoring() -> dict[str, Any]:
    return _load("scoring.yaml")


@lru_cache
def adaptive() -> dict[str, Any]:
    return _load("adaptive.yaml")


@lru_cache
def review_areas() -> dict[str, Any]:
    return _load("review_areas.yaml")


@lru_cache
def taxonomy() -> dict[str, Any]:
    return _load("taxonomy.yaml")


@lru_cache
def provenance() -> dict[str, Any]:
    return _load("provenance.yaml")


def provenance_datasets() -> dict[str, dict[str, Any]]:
    """config/provenance.yaml `datasets` keyed as the YAML, each with a `modality` (chestx-det → cxr, brain → mr,
    other MSD tasks → ct)."""
    out: dict[str, dict[str, Any]] = {}
    for key, d in (provenance().get("datasets") or {}).items():
        if not isinstance(d, dict):
            continue
        k = key.lower()
        mod = "cxr" if "chest" in k and "x" in k else "mr" if "brain" in k else "ct"
        out[key] = {**d, "modality": d.get("modality") or mod}
    return out


@lru_cache
def labels() -> dict[str, dict[str, Any]]:
    return {d["id"]: d for d in taxonomy()["labels"]}


def display(label: str) -> str:
    if label == "not_sure":
        return "Not sure"
    return labels().get(label, {}).get("display", label.replace("_", " "))


def label_kind(label: str) -> str:
    return labels().get(label, {}).get("kind", "focal")


@lru_cache
def core_labels() -> tuple[str, ...]:
    return tuple(d["id"] for d in taxonomy()["labels"] if d.get("core"))


@lru_cache
def related_groups() -> tuple[frozenset[str], ...]:
    return tuple(frozenset(g) for g in taxonomy().get("related_groups", []))


def zone_human(zone: str | None) -> str:
    if not zone:
        return "unknown region"
    z = review_areas().get("zones", {}).get(zone) or volumetric_zones_cfg().get(zone)
    return z["human"] if z else zone.replace("_", " ")


def zone_ids() -> list[str]:
    return list(review_areas().get("zones", {}).keys())


def review_area_ids() -> list[str]:
    return list(review_areas().get("review_areas", []))


# ------------------------------------------------------------------ volumetric (CT / MR)
MODALITIES = ("cxr", "ct", "mr")


def volumetric_cfg() -> dict[str, Any]:
    return scoring().get("volumetric") or {}


def volumetric_zones_cfg() -> dict[str, dict[str, Any]]:
    return (review_areas().get("volumetric") or {}).get("zones") or {}


def volumetric_review_areas(body_region: str | None) -> list[str]:
    areas = (review_areas().get("volumetric") or {}).get("review_areas") or {}
    return list(areas.get(body_region or "", []))


def label_modality(label: str) -> str:
    return str(labels().get(label, {}).get("modality") or "cxr")


@lru_cache
def learner_options(modality: str) -> tuple[str, ...]:
    """Learner focal options per modality (taxonomy learner_focal_options_by_modality; cxr falls back to the flat
    list)."""
    by = taxonomy().get("learner_focal_options_by_modality") or {}
    if modality in by:
        return tuple(by[modality])
    return tuple(taxonomy().get("learner_focal_options", [])) if modality == "cxr" else ()


@lru_cache
def core_labels_for(modality: str) -> tuple[str, ...]:
    """Core labels of ONE modality (selector pools, weak-areas, Elo targets). For cxr this is exactly the core list
    before the volumetric labels were added to the taxonomy."""
    return tuple(d["id"] for d in taxonomy()["labels"] if d.get("core") and (d.get("modality") or "cxr") == modality)


def cards_dir() -> Path:
    import os

    env = os.environ.get("BLINDSPOT_CARDS_DIR")
    return Path(env) if env else REPO_ROOT / "content" / "teaching_cards"


def signs_dir() -> Path:
    """content/signs/<id>.yaml: generic sign schematics (SignSchematic contract)."""
    import os

    env = os.environ.get("BLINDSPOT_SIGNS_DIR")
    return Path(env) if env else REPO_ROOT / "content" / "signs"
