"""Medical Segmentation Decathlon adapter: task table, selective fetch, NIfTI loading in our (z,y,x) convention.

Run:  uv run python -m pipeline.volumetric.msd --task Task07_Pancreas --limit 30
      (fetches dataset.json, the labels of the first 2×limit training cases by id, then the images of the
       `limit` cases whose label has a lesion — ~1 GB per task instead of the 7–12 GB tar)

Raw layout (data/raw/msd/<Task>/): dataset.json, labelsTr/<case>.nii.gz, imagesTr/<case>.nii.gz. Resumable.
Label values: lesions from config/taxonomy.yaml `sources.msd` ("Task07_Pancreas:2", "Task01_BrainTumour:1+2+3"
= one finding from the union); anatomy from `anatomy_labels` (zones, never findings).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import nibabel as nib
import numpy as np
import yaml

from pipeline.volumetric import tarindex
from pipeline.volumetric.geometry import nifti_to_zyx

log = logging.getLogger("volumetric.msd")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("BLINDSPOT_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw" / "msd"
TAXONOMY_PATH = REPO_ROOT / "config" / "taxonomy.yaml"
PROVENANCE_PATH = REPO_ROOT / "config" / "provenance.yaml"
MIRROR = os.environ.get("BLINDSPOT_MSD_MIRROR", "https://msd-for-monai.s3-us-west-2.amazonaws.com")

# Per-task presentation choices. (Candidates for config/volumetric.yaml — orchestrator-owned; kept here meanwhile.)
# `flip`: axes to mirror AFTER the header-driven reorientation, because some MSD headers are wrong. Verified on
# anatomy (docs/PROGRESS.md "orientation evidence"): Task07 displays the cardiac apex, descending aorta and stomach at
# image left and the liver at image right when the RAS header is trusted, i.e. its x axis is mirrored; Task08 (same
# site) shows the liver at image right in every volume (2/30 right-heavy by liver_side_score). Task01 (BraTS) matches
# its header on S/I and A/P (vertex → cerebellum, frontal lobes anterior); L/R is not checkable on a brain.
# `target_z_mm`: slices are decimated (every k-th, k = max(1, round(target / native spacing)); no interpolation) so a
# 32-slice slab covers a useful thickness; chosen per SOURCE volume, so lesion and lesion-free slabs of one scan match.
# `measure_values`: mask values the calipers go on (brain: core + enhancing, as a radiologist measures; the finding and
# its hit mask still cover oedema too).
TASK_TABLE: dict[str, dict] = {
    "Task07_Pancreas": {"short": "pan", "window": (50.0, 400.0), "side": 144, "flip": "x", "target_z_mm": 2.5},
    "Task08_HepaticVessel": {"short": "hep", "window": (80.0, 180.0), "side": 144, "flip": "x", "target_z_mm": 2.5},
    "Task03_Liver": {"short": "liv", "window": (80.0, 180.0), "side": 144, "target_z_mm": 2.5},
    "Task01_BrainTumour": {
        "short": "brain",
        "window": None,
        "side": 144,
        "sequence": "T1c",
        "target_z_mm": 2.0,
        "measure_values": (2, 3),
    },
    "Task06_Lung": {"short": "lung", "window": (-600.0, 1500.0), "side": 176, "target_z_mm": 2.5},
    "Task10_Colon": {"short": "colon", "window": (50.0, 400.0), "side": 144, "target_z_mm": 2.5},
}
SEQUENCE_PATTERNS = {"T1c": re.compile(r"t1\s*(gd|c|ce|post|contrast)|gad", re.I)}


@dataclass(frozen=True)
class TaskSpec:
    task: str
    short: str
    modality: str  # ct | mr
    body_region: str
    lesion_label: str  # taxonomy id, e.g. pancreatic_tumour
    lesion_values: tuple[int, ...]
    union: bool  # True → all lesion values form ONE finding (brain)
    anatomy: dict[int, str]  # mask value → zone id
    window: tuple[float, float] | None  # None → percentile window (MR)
    side: int
    sequence: str | None = None
    flip: str = ""  # subset of "xyz": axes mirrored after the header reorientation (anatomy-verified header fixes)
    target_z_mm: float = 2.5
    measure_values: tuple[int, ...] | None = None  # None → the finding's own values
    dataset_labels: dict[str, str] = field(default_factory=dict)
    dataset_modality: dict[str, str] = field(default_factory=dict)

    @property
    def mask_labels(self) -> dict[str, str]:
        out = {str(v): z for v, z in sorted(self.anatomy.items())}
        out.update({str(v): self.lesion_label for v in self.lesion_values})
        return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _parse_source(src: str) -> tuple[str, tuple[int, ...], bool]:
    task, _, vals = src.partition(":")
    if not vals:
        raise ValueError(f"taxonomy msd source without label values: {src!r}")
    union = "+" in vals
    values = tuple(int(v) for v in re.split(r"[+,]", vals))
    return task, values, union


def load_task_specs(taxonomy_path: Path = TAXONOMY_PATH) -> dict[str, TaskSpec]:
    cfg = yaml.safe_load(Path(taxonomy_path).read_text())
    anatomy = {t: {int(k): str(v) for k, v in m.items()} for t, m in (cfg.get("anatomy_labels") or {}).items()}
    specs: dict[str, TaskSpec] = {}
    for entry in cfg["labels"]:
        for src in (entry.get("sources") or {}).get("msd", []) or []:
            task, values, union = _parse_source(src)
            if task in specs:
                raise ValueError(f"taxonomy: task {task} mapped twice ({specs[task].lesion_label}, {entry['id']})")
            table = TASK_TABLE.get(task)
            if table is None:
                raise ValueError(f"no TASK_TABLE entry for {task}")
            specs[task] = TaskSpec(
                task=task,
                short=table["short"],
                modality=entry["modality"],
                body_region=entry["body_region"],
                lesion_label=entry["id"],
                lesion_values=values,
                union=union,
                anatomy=anatomy.get(task, {}),
                window=table["window"],
                side=table["side"],
                sequence=table.get("sequence"),
                flip=table.get("flip", ""),
                target_z_mm=float(table.get("target_z_mm", 2.5)),
                measure_values=table.get("measure_values"),
            )
    return specs


def load_provenance(task: str, path: Path = PROVENANCE_PATH) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())["datasets"]
    if task not in cfg:
        raise KeyError(f"config/provenance.yaml has no entry for {task}")
    return dict(cfg[task])


# --------------------------------------------------------------------------- dataset.json
def with_dataset_json(spec: TaskSpec, raw_dir: Path = RAW_DIR) -> TaskSpec:
    """Attach dataset.json labels/modality and resolve the MR channel index for `sequence`."""
    meta = json.loads((raw_dir / spec.task / "dataset.json").read_text())
    labels = {str(k): str(v) for k, v in (meta.get("labels") or {}).items()}
    modality = {str(k): str(v) for k, v in (meta.get("modality") or {}).items()}
    for v in spec.lesion_values:
        if str(v) not in labels:
            raise ValueError(f"{spec.task}: lesion value {v} not in dataset.json labels {labels}")
    for v in spec.anatomy:
        if str(v) not in labels:
            raise ValueError(f"{spec.task}: anatomy value {v} not in dataset.json labels {labels}")
    return TaskSpec(**{**spec.__dict__, "dataset_labels": labels, "dataset_modality": modality})


def channel_index(spec: TaskSpec) -> int | None:
    """Index of the requested sequence among dataset.json `modality` entries (4-D images only)."""
    if spec.sequence is None:
        return None
    pat = SEQUENCE_PATTERNS[spec.sequence]
    hits = [int(k) for k, name in spec.dataset_modality.items() if pat.search(name)]
    if len(hits) != 1:
        raise ValueError(f"{spec.task}: cannot resolve sequence {spec.sequence} in modality {spec.dataset_modality}")
    return hits[0]


# --------------------------------------------------------------------------- fetch
def task_url(task: str) -> str:
    return f"{MIRROR}/{task}.tar"


def case_name(member_name: str) -> str:
    return Path(member_name).name.removesuffix(".nii.gz")


def training_members(
    members: list[tarindex.Member], task: str
) -> tuple[dict[str, tarindex.Member], dict[str, tarindex.Member]]:
    """(images, labels) of imagesTr/labelsTr keyed by case name; AppleDouble members skipped."""
    images: dict[str, tarindex.Member] = {}
    labels: dict[str, tarindex.Member] = {}
    for m in members:
        if not m.is_file or m.is_appledouble or not m.name.endswith(".nii.gz"):
            continue
        parts = Path(m.name).parts
        if len(parts) < 3 or parts[-3] != task:
            continue
        if parts[-2] == "imagesTr":
            images[case_name(m.name)] = m
        elif parts[-2] == "labelsTr":
            labels[case_name(m.name)] = m
    return images, labels


def lesion_voxels(label_path: Path, values: tuple[int, ...]) -> int:
    arr = np.asanyarray(nib.load(str(label_path)).dataobj)
    return int(np.isin(arr, values).sum())


def fetch_task(
    task: str,
    limit: int,
    *,
    raw_dir: Path = RAW_DIR,
    candidates: int | None = None,
    workers: int = 3,
    min_lesion_voxels: int = 30,
) -> list[str]:
    """Index the tar, fetch dataset.json + candidate labels, pick `limit` cases with a lesion, fetch their images.
    Returns the chosen case names (sorted). Everything is skipped when already on disk."""
    specs = load_task_specs()
    if task not in specs:
        raise KeyError(f"{task}: not in config/taxonomy.yaml msd sources")
    spec = specs[task]
    url = task_url(task)
    out = raw_dir / task
    out.mkdir(parents=True, exist_ok=True)
    members = tarindex.index_remote_tar(url, raw_dir / f"{task}.index.json")
    by_name = {m.name: m for m in members}
    ds = by_name.get(f"{task}/dataset.json") or by_name.get(f"./{task}/dataset.json")
    if ds is None:
        raise FileNotFoundError(f"{task}/dataset.json not in the archive index")
    tarindex.fetch_member(url, ds, out / "dataset.json")
    images, labels = training_members(members, task)
    names = sorted(set(images) & set(labels))
    log.info("%s: %d training cases in the archive", task, len(names))
    n_cand = candidates or 2 * limit
    chosen: list[str] = []
    client = tarindex.RangeClient(url)
    try:
        for name in names[:n_cand]:
            dest = out / "labelsTr" / f"{name}.nii.gz"
            tarindex.fetch_member(url, labels[name], dest, client=client)
            n_les = lesion_voxels(dest, spec.lesion_values)
            if n_les >= min_lesion_voxels:
                chosen.append(name)
            else:
                log.info("%s: %s has %d lesion voxels (< %d), skipped", task, name, n_les, min_lesion_voxels)
            if len(chosen) >= limit:
                break
    finally:
        client.close()
    log.info("%s: fetching %d images (%.0f MB)", task, len(chosen), sum(images[n].size for n in chosen) / 1e6)
    t0 = time.time()

    def _one(name: str) -> None:
        tarindex.fetch_member(url, images[name], out / "imagesTr" / f"{name}.nii.gz")
        nib.load(str(out / "imagesTr" / f"{name}.nii.gz")).header  # verify it loads

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_one, chosen))
    log.info("%s: images ready in %.0f s", task, time.time() - t0)
    return sorted(chosen)


# --------------------------------------------------------------------------- loading
@dataclass
class RawVolume:
    name: str
    vol: np.ndarray  # (z,y,x) float32 (CT in HU)
    label: np.ndarray  # (z,y,x) uint8
    spacing: tuple[float, float, float]
    channel: int | None
    original_shape: tuple[int, int, int]
    z_stride: int = 1  # slices were decimated by this factor (spacing already multiplied)


def z_stride_for(native_sz: float, target_mm: float) -> int:
    return max(1, int(round(target_mm / max(native_sz, 1e-6))))


def decimate_z(arr: np.ndarray, stride: int) -> np.ndarray:
    return np.ascontiguousarray(arr[::stride]) if stride > 1 else arr


def apply_flips(arr: np.ndarray, flip: str) -> np.ndarray:
    """Mirror the (z,y,x) array along the named axes ("x" → patient left/right, "y" → anterior/posterior, "z")."""
    for ax in flip:
        if ax not in "xyz":
            raise ValueError(f"bad flip axis {ax!r}")
        arr = np.flip(arr, axis="zyx".index(ax))
    return np.ascontiguousarray(arr)


def load_case(spec: TaskSpec, name: str, raw_dir: Path = RAW_DIR) -> RawVolume:
    img = nib.load(str(raw_dir / spec.task / "imagesTr" / f"{name}.nii.gz"))
    lab = nib.load(str(raw_dir / spec.task / "labelsTr" / f"{name}.nii.gz"))
    ch = channel_index(spec) if img.ndim == 4 else None
    vol, spacing = nifti_to_zyx(img, channel=ch)
    label, lspacing = nifti_to_zyx(lab)
    vol, label = apply_flips(vol, spec.flip), apply_flips(label, spec.flip)
    if vol.shape != label.shape:
        raise ValueError(f"{name}: image {vol.shape} and label {label.shape} shapes differ")
    if not np.allclose(spacing, lspacing, rtol=1e-3):
        raise ValueError(f"{name}: image spacing {spacing} != label spacing {lspacing}")
    original_shape = tuple(int(s) for s in vol.shape)
    stride = z_stride_for(spacing[0], spec.target_z_mm)
    vol, label = decimate_z(vol, stride), decimate_z(label, stride)
    spacing = (spacing[0] * stride, spacing[1], spacing[2])
    return RawVolume(
        name=name,
        vol=vol.astype(np.float32),
        label=np.rint(label).astype(np.uint8),
        spacing=tuple(round(float(s), 5) for s in spacing),  # type: ignore[arg-type]
        channel=ch,
        original_shape=original_shape,  # type: ignore[arg-type]
        z_stride=stride,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fetch MSD cases selectively (ranged tar reads, never the whole tar)")
    ap.add_argument("--task", required=True)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--candidates", type=int, default=None, help="labels to inspect (default 2×limit)")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    chosen = fetch_task(args.task, args.limit, candidates=args.candidates, workers=args.workers)
    print(json.dumps({"task": args.task, "chosen": chosen}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
