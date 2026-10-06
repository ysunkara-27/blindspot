"""Clinical-QA contact sheets (SPEC §3.2 step 8): 24 random abnormal + 6 random normal cases with mask outlines
and labels -> data/qa/contact_sheet_abnormal_1.png, _abnormal_2.png, contact_sheet_normal.png + an index JSON.

Run:  uv run python -m pipeline.qa_contact_sheet [--seed N]

Each tile: the canonical image, every finding's mask outline in its label colour with the label name, the case id,
split and qa flags. A small "image left = patient R" tag is drawn so reviewers can check orientation.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import cv2
import numpy as np

from shared.contracts import Case

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BLINDSPOT_DATA_DIR", REPO_ROOT / "data"))
PROC_DIR = DATA_DIR / "processed"
QA_DIR = DATA_DIR / "qa"
SEED = 7
TILE = 512
COLS = 4

# BGR, distinguishable on a grey radiograph
COLORS: dict[str, tuple[int, int, int]] = {
    "pneumothorax": (255, 255, 0),
    "effusion": (255, 128, 0),
    "consolidation": (0, 200, 255),
    "atelectasis": (0, 128, 255),
    "nodule": (0, 255, 0),
    "mass": (0, 0, 255),
    "calcification": (255, 255, 255),
    "fracture": (255, 0, 255),
    "pleural_thickening": (180, 105, 255),
    "cardiomegaly": (0, 255, 255),
    "emphysema": (128, 255, 128),
    "fibrosis": (200, 200, 0),
    "diffuse_nodule": (100, 180, 100),
}


def _text(img: np.ndarray, s: str, org: tuple[int, int], color=(255, 255, 255), scale: float = 0.5) -> None:
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def render_tile(case: Case, root: Path, tile: int = TILE) -> np.ndarray:
    img = cv2.imread(str(root / case.image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(root / case.image_path)
    s = tile / img.shape[1]
    out = cv2.cvtColor(cv2.resize(img, (tile, tile), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
    for f in case.findings:
        m = cv2.imread(str(root / f.geometry.mask_path), cv2.IMREAD_GRAYSCALE) if f.geometry.mask_path else None
        if m is None:
            continue
        m = cv2.resize(m, (tile, tile), interpolation=cv2.INTER_NEAREST)
        cnts, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        col = COLORS.get(f.label, (255, 255, 255))
        dash = f.geometry.kind == "bbox"
        cv2.drawContours(out, cnts, -1, col, 1 if dash else 2, cv2.LINE_AA)
        x0, y0 = f.geometry.bbox[0] * s, f.geometry.bbox[1] * s
        tag = f"{f.finding_id.split('#')[1]} {f.label}" + (" [bbox]" if dash else "")
        _text(out, tag, (int(x0), max(int(y0) - 4, 30)), col, 0.45)
    _text(
        out,
        f"{case.case_id}  {case.split}  {'NORMAL' if case.is_normal else f'{len(case.findings)} findings'}",
        (6, 18),
    )
    if case.qa_flags:
        _text(out, "flags: " + ",".join(case.qa_flags), (6, tile - 10), (0, 200, 255), 0.4)
    _text(out, "img-left = pt R", (6, 36), (200, 200, 200), 0.4)
    return out


def make_sheet(cases: list[Case], root: Path, title: str, cols: int = COLS, tile: int = TILE) -> np.ndarray:
    rows = max(1, -(-len(cases) // cols))
    head = 40
    sheet = np.zeros((head + rows * tile, cols * tile, 3), np.uint8)
    _text(sheet, title, (10, 27), (255, 255, 255), 0.7)
    for i, c in enumerate(cases):
        r, k = divmod(i, cols)
        sheet[head + r * tile : head + (r + 1) * tile, k * tile : (k + 1) * tile] = render_tile(c, root, tile)
    return sheet


def legend(cols: int = COLS, tile: int = TILE) -> np.ndarray:
    h = 30 + 22 * ((len(COLORS) + 3) // 4)
    img = np.zeros((h, cols * tile, 3), np.uint8)
    for i, (lab, col) in enumerate(COLORS.items()):
        r, k = divmod(i, 4)
        _text(img, lab, (10 + k * (cols * tile // 4), 22 + 22 * r), col, 0.55)
    return img


def sample(cases: list[Case], n_abn: int = 24, n_norm: int = 6, seed: int = SEED) -> tuple[list[Case], list[Case]]:
    rng = random.Random(seed)
    abn = sorted((c for c in cases if not c.is_normal), key=lambda c: c.case_id)
    nor = sorted((c for c in cases if c.is_normal), key=lambda c: c.case_id)
    return rng.sample(abn, min(n_abn, len(abn))), rng.sample(nor, min(n_norm, len(nor)))


def run(seed: int = SEED, proc: Path = PROC_DIR, qa: Path = QA_DIR) -> list[Path]:
    with (proc / "cases.jsonl").open() as fh:
        cases = [Case.model_validate_json(line) for line in fh if line.strip()]
    abn, nor = sample(cases, seed=seed)
    qa.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    leg = legend()
    for j in range(0, len(abn), 12):
        chunk = abn[j : j + 12]
        p = qa / f"contact_sheet_abnormal_{j // 12 + 1}.png"
        sheet = make_sheet(chunk, proc, f"Blindspot QA — abnormal {j + 1}-{j + len(chunk)} of {len(abn)} (seed {seed})")
        cv2.imwrite(str(p), np.vstack([sheet, leg]))
        out.append(p)
    p = qa / "contact_sheet_normal.png"
    cv2.imwrite(str(p), make_sheet(nor, proc, f"Blindspot QA — {len(nor)} normal (seed {seed})", cols=3))
    out.append(p)
    index = {
        "seed": seed,
        "abnormal": [{"case_id": c.case_id, "labels": [f.label for f in c.findings], "flags": c.qa_flags} for c in abn],
        "normal": [c.case_id for c in nor],
        "review_prompt": "For each tile: is every outline on the right structure and correctly labelled? "
        "Note case_id + finding id for any disagreement.",
    }
    (qa / "contact_sheet_index.json").write_text(json.dumps(index, indent=2) + "\n")
    for p in out:
        print(f"wrote {p}", flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write clinical-QA contact sheets")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    run(a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
