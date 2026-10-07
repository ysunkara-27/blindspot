"""Build (and optionally upload) the runtime data bundle for a hosted Blindspot container.

Contents (everything the API reads at runtime, nothing else):
  cases.jsonl          without holdout cases
  splits.json          without the holdout list
  ingest_stats.json, taxonomy_report.json
  images/<case>.png    for every kept case
  masks/*.png          for every finding of every kept case
  zones/<case>.json.gz gzipped zones (shared.rle.read_zones reads the .gz sibling when the .json is absent)
Excluded: zone preview PNGs, anatomy/*.npz (dev overlays only), holdout cases' files, data/qa, the SQLite DB.

The bundle must stay PRIVATE (SPEC §20: no public redistribution of dataset images). --upload creates a private
Hugging Face *dataset* repo if missing and refuses to upload to a public one.

  uv run python deploy/make_data_bundle.py                       # stage into data/bundle/processed, print sizes
  uv run python deploy/make_data_bundle.py --tar data/bundle.tar # also write a tar
  HF_TOKEN=... uv run python deploy/make_data_bundle.py --upload <user>/blindspot-data
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_SPLITS = frozenset({"holdout"})
META_FILES = ("ingest_stats.json", "taxonomy_report.json")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


def kept_cases(src: Path) -> tuple[list[str], list[dict]]:
    lines, kept = [], []
    for line in (src / "cases.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c.get("split") in EXCLUDED_SPLITS:
            continue
        lines.append(line)
        kept.append(c)
    return lines, kept


def case_files(c: dict) -> list[str]:
    """Relative paths (images, masks) a kept case needs; zones handled separately (gzipped)."""
    out = [c["image_path"]]
    out += [f["geometry"]["mask_path"] for f in c.get("findings", []) if f.get("geometry", {}).get("mask_path")]
    return out


def filtered_splits(doc: dict) -> dict:
    doc = dict(doc)
    if isinstance(doc.get("splits"), dict):
        doc["splits"] = {k: v for k, v in doc["splits"].items() if k not in EXCLUDED_SPLITS}
    for k in EXCLUDED_SPLITS:
        doc.pop(k, None)
    return doc


def _place(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)  # same filesystem: no extra disk
    except OSError:
        shutil.copy2(src, dst)


def gzip_zones(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    with src.open("rb") as fi, gzip.open(dst, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)


def build(src: Path, out: Path) -> dict[str, int]:
    lines, kept = kept_cases(src)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases.jsonl").write_text("\n".join(lines) + "\n")
    if (src / "splits.json").exists():
        (out / "splits.json").write_text(json.dumps(filtered_splits(json.loads((src / "splits.json").read_text()))))
    for m in META_FILES:
        if (src / m).exists():
            shutil.copy2(src / m, out / m)
    missing = 0
    for c in kept:
        for rel in case_files(c):
            if (src / rel).exists():
                _place(src / rel, out / rel)
            else:
                missing += 1
        z = c.get("zones_path")
        if z and (src / z).exists():
            gzip_zones(src / z, out / (z + ".gz"))
    # Volumetric cases (cases_msd.jsonl): every case's volume, label volume, preview and zones3d file, plus the
    # reference-bank picks. These are already gzipped packs; holdout does not apply (no holdout split for volumes).
    vol_src = src / "cases_msd.jsonl"
    if vol_src.exists():
        vol_lines = [ln for ln in vol_src.read_text().splitlines() if ln.strip()]
        (out / "cases_msd.jsonl").write_text("\n".join(vol_lines) + "\n")
        for ln in vol_lines:
            c = json.loads(ln)
            rels = [c.get("image_path")]
            v = c.get("volume") or {}
            rels += [v.get("data_path"), v.get("mask_path")]
            rels.append(f"zones3d/{c['case_id']}.json")
            for rel in rels:
                if rel and (src / rel).exists():
                    _place(src / rel, out / rel)
                elif rel:
                    missing += 1
        for extra in ("reference_bank_volumetric.json", "volumetric_stats.json"):
            if (src / extra).exists():
                shutil.copy2(src / extra, out / extra)
    sizes: dict[str, int] = {}
    for p in out.rglob("*"):
        if p.is_file():
            top = p.relative_to(out).parts[0] if len(p.relative_to(out).parts) > 1 else "(top-level files)"
            sizes[top] = sizes.get(top, 0) + p.stat().st_size
    sizes["_cases"] = len(kept)
    sizes["_missing_files"] = missing
    return sizes


def write_tar(out: Path, tar_path: Path) -> int:
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w") as tf:  # PNGs and .gz are already compressed
        tf.add(out, arcname="processed")
    return tar_path.stat().st_size


def upload(out: Path, repo_id: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    info = api.repo_info(repo_id, repo_type="dataset")
    if not getattr(info, "private", False):
        sys.exit(f"refusing to upload: dataset repo {repo_id} is PUBLIC (SPEC §20). Make it private first.")
    if hasattr(api, "upload_large_folder"):  # resumable, many files
        api.upload_large_folder(repo_id=repo_id, folder_path=str(out), repo_type="dataset", private=True)
    else:
        api.upload_folder(repo_id=repo_id, folder_path=str(out), repo_type="dataset", commit_message="data bundle")
    print(f"uploaded {out} → https://huggingface.co/datasets/{repo_id} (private)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, default=REPO_ROOT / "data" / "processed")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "bundle" / "processed")
    ap.add_argument("--tar", type=Path, default=None, help="also write an (uncompressed) tar of the bundle")
    ap.add_argument("--upload", metavar="REPO_ID", default=None, help="upload to a PRIVATE HF dataset repo")
    a = ap.parse_args(argv)
    if not (a.src / "cases.jsonl").exists():
        print(f"no cases.jsonl under {a.src}", file=sys.stderr)
        return 2
    sizes = build(a.src, a.out)
    n, missing = sizes.pop("_cases"), sizes.pop("_missing_files")
    total = sum(sizes.values())
    print(f"bundle: {a.out}  ({n} cases, holdout excluded; {missing} referenced files missing)")
    for k, v in sorted(sizes.items()):
        print(f"  {k:<20} {human(v):>10}")
    print(f"  {'TOTAL':<20} {human(total):>10}")
    if a.tar:
        print(f"tar: {a.tar} {human(write_tar(a.out, a.tar))}")
    if a.upload:
        upload(a.out, a.upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
