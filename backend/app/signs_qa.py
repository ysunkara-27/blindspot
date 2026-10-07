"""QA: draw the sign annotations of random real cases onto PNGs under data/qa/signs_<case>.png.

    uv run python -m backend.app.signs_qa [--n 20] [--seed 1] [--labels pneumothorax,effusion] [--out data/qa]
Never part of the app; for looking at geometry by eye before a release.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2
import numpy as np

from backend.app.cases import get_repo
from backend.app.signs import check_sign, draw_signs, signs_for_case


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--labels", default="")
    ap.add_argument("--out", type=Path, default=Path("data/qa"))
    a = ap.parse_args()
    repo = get_repo()
    want = {x for x in a.labels.split(",") if x}
    cases = [c for c in repo.all() if c.volume is None and c.findings and c.anatomy_path]
    if want:
        cases = [c for c in cases if any(f.label in want for f in c.findings)]
    rng = random.Random(a.seed)
    rng.shuffle(cases)
    a.out.mkdir(parents=True, exist_ok=True)
    n_signs = 0
    for c in cases[: a.n]:
        img = cv2.imread(str(repo.image_path(c)), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        out = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        signs = signs_for_case(c, repo)
        for f in c.findings:
            m = repo.mask(c.case_id, f.finding_id)
            if m is not None:  # faint magenta outline of the expert mask for reference
                cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(out, cnts, -1, (160, 60, 160), 1)
            for s in signs.get(f.short_id, []):
                errs = check_sign(s)
                if errs:
                    print("BAD", c.case_id, errs)
            n_signs += len(signs.get(f.short_id, []))
        out = draw_signs(out, [s for v in signs.values() for s in v])
        labels = ", ".join(f"{f.short_id} {f.label}" for f in c.findings)
        cv2.putText(out, f"{c.case_id}: {labels}"[:120], (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        p = a.out / f"signs_{c.case_id}.png"
        cv2.imwrite(str(p), out)
        print(p, "|", labels, "|", [s.id for v in signs.values() for s in v])
    print(f"{n_signs} signs on {min(a.n, len(cases))} cases")


if __name__ == "__main__":
    main()
