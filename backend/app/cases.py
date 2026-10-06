"""Case repository: cases.jsonl + masks + zones, loaded lazily with LRU caches.

Root = BLINDSPOT_PROCESSED_DIR if set, else settings.processed_dir (data/processed). Paths inside
cases.jsonl (image_path, mask_path, zones_path) are relative to the root.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.app.settings import get_settings
from shared.contracts import Case, Finding
from shared.rle import read_zones


def processed_root() -> Path:
    env = os.environ.get("BLINDSPOT_PROCESSED_DIR")
    return Path(env).resolve() if env else get_settings().processed_dir


def approximate_zones(width: int, height: int) -> dict[str, np.ndarray]:
    """SPEC §4.3 fallback: fixed-fraction zones (image halves and thirds). Patient right = image left."""
    yy, xx = np.mgrid[0:height, 0:width]
    xm = width / 2
    top, bot = 0.08 * height, 0.85 * height
    lung_y = (yy >= top) & (yy < bot)
    right = lung_y & (xx >= 0.08 * width) & (xx < xm - 0.04 * width)
    left = lung_y & (xx >= xm + 0.04 * width) & (xx < 0.92 * width)
    ext = bot - top
    z: dict[str, np.ndarray] = {}
    for side, lung, lat in (("right", right, xx < 0.25 * width), ("left", left, xx > 0.75 * width)):
        z[f"{side}_upper_zone"] = lung & (yy < top + ext / 3)
        z[f"{side}_mid_zone"] = lung & (yy >= top + ext / 3) & (yy < top + 2 * ext / 3)
        z[f"{side}_lower_zone"] = lung & (yy >= top + 2 * ext / 3)
        z[f"{side}_apex"] = lung & (yy < top + 0.18 * ext)
        z[f"{side}_costophrenic_angle"] = lung & (yy > bot - 0.18 * ext) & lat
        z[f"{side}_lung"] = lung
    z["right_hilum"] = (np.abs(xx - 0.40 * width) < 0.06 * width) & (np.abs(yy - 0.42 * height) < 0.08 * height)
    z["left_hilum"] = (np.abs(xx - 0.60 * width) < 0.06 * width) & (np.abs(yy - 0.42 * height) < 0.08 * height)
    z["mediastinum"] = (np.abs(xx - xm) < 0.08 * width) & (yy >= top) & (yy < 0.6 * height)
    z["cardiac_silhouette"] = (xx > 0.38 * width) & (xx < 0.72 * width) & (yy >= 0.5 * height) & (yy < 0.8 * height)
    z["retrocardiac"] = z["cardiac_silhouette"] & (xx > xm)
    z["subdiaphragmatic"] = (
        (yy >= bot) & (yy < min(height, bot + 0.08 * height)) & (xx > 0.08 * width) & (xx < 0.92 * width)
    )
    z["lungs"] = right | left
    return z


class CaseRepository:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cases: dict[str, Case] | None = None
        self.zones = lru_cache(maxsize=16)(self._zones)  # type: ignore[method-assign]
        self.mask = lru_cache(maxsize=256)(self._mask)  # type: ignore[method-assign]
        self.dilated_mask = lru_cache(maxsize=256)(self._dilated)  # type: ignore[method-assign]

    # ------------------------------------------------------------------ cases
    def _load(self) -> dict[str, Case]:
        if self._cases is None:
            p = self.root / "cases.jsonl"
            out: dict[str, Case] = {}
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.strip():
                        c = Case.model_validate_json(line)
                        out[c.case_id] = c
            self._cases = out
        return self._cases

    def count(self) -> int:
        return len(self._load())

    def all(self) -> list[Case]:
        return list(self._load().values())

    def get(self, case_id: str) -> Case | None:
        return self._load().get(case_id)

    def by_split(self, split: str) -> list[Case]:
        return [c for c in self._load().values() if c.split == split]

    def image_path(self, case: Case) -> Path:
        return self.root / case.image_path

    def finding(self, case: Case, short_or_full_id: str) -> Finding | None:
        for f in case.findings:
            if f.finding_id == short_or_full_id or f.short_id == short_or_full_id:
                return f
        return None

    # ------------------------------------------------------------------ masks
    def _mask(self, case_id: str, finding_id: str) -> np.ndarray | None:
        case = self.get(case_id)
        f = self.finding(case, finding_id) if case else None
        if f is None or not f.geometry.mask_path:
            return None
        p = self.root / f.geometry.mask_path
        if not p.exists():
            return None
        m = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if m is None:
            return None
        if m.shape != (case.height, case.width):
            m = cv2.resize(m, (case.width, case.height), interpolation=cv2.INTER_NEAREST)
        return m > 127

    def _dilated(self, case_id: str, finding_id: str, radius_px: int) -> np.ndarray | None:
        m = self.mask(case_id, finding_id)
        if m is None:
            return None
        return dilate(m, radius_px)

    # ------------------------------------------------------------------ zones
    def _zones(self, case_id: str) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        case = self.get(case_id)
        if case is None:
            raise KeyError(case_id)
        zp = self.root / case.zones_path if case.zones_path else None
        if zp is not None and (zp.exists() or zp.with_name(zp.name + ".gz").exists()):
            masks, meta = read_zones(zp)  # read_zones falls back to the .json.gz sibling (deploy bundle)
            if "lungs" not in masks and "right_lung" in masks and "left_lung" in masks:
                masks["lungs"] = masks["right_lung"] | masks["left_lung"]
            return masks, meta
        z = approximate_zones(case.width, case.height)
        return z, {
            "case_id": case_id,
            "width": case.width,
            "height": case.height,
            "approximate": True,
            "midline_x": case.width / 2,
        }


def dilate(mask: np.ndarray, radius_px: int) -> np.ndarray:
    r = max(0, int(round(radius_px)))
    if r == 0:
        return mask.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(mask.astype(np.uint8), k) > 0


_REPOS: dict[Path, CaseRepository] = {}


def get_repo(root: Path | None = None) -> CaseRepository:
    r = Path(root) if root else processed_root()
    if r not in _REPOS:
        _REPOS[r] = CaseRepository(r)
    return _REPOS[r]


def reset_repos() -> None:
    _REPOS.clear()
