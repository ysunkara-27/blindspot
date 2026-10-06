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


def zone_human(zone: str | None) -> str:
    if not zone:
        return "an unlabelled area"
    z = review_areas_cfg().get("zones", {}).get(zone)
    return z["human"] if z and "human" in z else zone.replace("_", " ")


def zone_hardness(zone: str | None) -> float:
    z = review_areas_cfg().get("zones", {}).get(zone or "", {})
    return float(z.get("hardness", 0.5))


def zone_ids() -> list[str]:
    return list(review_areas_cfg().get("zones", {}).keys())


def review_area_ids() -> list[str]:
    return list(review_areas_cfg().get("review_areas", []))


@lru_cache
def _adjacency() -> dict[str, frozenset[str]]:
    """Symmetric closure of config adjacency."""
    adj: dict[str, set[str]] = {}
    for z, ns in (review_areas_cfg().get("adjacency") or {}).items():
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
    return None
