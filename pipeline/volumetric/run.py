"""Build the volumetric case set end to end.

Run:  uv run python -m pipeline.volumetric.run --limit 30 \
          --tasks Task07_Pancreas,Task08_HepaticVessel,Task01_BrainTumour
      [--margin 6] [--vol-slices 32] [--vol-side N] [--no-fetch] [--force] [--normal-frac 0.4] [--bench 5]

Per task: fetch (selective ranged reads, resumable) → for each chosen volume build the lesion slab (findings) and,
for ~normal_frac of the cases, a lesion-free slab (is_normal, qa_flags lesion_free_slab) → write
data/processed/{volumes,masks,previews,zones3d}/… → data/processed/cases_msd.jsonl (every line validated as Case),
data/processed/volumetric_stats.json, data/qa/volumetric_contact_sheet.png. Logs: logs/volumetric_run.log.
Splits: `bench` for --bench lesion cases per task (reference bank, never served), `practice` for the rest.
No assessment forms for volumes yet.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from pipeline.volumetric import msd, pack
from pipeline.volumetric.build import (
    BuildOptions,
    Built,
    assign_difficulty,
    build_lesion_case,
    build_normal_case,
    liver_side_score,
)
from shared.contracts import Case

DATA_DIR = msd.DATA_DIR
OUT_DIR = DATA_DIR / "processed"
QA_DIR = DATA_DIR / "qa"
LOG_DIR = msd.REPO_ROOT / "logs"
SEED = 20261008
log = logging.getLogger("volumetric.run")


def case_number(name: str) -> int:
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 0


def write_built(b: Built, out_dir: Path, force: bool = False) -> int:
    c = b.case
    assert c.volume is not None
    vol_path, mask_path = out_dir / c.volume.data_path, out_dir / c.volume.mask_path
    nbytes = 0
    if force or not vol_path.exists():
        nbytes += pack.write_gz(vol_path, b.vol)
    else:
        nbytes += vol_path.stat().st_size
    if force or not mask_path.exists():
        nbytes += pack.write_gz(mask_path, b.mask)
    else:
        nbytes += mask_path.stat().st_size
    prev = out_dir / c.image_path
    prev.parent.mkdir(parents=True, exist_ok=True)
    import cv2

    cv2.imwrite(str(prev), b.preview)
    assert c.zones_path is not None
    pack.write_json(out_dir / c.zones_path, b.zones_doc)
    return nbytes


def verify_roundtrip(b: Built, out_dir: Path) -> None:
    c = b.case
    assert c.volume is not None
    v = pack.read_gz(out_dir / c.volume.data_path, "<i2", tuple(c.volume.shape))
    m = pack.read_gz(out_dir / c.volume.mask_path, "u1", tuple(c.volume.shape))
    if not np.array_equal(v, b.vol) or not np.array_equal(m, b.mask):
        raise AssertionError(f"{c.case_id}: pack round-trip mismatch")


def build_task(
    task: str, args: argparse.Namespace, out_dir: Path, raw_dir: Path
) -> tuple[list[Case], dict, list[tuple[str, np.ndarray]]]:
    spec = msd.with_dataset_json(msd.load_task_specs()[task], raw_dir)
    prov = msd.load_provenance(task)
    opts = BuildOptions(margin=args.margin, vol_slices=args.vol_slices, vol_side=args.vol_side)
    raw_task = raw_dir / task
    names = sorted(p.name.removesuffix(".nii.gz") for p in (raw_task / "imagesTr").glob("*.nii.gz"))
    names = [n for n in names if (raw_task / "labelsTr" / f"{n}.nii.gz").exists()][: args.limit]
    if not names:
        raise FileNotFoundError(f"{task}: no raw volumes under {raw_task} (run the fetch first)")
    rng = random.Random(f"{SEED}:{task}")
    bench_names = set(rng.sample(names, min(args.bench, len(names))))
    n_normals_target = int(round(args.normal_frac / (1 - args.normal_frac) * len(names)))
    normal_names = set(rng.sample(names, min(n_normals_target, len(names))))

    cases: list[Case] = []
    tiles: list[tuple[str, np.ndarray]] = []
    stats = Counter()
    measures: list[float] = []
    liver_scores: list[float] = []
    t0 = time.time()
    for i, name in enumerate(names):
        raw = msd.load_case(spec, name, raw_dir)
        cid = f"msd_{spec.short}_{case_number(name):04d}"
        split = "bench" if name in bench_names else "practice"
        b = build_lesion_case(spec, raw, cid, prov, opts, split=split)
        if b is None:
            log.warning("%s: %s → no usable lesion component, skipped", task, name)
            stats["skipped_no_lesion"] += 1
        else:
            stats["bytes"] += write_built(b, out_dir, args.force)
            verify_roundtrip(b, out_dir)
            cases.append(b.case)
            measures += [f.measure.long_mm for f in b.case.findings if f.measure]
            if spec.body_region == "abdomen":
                liver_scores.append(liver_side_score(b.vol))
            if len(tiles) < 12:
                f0 = b.case.findings[0]
                tiles.append(
                    (
                        f"{cid} {f0.measure.long_mm:.0f}mm z{f0.measure.slice}" if f0.measure else cid,
                        b.preview,
                    )
                )
            log.info(
                "%s %s: slab z%d–%d shape %s findings %d (%s) flags %s",
                task,
                cid,
                b.case.volume.crop_origin[0],  # type: ignore[index]
                b.case.volume.crop_origin[0] + b.case.volume.shape[0],  # type: ignore[index]
                b.case.volume.shape,  # type: ignore[union-attr]
                len(b.case.findings),
                ", ".join(f"{f.measure.long_mm:.0f}mm" for f in b.case.findings if f.measure),
                b.case.qa_flags,
            )
        if name in normal_names:
            nb = build_normal_case(spec, raw, f"{cid}n", prov, opts)
            if nb is None:
                log.info("%s: %s has no lesion-free slab ≥ %d slices with the organ", task, name, 12)
                stats["normal_unavailable"] += 1
            else:
                stats["bytes"] += write_built(nb, out_dir, args.force)
                verify_roundtrip(nb, out_dir)
                cases.append(nb.case)
                log.info(
                    "%s %sn: normal slab z%d–%d shape %s",
                    task,
                    cid,
                    nb.case.features["normal_slab_z0"],
                    nb.case.features["normal_slab_z1"],
                    nb.case.volume.shape,
                )  # type: ignore[union-attr]
        log.info("%s: %d/%d volumes done (%.0f s)", task, i + 1, len(names), time.time() - t0)
    cases = assign_difficulty(cases)
    lesion_cases = [c for c in cases if not c.is_normal]
    orientation = None
    if liver_scores:
        frac_ok = float(np.mean([s > 0.5 for s in liver_scores]))
        orientation = {
            "check": "liver-density voxels (40-200 HU) mostly in the patient-right half (low x)",
            "cases_right_heavy": int(sum(s > 0.5 for s in liver_scores)),
            "n": len(liver_scores),
            "mean_right_share": round(float(np.mean(liver_scores)), 3),
            "header_flip": spec.flip or None,
        }
        if frac_ok < 0.7:
            log.warning(
                "%s: ORIENTATION SUSPECT — only %.0f%% of cases have the dense liver on the patient's right",
                task,
                100 * frac_ok,
            )
    per_label = Counter(f.label for c in lesion_cases for f in c.findings)
    stats_doc = {
        "cases": len(cases),
        "lesion_cases": len(lesion_cases),
        "normals": sum(c.is_normal for c in cases),
        "bench": sum(c.split == "bench" for c in cases),
        "findings_per_label": dict(per_label),
        "findings_per_case": dict(Counter(len(c.findings) for c in lesion_cases)),
        "measure_mm": {
            "n": len(measures),
            "min": round(min(measures), 1) if measures else None,
            "p25": round(float(np.percentile(measures, 25)), 1) if measures else None,
            "median": round(float(np.median(measures)), 1) if measures else None,
            "p75": round(float(np.percentile(measures, 75)), 1) if measures else None,
            "max": round(max(measures), 1) if measures else None,
        },
        "bytes_packed": int(stats["bytes"]),
        "bytes_per_case_mean": int(stats["bytes"] / max(len(cases), 1)),
        "bytes_raw_downloaded": sum(p.stat().st_size for p in raw_task.rglob("*.nii.gz")),
        "skipped_no_lesion": int(stats["skipped_no_lesion"]),
        "normal_unavailable": int(stats["normal_unavailable"]),
        "qa_flags": dict(Counter(f for c in cases for f in c.qa_flags)),
        "sequence": spec.sequence,
        "orientation": orientation,
        "window": list(cases[0].volume.window.model_dump().values())
        if cases and spec.window
        else "percentile 1-99 per slab",
        "mask_labels": spec.mask_labels,
        "seconds": round(time.time() - t0, 1),
    }
    return cases, stats_doc, tiles


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MSD → Blindspot volumetric cases")
    ap.add_argument("--tasks", default="Task07_Pancreas,Task08_HepaticVessel,Task01_BrainTumour")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--margin", type=int, default=6)
    ap.add_argument("--vol-slices", type=int, default=32)
    ap.add_argument("--vol-side", type=int, default=None, help="in-plane side (default per task: 144, lung 176)")
    ap.add_argument("--normal-frac", type=float, default=0.4)
    ap.add_argument("--bench", type=int, default=5)
    ap.add_argument("--no-fetch", action="store_true", help="use what is already under data/raw/msd")
    ap.add_argument("--force", action="store_true", help="rewrite packed volumes that already exist")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--raw", type=Path, default=None, help="raw MSD dir (default data/raw/msd)")
    args = ap.parse_args(argv)
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "volumetric_run.log")],
    )
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    raw_dir = args.raw or msd.RAW_DIR
    all_cases: list[Case] = []
    stats: dict[str, dict] = {}
    sections: list[tuple[str, list[tuple[str, np.ndarray]]]] = []
    for task in tasks:
        if not args.no_fetch:
            msd.fetch_task(task, args.limit, raw_dir=raw_dir)
        cases, st, tiles = build_task(task, args, args.out, raw_dir)
        all_cases += cases
        stats[task] = st
        sections.append(
            (f"{task}  (axial, patient R on image left, anterior up; amber = lesion, blue = anatomy)", tiles)
        )
        log.info("%s: %s", task, json.dumps(st))
    all_cases.sort(key=lambda c: c.case_id)
    out_path = args.out / "cases_msd.jsonl"
    lines = [c.model_dump_json(exclude_none=True) for c in all_cases]
    for ln in lines:
        Case.model_validate_json(ln)
    ids = [c.case_id for c in all_cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    out_path.write_text("\n".join(lines) + "\n")
    (args.out / "volumetric_stats.json").write_text(json.dumps(stats, indent=2))
    pack.contact_sheet(sections, QA_DIR / "volumetric_contact_sheet.png")
    log.info(
        "wrote %d cases to %s; stats → volumetric_stats.json; contact sheet → %s", len(all_cases), out_path, QA_DIR
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
