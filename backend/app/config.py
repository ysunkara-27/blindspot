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
    z = review_areas().get("zones", {}).get(zone)
    return z["human"] if z else zone.replace("_", " ")


def zone_ids() -> list[str]:
    return list(review_areas().get("zones", {}).keys())


def review_area_ids() -> list[str]:
    return list(review_areas().get("review_areas", []))


def cards_dir() -> Path:
    import os

    env = os.environ.get("BLINDSPOT_CARDS_DIR")
    return Path(env) if env else REPO_ROOT / "content" / "teaching_cards"
