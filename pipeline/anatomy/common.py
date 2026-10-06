"""Shared paths, config access, and IO for the anatomy + features pipeline.

No torch imports here: the backend imports `pipeline.anatomy` for `spatial_relation` / `zone_at`.

Path conventions (relative paths stored in cases.jsonl are relative to `data/processed/`):
- anatomy npz: `anatomy/<case_id>.npz`  (format: shared/rle.py docstring + optional classifier keys)
- zones json:  `zones/<case_id>.json`   (shared.rle.write_zones)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]

# TorchXRayVision ChestX-Det PSPNet channel order (raw model names).
TXV_TARGETS: tuple[str, ...] = (
    "Left Clavicle",
    "Right Clavicle",
    "Left Scapula",
    "Right Scapula",
    "Left Lung",
    "Right Lung",
    "Left Hilus Pulmonis",
    "Right Hilus Pulmonis",
    "Heart",
    "Aorta",
    "Facies Diaphragmatica",
    "Mediastinum",
    "Weasand",
    "Spine",
)

IN_SCOPE_SPLITS: tuple[str, ...] = ("assess_A", "assess_B", "practice", "bench")

# Our label -> TXV DenseNet (densenet121-res224-all) pathology name. Labels absent here stay null
# (calcification and diffuse_nodule have no trained output in these weights).
TXV_CLASSIFIER_MAP: dict[str, str] = {
    "pneumothorax": "Pneumothorax",
    "effusion": "Effusion",
    "consolidation": "Consolidation",
    "atelectasis": "Atelectasis",
    "nodule": "Nodule",
    "mass": "Mass",
    "fracture": "Fracture",
    "pleural_thickening": "Pleural_Thickening",
    "cardiomegaly": "Cardiomegaly",
    "emphysema": "Emphysema",
    "fibrosis": "Fibrosis",
}


# --------------------------------------------------------------------------- paths
def data_dir() -> Path:
    p = Path(os.environ.get("BLINDSPOT_DATA_DIR", "data"))
    return p if p.is_absolute() else (REPO / p)


def processed_dir() -> Path:
    return data_dir() / "processed"


def qa_dir() -> Path:
    return data_dir() / "qa"


def cases_path() -> Path:
    return processed_dir() / "cases.jsonl"


def anatomy_rel(case_id: str) -> str:
    return f"anatomy/{case_id}.npz"


def zones_rel(case_id: str) -> str:
    return f"zones/{case_id}.json"


# --------------------------------------------------------------------------- config
@lru_cache(maxsize=1)
def review_cfg() -> dict[str, Any]:
    return yaml.safe_load((REPO / "config" / "review_areas.yaml").read_text())


def zone_ids() -> list[str]:
    return list(review_cfg()["zones"].keys())


def review_areas() -> list[str]:
    return list(review_cfg()["review_areas"])


def human(zone_id: str) -> str:
    z = review_cfg()["zones"].get(zone_id)
    if z:
        return str(z["human"])
    return {"right_lung": "right lung", "left_lung": "left lung", "lungs": "lungs"}.get(
        zone_id, zone_id.replace("_", " ")
    )


def hardness(zone_id: str | None, default: float = 0.5) -> float:
    if zone_id is None:
        return default
    z = review_cfg()["zones"].get(zone_id)
    return float(z["hardness"]) if z else default


@lru_cache(maxsize=1)
def adjacency() -> dict[str, frozenset[str]]:
    """Symmetric closure of config adjacency (config lists it one-way for some zones)."""
    adj: dict[str, set[str]] = {z: set() for z in zone_ids()}
    for a, bs in (review_cfg().get("adjacency") or {}).items():
        for b in bs:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in adj.items()}


# --------------------------------------------------------------------------- logging
def get_logger(name: str) -> logging.Logger:
    """Log to stdout; callers redirect to logs/anatomy.log (Makefile tees, background runs use >>)."""
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


# --------------------------------------------------------------------------- cases.jsonl
def read_cases(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or cases_path()
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def update_cases(update: Callable[[dict[str, Any]], dict[str, Any] | None], path: Path | None = None) -> int:
    """Atomically rewrite cases.jsonl, applying `update(case_dict)` to each line.

    `update` mutates/returns the dict (None = unchanged). Every line is validated with
    shared.contracts.Case before the rename. Other fields are preserved verbatim. If the file changes
    on disk while we work (another agent rewrote it), we re-read and retry.
    """
    from shared.contracts import Case

    p = path or cases_path()
    for _attempt in range(5):
        mtime = p.stat().st_mtime_ns
        lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
        out: list[str] = []
        changed = 0
        for ln in lines:
            d = json.loads(ln)
            before = json.dumps(d, sort_keys=True)
            r = update(d)
            d = d if r is None else r
            Case.model_validate(d)
            if json.dumps(d, sort_keys=True) != before:
                changed += 1
            out.append(json.dumps(d, separators=(",", ":")))
        tmp = p.with_suffix(".jsonl.tmp-anatomy")
        tmp.write_text("\n".join(out) + "\n")
        if p.stat().st_mtime_ns != mtime:
            tmp.unlink(missing_ok=True)
            time.sleep(1.0)
            continue
        os.replace(tmp, p)
        return changed
    raise RuntimeError(f"{p} kept changing while updating; giving up")


def add_flag(case: dict[str, Any], flag: str) -> None:
    flags = case.setdefault("qa_flags", [])
    if flag not in flags:
        flags.append(flag)


def remove_flag(case: dict[str, Any], flag: str) -> None:
    case["qa_flags"] = [f for f in case.get("qa_flags", []) if f != flag]


def in_scope(case: dict[str, Any], splits: Iterable[str] = IN_SCOPE_SPLITS) -> bool:
    return case.get("split") in set(splits)


# --------------------------------------------------------------------------- anatomy npz
def save_anatomy(path: Path, masks: np.ndarray, targets: Iterable[str], **extra: np.ndarray) -> None:
    """masks: bool (14, H, W). Writes atomically (tmp + rename) so resumable runs never see partial files."""
    masks = np.asarray(masks, dtype=bool)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(
        tmp,
        masks=np.packbits(masks, axis=-1),
        targets=np.array(list(targets)),
        shape=np.array(masks.shape),
        **extra,
    )
    os.replace(tmp, path)


def load_anatomy_raw(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    shape = tuple(int(s) for s in d["shape"])
    d["masks"] = np.unpackbits(d["masks"], axis=-1, count=shape[-1]).astype(bool).reshape(shape)
    d["targets"] = [str(t) for t in d["targets"]]
    return d


def clean_mask(m: np.ndarray, *, keep_largest_only: bool, min_rel: float = 0.2) -> np.ndarray:
    """Remove thresholding specks: keep the largest component (or all >= min_rel of the largest)."""
    m = np.asarray(m, dtype=bool)
    if not m.any():
        return m
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 2:
        return m
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = int(areas.max())
    if keep_largest_only:
        keep = [int(np.argmax(areas)) + 1]
    else:
        keep = [i + 1 for i, a in enumerate(areas) if a >= min_rel * big]
    return np.isin(lab, keep)


# Structures that are a single connected object; the rest (diaphragm domes, scapulae, aorta) may be split.
_SINGLE_OBJECT = {"Left Lung", "Right Lung", "Heart", "Left Clavicle", "Right Clavicle", "Spine", "Weasand"}


def clean_masks(masks: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {k: clean_mask(v, keep_largest_only=k in _SINGLE_OBJECT) for k, v in masks.items()}


def load_anatomy(path: Path, *, clean: bool = True) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Return ({target_name: bool mask}, extras) with names as stored (patient-side after orientation)."""
    d = load_anatomy_raw(path)
    masks = {name: d["masks"][i] for i, name in enumerate(d["targets"])}
    if clean:
        masks = clean_masks(masks)
    extras = {k: v for k, v in d.items() if k not in ("masks", "targets", "shape")}
    return masks, extras


def read_mask_png(rel_or_abs: str | Path, base: Path | None = None) -> np.ndarray:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = (base or processed_dir()) / p
    m = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise FileNotFoundError(p)
    return m > 0
