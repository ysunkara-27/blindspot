"""Case repository: cases*.jsonl + masks + zones (+ CT/MR volumes), loaded lazily with LRU caches.

Root = BLINDSPOT_PROCESSED_DIR if set, else settings.processed_dir (data/processed). Paths inside the case files
(image_path, mask_path, zones_path, volume.data_path, volume.mask_path) are relative to the root.

Every `cases*.jsonl` in the root is loaded: `cases.jsonl` first (the X-ray set, so its order — and therefore the
seeded selection of X-ray sessions — is unchanged), then the others sorted by name (e.g. `cases_msd.jsonl`).
Volumetric cases carry `volume` (docs/VOLUMETRIC_PLAN.md): `volumes/<id>.i16.gz` int16 little-endian (z, y, x) and
`masks/<id>.u8.gz` uint8 label values. Decoded arrays are cached in a small LRU (VOLUME_CACHE volumes each).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy import ndimage

from backend.app.settings import get_settings
from shared.contracts import VOLUME_LABELS, Case, Finding, Provenance
from shared.rle import read_zones

log = logging.getLogger("blindspot.cases")
VOLUME_CACHE = 8  # decoded volumes / label volumes kept in memory (≤ 8 each)
MIDLINE_FRAC = 0.1  # zones3d rule: midline band half-width as a fraction of nx (pipeline default)
ORGAN_DILATION_MM = 5.0  # zones3d rule: organ zones are the organ mask dilated by this much per axis, holes filled
SLAB_THIRDS = ("superior_slab", "mid_slab", "inferior_slab")


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
        self.volume = lru_cache(maxsize=VOLUME_CACHE)(self._volume)  # type: ignore[method-assign]
        self.maskvol = lru_cache(maxsize=VOLUME_CACHE)(self._maskvol)  # type: ignore[method-assign]
        self.finding_volmask = lru_cache(maxsize=64)(self._finding_volmask)  # type: ignore[method-assign]
        self.volume_zones = lru_cache(maxsize=VOLUME_CACHE)(self._volume_zones)  # type: ignore[method-assign]

    # ------------------------------------------------------------------ cases
    def case_files(self) -> list[Path]:
        """`cases.jsonl` first, then every other `cases*.jsonl` sorted by name."""
        files = sorted(p for p in self.root.glob("cases*.jsonl") if p.is_file())
        first = [p for p in files if p.name == "cases.jsonl"]
        return first + [p for p in files if p.name != "cases.jsonl"]

    def _load(self) -> dict[str, Case]:
        if self._cases is None:
            out: dict[str, Case] = {}
            for p in self.case_files():
                for line in p.read_text().splitlines():
                    if line.strip():
                        c = stamp_provenance(Case.model_validate_json(line))
                        if c.case_id in out:
                            log.warning("duplicate case id %s in %s; first definition kept", c.case_id, p.name)
                            continue
                        out[c.case_id] = c
            self._cases = out
        return self._cases

    def count(self) -> int:
        return len(self._load())

    def all(self) -> list[Case]:
        return list(self._load().values())

    def get(self, case_id: str) -> Case | None:
        return self._load().get(case_id)

    def by_split(self, split: str, modality: str | None = None) -> list[Case]:
        return [c for c in self._load().values() if c.split == split and (modality is None or c.modality == modality)]

    def by_modality(self, modality: str) -> list[Case]:
        return [c for c in self._load().values() if c.modality == modality]

    def count_by_modality(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self._load().values():
            out[c.modality] = out.get(c.modality, 0) + 1
        return out

    def modalities(self) -> list[str]:
        """Modalities with at least one case, in contract order (cxr, ct, mr)."""
        have = self.count_by_modality()
        return [m for m in ("cxr", "ct", "mr") if have.get(m)]

    def image_path(self, case: Case) -> Path:
        return self.root / case.image_path

    # ------------------------------------------------------------------ volumes (CT / MR)
    def volume_path(self, case: Case) -> Path | None:
        return self.root / case.volume.data_path if case.volume else None

    def maskvol_path(self, case: Case) -> Path | None:
        return self.root / case.volume.mask_path if case.volume else None

    def _volume(self, case_id: str) -> np.ndarray | None:
        """Decoded int16 volume (z, y, x), or None when the case is not volumetric or the file is missing."""
        case = self.get(case_id)
        p = self.volume_path(case) if case else None
        if case is None or case.volume is None or p is None or not p.exists():
            return None
        return read_gz_array(p, "<i2", tuple(case.volume.shape))

    def _maskvol(self, case_id: str) -> np.ndarray | None:
        """Decoded uint8 label volume (z, y, x). GROUND TRUTH: served only after submit (routes.attempts.maskvol)."""
        case = self.get(case_id)
        p = self.maskvol_path(case) if case else None
        if case is None or case.volume is None or p is None or not p.exists():
            return None
        return read_gz_array(p, np.uint8, tuple(case.volume.shape))

    def _finding_volmask(self, case_id: str, finding_id: str) -> np.ndarray | None:
        """Boolean (z, y, x) mask of ONE finding: the connected component(s) of its label values that belong to it.
        Several findings may share a label value (two liver tumours are both value 2), so the component is chosen
        by the finding's centroid3, else by overlap with its box (bbox × slice_range)."""
        case = self.get(case_id)
        f = self.finding(case, finding_id) if case else None
        mv = self.maskvol(case_id)
        if case is None or f is None or mv is None:
            return None
        return finding_component(mv, f)

    def _volume_zones(self, case_id: str) -> dict[str, np.ndarray]:
        case = self.get(case_id)
        if case is None or case.volume is None:
            return {}
        mv = self.maskvol(case_id)
        return volume_zones(case, mv, self.root)

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


# Case.source → config/provenance.yaml `datasets` key, for cases written before the provenance block existed.
PROVENANCE_BY_SOURCE = {"chestx-det": "chestx-det"}


def stamp_provenance(case: Case) -> Case:
    """Read-time provenance for a case whose file lacks the block (X-ray cases.jsonl): the config entry for its source.
    cases.jsonl is never rewritten; synthetic cases get no badge."""
    if case.provenance is not None:
        return case
    key = PROVENANCE_BY_SOURCE.get(case.source)
    if key is None:
        return case
    from backend.app import config  # local: config is cheap but not needed for volumes-only callers

    d = (config.provenance().get("datasets") or {}).get(key)
    if not isinstance(d, dict):
        return case
    try:
        prov = Provenance.model_validate({k: v for k, v in d.items() if k in Provenance.model_fields})
    except ValueError:
        return case
    return case.model_copy(update={"provenance": prov})


def read_gz_array(path: Path, dtype: Any, shape: tuple[int, ...]) -> np.ndarray:
    with gzip.open(path, "rb") as fh:
        raw = fh.read()
    arr = np.frombuffer(raw, dtype=dtype)
    n = int(np.prod(shape))
    if arr.size != n:
        raise ValueError(f"{path.name}: {arr.size} values, expected {n} for shape {shape}")
    return arr.reshape(shape)


def finding_box(f: Finding, shape: tuple[int, int, int]) -> tuple[int, int, int, int, int, int]:
    """Integer voxel box (z0, z1, y0, y1, x0, x1), end-exclusive, clipped to the volume."""
    nz, ny, nx = shape
    x0, y0, x1, y1 = f.geometry.bbox
    z0, z1 = f.slice_range if f.slice_range else (0, nz - 1)
    return (
        max(0, int(z0)),
        min(nz, int(z1) + 1),
        max(0, int(y0)),
        min(ny, int(np.ceil(y1))),
        max(0, int(x0)),
        min(nx, int(np.ceil(x1))),
    )


def finding_values(f: Finding) -> list[int]:
    if f.label_values:
        return [int(v) for v in f.label_values]
    return [int(f.label_value)] if f.label_value is not None else []


def finding_component(mv: np.ndarray, f: Finding) -> np.ndarray:
    """Voxels of `f`: among the connected components of its label values, the one holding its centroid3, else
    those overlapping its box; a finding without values gets its box."""
    vals = finding_values(f)
    if not vals:
        out = np.zeros(mv.shape, bool)
        z0, z1, y0, y1, x0, x1 = finding_box(f, mv.shape)  # type: ignore[arg-type]
        out[z0:z1, y0:y1, x0:x1] = True
        return out
    sel = np.isin(mv, vals)
    labelled, n = ndimage.label(sel)
    if n <= 1:
        return sel
    if f.centroid3 is not None:
        cx, cy, cz = (int(round(v)) for v in f.centroid3)
        if 0 <= cz < mv.shape[0] and 0 <= cy < mv.shape[1] and 0 <= cx < mv.shape[2] and labelled[cz, cy, cx]:
            return labelled == labelled[cz, cy, cx]
    z0, z1, y0, y1, x0, x1 = finding_box(f, mv.shape)  # type: ignore[arg-type]
    inside = labelled[z0:z1, y0:y1, x0:x1]
    ids = [int(i) for i in np.unique(inside) if i]
    if not ids:
        return sel
    best = max(ids, key=lambda i: int((inside == i).sum()))
    return labelled == best


def anatomy_zone_values(case: Case) -> dict[str, list[int]]:
    """Label values of the mask that are ANATOMY (organs → zones), i.e. not finding labels: {zone_id: [values]}."""
    out: dict[str, list[int]] = {}
    if case.volume is None:
        return out
    finding_vals = {v for f in case.findings for v in finding_values(f)}
    for val, name in case.volume.labels.items():
        try:
            v = int(val)
        except ValueError:
            continue
        if name in VOLUME_LABELS or v in finding_vals:
            continue
        out.setdefault(name, []).append(v)
    return out


def slab_zones(shape: tuple[int, int, int], midline_frac: float = MIDLINE_FRAC) -> dict[str, np.ndarray]:
    """Thirds along z (slice 0 = most superior: superior = [0, nz//3), mid = [nz//3, nz - nz//3), inferior = the rest)
    and halves across x (patient RIGHT = low x, displayed on the left; midline band = |x − (nx−1)/2| ≤ midline_frac·nx).
    The same rules as the pipeline's zones3d files."""
    nz, ny, nx = shape
    z = np.arange(nz)[:, None, None]
    x = np.arange(nx)[None, None, :]
    ones = np.ones(shape, bool)
    third = nz // 3
    band = np.abs(x - (nx - 1) / 2) <= midline_frac * nx
    return {
        "superior_slab": ones & (z < third),
        "mid_slab": ones & (z >= third) & (z < nz - third),
        "inferior_slab": ones & (z >= nz - third),
        "right_half": ones & (x < (nx - 1) / 2) & ~band,
        "left_half": ones & (x > (nx - 1) / 2) & ~band,
        "midline_volume": ones & band,
    }


def organ_zone(mv: np.ndarray, values: list[int], spacing: tuple[float, ...], dilation_mm: float) -> np.ndarray:
    """Organ mask values, dilated by `dilation_mm` per axis (voxels = mm / spacing), holes filled."""
    m = np.isin(mv, values)
    if dilation_mm > 0 and m.any():
        r = [max(0, int(round(dilation_mm / float(s)))) for s in spacing]
        st = np.ones((2 * r[0] + 1, 2 * r[1] + 1, 2 * r[2] + 1), bool)
        m = ndimage.binary_dilation(m, structure=st)
    return ndimage.binary_fill_holes(m) if m.any() else m


def _zones3d_zone(
    spec: Any, mv: np.ndarray | None, base: dict[str, np.ndarray], spacing, dil: float
) -> np.ndarray | None:
    """One zones3d entry: [label values] | "slab:<superior|mid|inferior>" | "half:<right|left|midline>" |
    {"label_values": [...]} | {"box": [x0, y0, z0, x1, y1, z1]} (end-exclusive)."""
    if isinstance(spec, list):
        return organ_zone(mv, [int(v) for v in spec], spacing, dil) if mv is not None else None
    if isinstance(spec, str):
        kind, _, which = spec.partition(":")
        if kind == "slab":
            return base.get(f"{which}_slab")
        if kind == "half":
            return base.get("midline_volume" if which == "midline" else f"{which}_half")
        return None
    if isinstance(spec, dict):
        if mv is not None and isinstance(spec.get("label_values"), list):
            return organ_zone(mv, [int(v) for v in spec["label_values"]], spacing, dil)
        if isinstance(spec.get("box"), list) and len(spec["box"]) == 6:
            x0, y0, z0, x1, y1, z1 = (int(v) for v in spec["box"])
            m = np.zeros(next(iter(base.values())).shape, bool)
            m[max(0, z0) : z1, max(0, y0) : y1, max(0, x0) : x1] = True
            return m
    return None


def volume_zones(case: Case, mv: np.ndarray | None, root: Path | None = None) -> dict[str, np.ndarray]:
    """Zones of a volumetric case as boolean (z, y, x) masks. From `zones3d/<case_id>.json` when the pipeline wrote one
    (VOLUMETRIC ZONES FILE in docs/PROGRESS.md: {"zones": {id: [values] | "slab:…" | "half:…"}, "rules":
    {"organ_dilation_mm", "midline_frac"}}), else derived here: organ zones from the anatomy label values of the mask,
    slab thirds/halves from the shape, brain hemispheres as halves."""
    if case.volume is None:
        return {}
    shape = tuple(int(n) for n in case.volume.shape)
    spacing = tuple(float(s) for s in case.volume.spacing)
    doc: dict[str, Any] = {}
    p = root / "zones3d" / f"{case.case_id}.json" if root else None
    if p is not None and p.exists():
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            log.warning("zones3d for %s unreadable: %s", case.case_id, e)
            doc = {}
    rules = doc.get("rules") if isinstance(doc.get("rules"), dict) else {}
    frac = float(rules.get("midline_frac", MIDLINE_FRAC))
    dil = float(rules.get("organ_dilation_mm", ORGAN_DILATION_MM))
    zones = slab_zones(shape, frac)  # type: ignore[arg-type]
    if case.body_region == "brain":
        zones["brain_right"] = zones["right_half"]
        zones["brain_left"] = zones["left_half"]
        zones["brain_midline"] = zones["midline_volume"]
    specs = doc.get("zones") if isinstance(doc.get("zones"), dict) else None
    if specs:
        for zone, spec in specs.items():
            m = _zones3d_zone(spec, mv, zones, spacing, dil)
            if m is not None and m.shape == shape:
                zones[zone] = m
    elif mv is not None:
        for zone, vals in anatomy_zone_values(case).items():
            zones[zone] = organ_zone(mv, vals, spacing, dil)
    return zones


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
