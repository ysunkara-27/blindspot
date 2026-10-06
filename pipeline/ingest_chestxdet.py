"""Ingest ChestX-Det (HF mirror `MedOtter/ChestX-Det`) into the canonical Case schema (SPEC §3.2).

Run:  uv run python -m pipeline.ingest_chestxdet [--limit N] [--workers K] [--force]

Outputs (all under data/processed/, gitignored):
  images/cxd_<image_id>.png      8-bit L, 1024x1024
  masks/cxd_<image_id>_F<n>.png  0/255 instance masks (mask_path is relative to data/processed/)
  cases.jsonl                    one shared.contracts.Case per line, sorted by case_id
  taxonomy_report.json           raw syms -> canonical labels, counts
  ingest_stats.json              counts by label, normals, instances/case, areas, flags, cross-checks

Resumable: images and masks already on disk are not rewritten (use --force to rewrite).
Idempotent: the same input produces byte-identical cases.jsonl. If data/processed/splits.json exists,
its split assignment is re-applied so a re-ingest does not reset splits.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pyarrow.parquet as pq
import yaml
from PIL import Image

from shared.contracts import Case, Finding, Geometry

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BLINDSPOT_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw" / "chestxdet"
OUT_DIR = DATA_DIR / "processed"
TAXONOMY_PATH = REPO_ROOT / "config" / "taxonomy.yaml"

HF_REPO = "MedOtter/ChestX-Det"
SOURCE = "chestx-det"
SIZE = 1024
MERGE_IOU = 0.6
LICENSE_TAG = "NIH ChestX-ray14 images (attribution required) / ChestX-Det annotations Apache-2.0"
ATTRIBUTION = (
    "Images: NIH Clinical Center ChestX-ray14 (https://nihcc.app.box.com/v/ChestXray-NIHCC; "
    "Wang et al., CVPR 2017). Annotations: ChestX-Det by Deepwise AI Lab (Lian et al., IEEE TMI 2021)."
)

# qa flags. EXCLUDING flags drop the case from cases.jsonl; the others are informational.
FLAG_MASK_FROM_BBOX = "mask_from_bbox"
FLAG_NEG_MISMATCH = "negative_flag_mismatch"
FLAG_MERGED = "merged_duplicate_instances"
FLAG_RESIZED = "resized_to_1024"
FLAG_POLY_CLIPPED = "polygon_clipped"
FLAG_INSTANCE_DROPPED = "instance_dropped_empty"
EXCLUDING_FLAGS = {FLAG_NEG_MISMATCH}

# fields that M2 (vision-ml) fills in cases.jsonl; ingest refuses to clobber them without --force
M2_CASE_FIELDS = ("anatomy_path", "zones_path", "cardiothoracic_ratio")


class UnmappedLabelError(ValueError):
    """A source label has no entry in config/taxonomy.yaml. Never guess — fix the taxonomy."""


# --------------------------------------------------------------------------- taxonomy
def norm_label(s: str) -> str:
    """Case- and whitespace-insensitive key: 'Pleural  thickening ' -> 'pleural thickening'."""
    return " ".join(str(s).split()).casefold()


@dataclass(frozen=True)
class LabelInfo:
    label: str
    kind: str


def load_taxonomy(path: Path = TAXONOMY_PATH, source: str = SOURCE) -> dict[str, LabelInfo]:
    """normalized source string -> (canonical id, kind). Fails on a source string mapped twice."""
    cfg = yaml.safe_load(Path(path).read_text())
    table: dict[str, LabelInfo] = {}
    for entry in cfg["labels"]:
        for raw in (entry.get("sources") or {}).get(source, []) or []:
            key = norm_label(raw)
            info = LabelInfo(entry["id"], entry["kind"])
            if key in table and table[key] != info:
                raise ValueError(f"taxonomy: source label {raw!r} mapped to two ids: {table[key]} and {info}")
            table[key] = info
    if not table:
        raise ValueError(f"taxonomy: no labels for source {source!r} in {path}")
    return table


def map_syms(syms: Iterable[str], table: dict[str, LabelInfo]) -> dict[str, LabelInfo]:
    """Map every raw sym; raise UnmappedLabelError listing ALL unmapped values."""
    syms = set(syms)
    unmapped = sorted(s for s in syms if norm_label(s) not in table)
    if unmapped:
        raise UnmappedLabelError(
            f"unmapped ChestX-Det syms: {unmapped}. Add them to config/taxonomy.yaml "
            f"(orchestrator) — known: {sorted(table)}"
        )
    return {s: table[norm_label(s)] for s in syms}


# --------------------------------------------------------------------------- annotations
@dataclass
class RawInstance:
    sym: str
    box: tuple[float, float, float, float] | None
    polygon: list[tuple[float, float]] | None


def parse_annotation(annotation_json: str | dict) -> list[RawInstance]:
    """Zip syms/boxes/polygons into instances. Length mismatches raise (malformed source)."""
    ann = json.loads(annotation_json) if isinstance(annotation_json, str) else annotation_json
    syms = list(ann.get("syms") or [])
    boxes = list(ann.get("boxes") or [])
    polys = ann.get("polygons")
    polys = list(polys) if polys is not None else [None] * len(syms)
    if not (len(syms) == len(boxes) == len(polys)):
        raise ValueError(f"annotation length mismatch: syms={len(syms)} boxes={len(boxes)} polygons={len(polys)}")
    out = []
    for s, b, p in zip(syms, boxes, polys):
        box = tuple(float(v) for v in b) if b is not None and len(b) == 4 else None
        poly = [(float(pt[0]), float(pt[1])) for pt in p] if p else None
        out.append(RawInstance(sym=str(s), box=box, polygon=poly))  # type: ignore[arg-type]
    return out


# --------------------------------------------------------------------------- geometry
def clip_polygon(poly: list[tuple[float, float]], w: int, h: int) -> tuple[list[tuple[float, float]], bool]:
    """Clamp vertices into [0, w-1] x [0, h-1]; return (polygon, was_clipped)."""
    clipped = False
    out = []
    for x, y in poly:
        cx, cy = min(max(x, 0.0), w - 1.0), min(max(y, 0.0), h - 1.0)
        clipped |= (cx, cy) != (x, y)
        out.append((cx, cy))
    return out, clipped


def rasterize_polygon(poly: list[tuple[float, float]] | None, w: int, h: int) -> np.ndarray | None:
    """Filled polygon -> bool mask (h, w); None if invalid (< 3 vertices, non-finite, or zero pixels)."""
    if not poly or len(poly) < 3:
        return None
    arr = np.asarray(poly, dtype=np.float64)
    if not np.isfinite(arr).all():
        return None
    pts = np.round(arr).astype(np.int32).reshape(-1, 1, 2)
    centred = pts.reshape(-1, 2) - pts.reshape(-1, 2).mean(axis=0)
    if np.linalg.matrix_rank(centred.astype(np.float64)) < 2:  # collinear / repeated points -> invalid
        return None
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts], 255)
    return m > 0 if m.any() else None


def rasterize_box(box: tuple[float, float, float, float] | None, w: int, h: int) -> np.ndarray | None:
    if box is None or not np.isfinite(box).all():
        return None
    x0, y0, x1, y1 = box
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    xi0, yi0 = max(int(np.floor(x0)), 0), max(int(np.floor(y0)), 0)
    xi1, yi1 = min(int(np.ceil(x1)), w), min(int(np.ceil(y1)), h)
    if xi1 <= xi0 or yi1 <= yi0:
        return None
    m = np.zeros((h, w), bool)
    m[yi0:yi1, xi0:xi1] = True
    return m


def mask_bbox(m: np.ndarray) -> tuple[float, float, float, float]:
    """Half-open pixel bbox (x0, y0, x1, y1) of a non-empty mask."""
    ys, xs = np.nonzero(m)
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def mask_centroid(m: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(m)
    return float(xs.mean()), float(ys.mean())


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def largest_contour(m: np.ndarray) -> list[tuple[float, float]] | None:
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    return [(float(p[0][0]), float(p[0][1])) for p in c] if len(c) >= 3 else None


@dataclass
class Instance:
    label: str
    kind: str
    source_label: str
    mask: np.ndarray
    geom_kind: str  # "polygon" | "bbox"
    polygon: list[tuple[float, float]] | None
    flags: set[str] = field(default_factory=set)
    merged_from: int = 1


def build_instances(
    raws: list[RawInstance], mapping: dict[str, LabelInfo], w: int, h: int
) -> tuple[list[Instance], Counter]:
    """Rasterize each raw instance (polygon first, bbox fallback). Returns instances and event counts."""
    ev: Counter = Counter()
    out: list[Instance] = []
    for r in raws:
        info = mapping[r.sym]
        poly, clipped = clip_polygon(r.polygon, w, h) if r.polygon else (None, False)
        m = rasterize_polygon(poly, w, h)
        flags: set[str] = set()
        if m is not None:
            if clipped:
                flags.add(FLAG_POLY_CLIPPED)
                ev["polygon_clipped"] += 1
            out.append(Instance(info.label, info.kind, r.sym, m, "polygon", poly, flags))
            continue
        m = rasterize_box(r.box, w, h)
        if m is None:
            ev["instance_dropped_empty"] += 1
            continue
        ev["mask_from_bbox"] += 1
        out.append(Instance(info.label, info.kind, r.sym, m, "bbox", None, {FLAG_MASK_FROM_BBOX}))
    return out, ev


def merge_duplicates(insts: list[Instance], thr: float = MERGE_IOU) -> tuple[list[Instance], int]:
    """Union same-label instances with mask IoU > thr (transitively). Returns (instances, n_merged_away).

    Order is preserved by first occurrence. A merged instance keeps 'polygon' geometry if any member was
    a polygon; its polygon becomes the largest external contour of the union mask.
    """
    n = len(insts)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if insts[i].label == insts[j].label and mask_iou(insts[i].mask, insts[j].mask) > thr:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    out = []
    for root in sorted(groups):
        members = [insts[i] for i in groups[root]]
        if len(members) == 1:
            out.append(members[0])
            continue
        union = np.logical_or.reduce([m.mask for m in members])
        any_poly = any(m.geom_kind == "polygon" for m in members)
        flags = set().union(*(m.flags for m in members)) | {FLAG_MERGED}
        if any_poly:
            flags.discard(FLAG_MASK_FROM_BBOX)
        out.append(
            Instance(
                label=members[0].label,
                kind=members[0].kind,
                source_label=members[0].source_label,
                mask=union,
                geom_kind="polygon" if any_poly else "bbox",
                polygon=largest_contour(union) if any_poly else None,
                flags=flags,
                merged_from=len(members),
            )
        )
    return out, n - len(out)


def classify_normal(is_negative: bool, n_instances: int) -> tuple[bool, bool]:
    """(is_normal, mismatch). Normal only if the source says negative AND there are no instances."""
    is_normal = bool(is_negative) and n_instances == 0
    mismatch = bool(is_negative) != (n_instances == 0)
    return is_normal, mismatch


# --------------------------------------------------------------------------- images
def decode_image(img_bytes: bytes) -> tuple[np.ndarray, str, bytes | None]:
    """-> (uint8 L array, original PIL mode, original bytes if they are already a canonical L PNG)."""
    im = Image.open(io.BytesIO(img_bytes))
    mode, fmt = im.mode, im.format
    canonical = fmt == "PNG" and mode == "L" and im.size == (SIZE, SIZE)
    arr = np.asarray(im.convert("L"), dtype=np.uint8)
    return arr, mode, (img_bytes if canonical else None)


def resize_to_canonical(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    h, w = arr.shape
    if (w, h) == (SIZE, SIZE):
        return arr, 1.0, 1.0
    return cv2.resize(arr, (SIZE, SIZE), interpolation=cv2.INTER_AREA), SIZE / w, SIZE / h


def scale_raws(raws: list[RawInstance], sx: float, sy: float) -> list[RawInstance]:
    if sx == 1.0 and sy == 1.0:
        return raws
    return [
        RawInstance(
            r.sym,
            (r.box[0] * sx, r.box[1] * sy, r.box[2] * sx, r.box[3] * sy) if r.box else None,
            [(x * sx, y * sy) for x, y in r.polygon] if r.polygon else None,
        )
        for r in raws
    ]


def write_png_atomic(path: Path, arr: np.ndarray | None = None, raw: bytes | None = None) -> None:
    tmp = path.with_suffix(".tmp.png")
    if raw is not None:
        tmp.write_bytes(raw)
    else:
        if not cv2.imwrite(str(tmp), arr):
            raise OSError(f"cv2.imwrite failed for {path}")
    os.replace(tmp, path)


def png_ok(path: Path, expect: tuple[int, int] = (SIZE, SIZE)) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with Image.open(path) as im:
            return im.size == expect and im.mode == "L"
    except Exception:
        return False


# --------------------------------------------------------------------------- per-row conversion
MASK_COLUMNS = {  # label id -> per-class mask column (cross-check only)
    "pneumothorax": "pneumothorax_mask",
    "effusion": "effusion_mask",
    "consolidation": "consolidation_mask",
    "atelectasis": "atelectasis_mask",
    "nodule": "nodule_mask",
    "mass": "mass_mask",
    "calcification": "calcification_mask",
    "fracture": "fracture_mask",
    "pleural_thickening": "pleural_thickening_mask",
    "cardiomegaly": "cardiomegaly_mask",
    "emphysema": "emphysema_mask",
    "fibrosis": "fibrosis_mask",
    "diffuse_nodule": "diffuse_nodule_mask",
}


def _image_bytes(v: Any) -> bytes | None:
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("bytes")
    return bytes(v)


def convert_row(row: dict[str, Any], mapping: dict[str, LabelInfo], out_dir: Path, force: bool = False) -> dict:
    """Convert one HF row. Returns {'case': Case|None, 'excluded': reason|None, 'stats': {...}}."""
    image_id = str(row["image_id"])
    case_id = f"cxd_{image_id}"
    arr, orig_mode, raw_png = decode_image(_image_bytes(row["image"]))
    arr, sx, sy = resize_to_canonical(arr)
    case_flags: set[str] = set()
    if (sx, sy) != (1.0, 1.0):
        case_flags.add(FLAG_RESIZED)
        raw_png = None
    raws = scale_raws(parse_annotation(row["annotation_json"]), sx, sy)
    insts, ev = build_instances(raws, mapping, SIZE, SIZE)
    n_raw = len(raws)
    if ev["instance_dropped_empty"]:
        case_flags.add(FLAG_INSTANCE_DROPPED)
    insts, n_merged = merge_duplicates(insts)
    ev["merged_away"] += n_merged

    is_normal, mismatch = classify_normal(bool(row["is_negative"]), len(insts))
    if mismatch:
        case_flags.add(FLAG_NEG_MISMATCH)

    # cross-check our union masks against the per-class mask columns (IoU per present label)
    xcheck: dict[str, float] = {}
    for label, col in MASK_COLUMNS.items():
        mine = [i.mask for i in insts if i.label == label]
        b = _image_bytes(row.get(col))
        if not mine and b is None:
            continue
        ref = (np.asarray(Image.open(io.BytesIO(b)).convert("L")) > 127) if b is not None else None
        if ref is not None and ref.shape != (SIZE, SIZE):
            ref = cv2.resize(ref.astype(np.uint8), (SIZE, SIZE), interpolation=cv2.INTER_NEAREST) > 0
        u = np.logical_or.reduce(mine) if mine else np.zeros((SIZE, SIZE), bool)
        xcheck[label] = mask_iou(u, ref) if ref is not None else 0.0

    stats = {
        "case_id": case_id,
        "source_split": str(row["split"]),
        "original_mode": orig_mode,
        "n_raw_instances": n_raw,
        "events": dict(ev),
        "xcheck": xcheck,
        "is_negative": bool(row["is_negative"]),
    }
    if case_flags & EXCLUDING_FLAGS:
        return {"case": None, "excluded": sorted(case_flags & EXCLUDING_FLAGS), "stats": stats}

    img_rel = f"images/{case_id}.png"
    img_path = out_dir / img_rel
    if force or not png_ok(img_path):
        write_png_atomic(img_path, arr=arr, raw=raw_png)

    findings: list[Finding] = []
    for n, inst in enumerate(insts, start=1):
        fid = f"{case_id}#F{n}"
        mask_rel = f"masks/{case_id}_F{n}.png"
        mpath = out_dir / mask_rel
        m8 = inst.mask.astype(np.uint8) * 255
        if force or not mpath.exists() or not _same_mask(mpath, inst.mask):
            write_png_atomic(mpath, arr=m8)
        case_flags |= inst.flags
        findings.append(
            Finding(
                finding_id=fid,
                label=inst.label,  # type: ignore[arg-type]
                source_label=inst.source_label,
                kind=inst.kind,  # type: ignore[arg-type]
                geometry=Geometry(
                    kind=inst.geom_kind,  # type: ignore[arg-type]
                    bbox=mask_bbox(inst.mask),
                    polygon=inst.polygon,
                    mask_path=mask_rel,
                ),
                centroid=mask_centroid(inst.mask),
                area_frac=float(inst.mask.sum() / (SIZE * SIZE)),
            )
        )
    case = Case(
        case_id=case_id,
        source=SOURCE,
        source_split=str(row["split"]),
        split="practice",
        image_path=img_rel,
        width=SIZE,
        height=SIZE,
        pixel_spacing_mm=None,
        is_normal=is_normal,
        findings=findings,
        license_tag=LICENSE_TAG,
        attribution=ATTRIBUTION,
        qa_flags=sorted(case_flags),
    )
    return {"case": case, "excluded": None, "stats": stats}


def _same_mask(path: Path, m: np.ndarray) -> bool:
    old = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return old is not None and old.shape == m.shape and np.array_equal(old > 127, m)


# --------------------------------------------------------------------------- source reading
READ_COLUMNS = ["image_id", "image", "annotation_json", "is_negative", *MASK_COLUMNS.values()]


def download(raw_dir: Path = RAW_DIR) -> list[Path]:
    """snapshot_download (skips files already present). Returns parquet shards; logs total size."""
    from huggingface_hub import snapshot_download

    raw_dir.mkdir(parents=True, exist_ok=True)
    t = time.time()
    snapshot_download(repo_id=HF_REPO, repo_type="dataset", local_dir=str(raw_dir))
    shards = sorted((raw_dir / "data").glob("*.parquet"))
    total = sum(p.stat().st_size for p in shards)
    log(
        f"download: {len(shards)} parquet shards, {total / 1e9:.3f} GB ({total} bytes) "
        f"in {raw_dir} [{time.time() - t:.0f}s]"
    )
    if not shards:
        raise RuntimeError(f"no parquet shards under {raw_dir}/data — HF mirror malformed? see SPEC §3.1 fallbacks")
    return shards


def shard_split(p: Path) -> str:
    return p.name.split("-", 1)[0]


def iter_rows(shards: list[Path], columns: list[str], limit: int | None = None) -> Iterator[dict]:
    n = 0
    for p in shards:
        pf = pq.ParquetFile(p)
        cols = [c for c in columns if c in pf.schema_arrow.names]
        for batch in pf.iter_batches(batch_size=32, columns=cols):
            for row in batch.to_pylist():
                row["split"] = shard_split(p)
                yield row
                n += 1
                if limit is not None and n >= limit:
                    return


def collect_syms(shards: list[Path], limit: int | None = None) -> Counter:
    c: Counter = Counter()
    for row in iter_rows(shards, ["annotation_json"], limit):
        for r in parse_annotation(row["annotation_json"]):
            c[r.sym] += 1
    return c


# --------------------------------------------------------------------------- worker plumbing
_W: dict[str, Any] = {}


def _init_worker(mapping: dict[str, LabelInfo], out_dir: str, force: bool) -> None:
    cv2.setNumThreads(1)
    _W.update(mapping=mapping, out_dir=Path(out_dir), force=force)


def _work(row: dict) -> dict:
    res = convert_row(row, _W["mapping"], _W["out_dir"], _W["force"])
    res["case"] = res["case"].model_dump_json() if res["case"] is not None else None
    return res


# --------------------------------------------------------------------------- stats
def quantiles(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {}
    a = np.asarray(xs)
    return {f"p{q}": float(np.percentile(a, q)) for q in (0, 5, 25, 50, 75, 95, 100)} | {"n": len(xs)}


def build_stats(cases: list[Case], results: list[dict], download_bytes: int, sym_counts: Counter) -> dict:
    per_label = Counter()
    per_label_images = Counter()
    per_label_area: dict[str, list[float]] = defaultdict(list)
    geom = Counter()
    for c in cases:
        for f in c.findings:
            per_label[f.label] += 1
            per_label_area[f.label].append(f.area_frac)
            geom[f.geometry.kind] += 1
        for lab in {f.label for f in c.findings}:
            per_label_images[lab] += 1
    flags = Counter(fl for c in cases for fl in c.qa_flags)
    events = Counter()
    for r in results:
        events.update(r["stats"]["events"])
    excluded = [{"case_id": r["stats"]["case_id"], "reasons": r["excluded"]} for r in results if r["excluded"]]
    xc: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for lab, v in r["stats"]["xcheck"].items():
            xc[lab].append(v)
    n_inst = sum(per_label.values())
    return {
        "source": HF_REPO,
        "download_bytes": download_bytes,
        "rows_read": len(results),
        "cases_written": len(cases),
        "excluded": excluded,
        "by_source_split": dict(Counter(c.source_split for c in cases)),
        "normals": sum(c.is_normal for c in cases),
        "abnormal": sum(not c.is_normal for c in cases),
        "normals_by_source_split": dict(Counter(c.source_split for c in cases if c.is_normal)),
        "raw_instances": sum(r["stats"]["n_raw_instances"] for r in results),
        "instances": n_inst,
        "instances_by_label": dict(per_label.most_common()),
        "images_by_label": dict(per_label_images.most_common()),
        "instances_by_kind": dict(Counter(f.kind for c in cases for f in c.findings)),
        "geometry_kind": dict(geom),
        "polygon_fraction": (geom["polygon"] / n_inst) if n_inst else 0.0,
        "instances_per_case": dict(sorted(Counter(len(c.findings) for c in cases).items())),
        "area_frac_all": quantiles([f.area_frac for c in cases for f in c.findings]),
        "area_frac_by_label": {k: quantiles(v) for k, v in sorted(per_label_area.items())},
        "events": dict(events),
        "qa_flags": dict(flags),
        "original_mode": dict(Counter(r["stats"]["original_mode"] for r in results)),
        "raw_sym_counts": dict(sym_counts.most_common()),
        "xcheck_note": "IoU of our per-label instance-mask union vs the HF per-class mask column. Values < 1 come "
        "from the mirror's class masks being filled even-odd: where two same-class instances overlap, the column "
        "has a hole (verified: parity-of-instances matches the column at IoU > 0.96). Instance masks are correct; "
        "never use the class-mask columns as ground truth.",
        "xcheck_iou_vs_class_masks": {
            k: {"mean": float(np.mean(v)), "min": float(np.min(v)), "n_below_0.9": int(sum(x < 0.9 for x in v))}
            for k, v in sorted(xc.items())
        },
    }


def build_taxonomy_report(sym_counts: Counter, mapping: dict[str, LabelInfo], cases: list[Case]) -> dict:
    return {
        "source": SOURCE,
        "taxonomy": str(TAXONOMY_PATH.relative_to(REPO_ROOT)),
        "unique_syms": sorted(sym_counts),
        "mapping": {
            s: {"label": mapping[s].label, "kind": mapping[s].kind, "raw_instances": sym_counts[s]}
            for s in sorted(sym_counts)
        },
        "unmapped": [],
        "canonical_instances_after_merge": dict(Counter(f.label for c in cases for f in c.findings).most_common()),
    }


# --------------------------------------------------------------------------- main
def log(msg: str) -> None:
    print(f"[ingest {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_existing_splits(out_dir: Path) -> dict[str, str]:
    p = out_dir / "splits.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {cid: name for name, ids in data["splits"].items() for cid in ids}


def guard_m2_fields(out_dir: Path, force: bool) -> None:
    p = out_dir / "cases.jsonl"
    if force or not p.exists():
        return
    with p.open() as fh:
        for line in fh:
            d = json.loads(line)
            if any(d.get(k) for k in M2_CASE_FIELDS) or d.get("difficulty_prior"):
                raise SystemExit(
                    "cases.jsonl already carries M2 fields (anatomy/zones/difficulty). Re-ingesting would erase "
                    "them; rerun with --force and then rerun `make anatomy features`."
                )


def run(limit: int | None, workers: int, force: bool, out_dir: Path = OUT_DIR, raw_dir: Path = RAW_DIR) -> dict:
    t0 = time.time()
    guard_m2_fields(out_dir, force)
    shards = download(raw_dir)
    download_bytes = sum(p.stat().st_size for p in shards)

    sym_counts = collect_syms(shards, limit)
    log(
        f"unique syms BEFORE mapping ({len(sym_counts)}): "
        + ", ".join(f"{s!r}={n}" for s, n in sorted(sym_counts.items()))
    )
    table = load_taxonomy()
    mapping = map_syms(sym_counts, table)  # raises UnmappedLabelError
    for s in sorted(mapping):
        log(f"  map {s!r:24} -> {mapping[s].label} ({mapping[s].kind})")

    for d in ("images", "masks"):
        (out_dir / d).mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    rows = iter_rows(shards, READ_COLUMNS, limit)
    if workers <= 1:
        _init_worker(mapping, str(out_dir), force)
        it: Iterable[dict] = map(_work, rows)
        results = _drain(it)
    else:
        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(mapping, str(out_dir), force)) as ex:
            results = _drain(ex.map(_work, rows, chunksize=4))

    cases = sorted((Case.model_validate_json(r["case"]) for r in results if r["case"]), key=lambda c: c.case_id)
    if len({c.case_id for c in cases}) != len(cases):
        raise RuntimeError("duplicate case_id in source")
    prev = load_existing_splits(out_dir)
    if prev:
        cases = [c.model_copy(update={"split": prev.get(c.case_id, c.split)}) for c in cases]
        log(f"re-applied existing splits.json to {sum(c.case_id in prev for c in cases)} cases")

    # orphan masks (e.g. after a merge-rule change) are removed so masks/ mirrors cases.jsonl exactly
    if limit is None:
        referenced = {f.geometry.mask_path.split("/", 1)[1] for c in cases for f in c.findings if f.geometry.mask_path}
        orphans = [p for p in (out_dir / "masks").glob("*.png") if p.name not in referenced]
        for p in orphans:
            p.unlink()
        if orphans:
            log(f"removed {len(orphans)} orphan mask files")

    tmp = out_dir / "cases.jsonl.tmp"
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in cases))
    os.replace(tmp, out_dir / "cases.jsonl")
    stats = build_stats(cases, results, download_bytes, sym_counts)
    stats["limit"] = limit
    stats["elapsed_s"] = round(time.time() - t0, 1)
    (out_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    (out_dir / "taxonomy_report.json").write_text(
        json.dumps(build_taxonomy_report(sym_counts, mapping, cases), indent=2) + "\n"
    )
    log(
        f"wrote {len(cases)} cases ({stats['normals']} normal, {stats['abnormal']} abnormal), "
        f"{stats['instances']} instances (raw {stats['raw_instances']}, "
        f"merged away {stats['events'].get('merged_away', 0)}), "
        f"polygon fraction {stats['polygon_fraction']:.4f}, excluded {len(stats['excluded'])}, "
        f"flags {stats['qa_flags']} in {stats['elapsed_s']}s"
    )
    return stats


def _drain(it: Iterable[dict]) -> list[dict]:
    out = []
    t = time.time()
    for i, r in enumerate(it, start=1):
        out.append(r)
        if i % 250 == 0:
            log(f"converted {i} rows ({i / (time.time() - t):.1f} rows/s)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=None, help="process only the first N rows (dev)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--force", action="store_true", help="rewrite images/masks; allow clobbering M2 fields")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--raw", type=Path, default=RAW_DIR)
    a = ap.parse_args(argv)
    try:
        run(a.limit, a.workers, a.force, a.out, a.raw)
    except UnmappedLabelError as e:
        log(f"FATAL: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
