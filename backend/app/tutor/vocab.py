"""Read-only vocabulary for the tutor: labels, zones, adjacency, validator settings (from config/*.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.app.settings import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "config"
CARDS_DIR = REPO_ROOT / "content" / "teaching_cards"
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
SCHEMAS_DIR = REPO_ROOT / "shared" / "schemas"

SIDES = ("right", "left")
VOLUMETRIC_MODALITIES = ("ct", "mr")
# Volumetric zone ids whose name does not start with the side word (config review_areas.yaml `volumetric.zones`).
_VOLUME_SIDED = {"brain_left": "left", "brain_right": "right", "left_half": "left", "right_half": "right"}


@lru_cache
def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG_DIR / name).read_text()) or {}


def taxonomy() -> dict[str, Any]:
    return _yaml("taxonomy.yaml")


def review_areas_cfg() -> dict[str, Any]:
    return _yaml("review_areas.yaml")


def scoring_cfg() -> dict[str, Any]:
    return _yaml("scoring.yaml")


def validator_cfg() -> dict[str, Any]:
    return dict(scoring_cfg().get("validator", {}))


@lru_cache
def labels() -> dict[str, dict[str, Any]]:
    return {d["id"]: d for d in taxonomy()["labels"]}


def display(label: str) -> str:
    if label == "not_sure":
        return "Not sure"
    return labels().get(label, {}).get("display", label.replace("_", " "))


def kind(label: str) -> str:
    return labels().get(label, {}).get("kind", "focal")


@lru_cache
def related_groups() -> tuple[frozenset[str], ...]:
    return tuple(frozenset(g) for g in taxonomy().get("related_groups", []))


def related(label_set: set[str] | frozenset[str]) -> set[str]:
    """Labels in the same related group as any label in `label_set` (including the labels themselves)."""
    out = set(label_set)
    for g in related_groups():
        if g & out:
            out |= g
    return out


def _zone_cfg(zone: str) -> dict[str, Any]:
    z = review_areas_cfg().get("zones", {}).get(zone)
    if z is None:
        z = volumetric_cfg().get("zones", {}).get(zone)
    return dict(z or {})


def zone_human(zone: str | None) -> str:
    if not zone:
        return "an unlabelled area"
    z = _zone_cfg(zone)
    return z["human"] if "human" in z else zone.replace("_", " ")


def zone_hardness(zone: str | None) -> float:
    return float(_zone_cfg(zone or "").get("hardness", 0.5))


def zone_ids() -> list[str]:
    """X-ray zone ids (config `zones`). Volumetric zones: volumetric_zone_ids(); both: all_zone_ids()."""
    return list(review_areas_cfg().get("zones", {}).keys())


def review_area_ids() -> list[str]:
    return list(review_areas_cfg().get("review_areas", []))


@lru_cache
def _adjacency() -> dict[str, frozenset[str]]:
    """Symmetric closure of config adjacency (X-ray zones and volumetric zones together; the id sets are disjoint)."""
    adj: dict[str, set[str]] = {}
    for section in (review_areas_cfg().get("adjacency") or {}, volumetric_cfg().get("adjacency") or {}):
        for z, ns in section.items():
            for n in ns:
                adj.setdefault(z, set()).add(n)
                adj.setdefault(n, set()).add(z)
    return {k: frozenset(v) for k, v in adj.items()}


def neighbors(zone: str) -> frozenset[str]:
    return _adjacency().get(zone, frozenset())


def side_of_zone(zone: str | None) -> str | None:
    if not zone:
        return None
    for s in SIDES:
        if zone.startswith(s + "_"):
            return s
    return _VOLUME_SIDED.get(zone)


# --------------------------------------------------------------------------- volumetric (CT / MR)
def is_volumetric(modality: str | None) -> bool:
    return (modality or "cxr") in VOLUMETRIC_MODALITIES


def volumetric_cfg() -> dict[str, Any]:
    """The `volumetric` section of config/review_areas.yaml (zones, review_areas by body region, adjacency, mimics)."""
    return dict(review_areas_cfg().get("volumetric") or {})


def volumetric_zone_ids() -> list[str]:
    return list(volumetric_cfg().get("zones", {}).keys())


def all_zone_ids() -> list[str]:
    return zone_ids() + [z for z in volumetric_zone_ids() if z not in zone_ids()]


def volumetric_review_area_ids(body_region: str | None) -> list[str]:
    """Coverage targets for a body region (config `volumetric.review_areas`); the slab thirds when unknown."""
    areas = volumetric_cfg().get("review_areas") or {}
    if body_region and body_region in areas:
        return list(areas[body_region])
    return [z for z in ("superior_slab", "mid_slab", "inferior_slab") if z in volumetric_zone_ids()]


def volumetric_scoring_cfg() -> dict[str, Any]:
    return dict(scoring_cfg().get("volumetric") or {})


def modality_of_label(label: str) -> str:
    return str(labels().get(label, {}).get("modality") or "cxr")


def learner_options(modality: str | None) -> list[str]:
    opts = taxonomy().get("learner_focal_options_by_modality") or {}
    if modality in opts:
        return list(opts[modality])
    return list(taxonomy().get("learner_focal_options", []))
