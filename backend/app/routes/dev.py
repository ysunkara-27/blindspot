"""Dev / clinical-QA routes: overlays of anatomy, zones and findings. Exposes ground truth by design —
used only by /dev/case/:id for QA, never by the reading flow.

Gated: every route returns 404 unless BLINDSPOT_DEV=1 (settings.blindspot_dev), so a pilot participant or demo
audience on the same origin can never read answers. `make dev`/`make demo` leave it off.
"""

from __future__ import annotations

import colorsys

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.app.cases import get_repo
from backend.app.settings import get_settings


def require_dev() -> None:
    """404 (not 403): when dev mode is off the routes should look absent."""
    if not get_settings().blindspot_dev:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(require_dev)], include_in_schema=False)
CYAN_BGR = (0xDD, 0xC9, 0x35)
GRATICULE_BGR = (0xA6, 0x99, 0x8C)


def _color(i: int, n: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(i / max(1, n), 0.7, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


@router.get("/cases")
def list_cases(split: str | None = None, limit: int = 200) -> dict:
    repo = get_repo()
    cs = [c for c in repo.all() if split is None or c.split == split][:limit]
    return {
        "n": repo.count(),
        "cases": [
            {
                "case_id": c.case_id,
                "split": c.split,
                "is_normal": c.is_normal,
                "labels": [f.label for f in c.findings],
                "qa_flags": c.qa_flags,
            }
            for c in cs
        ],
    }


@router.get("/cases/{case_id}")
def case_json(case_id: str) -> dict:
    c = get_repo().get(case_id)
    if c is None:
        raise HTTPException(status_code=404, detail="case not found")
    return c.model_dump()


@router.get("/cases/{case_id}/overlay")
def overlay(case_id: str, layers: str = Query(default="zones,findings")) -> Response:
    repo = get_repo()
    case = repo.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    img = cv2.imread(str(repo.image_path(case)), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise HTTPException(status_code=404, detail="image not found")
    out = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    want = {s.strip() for s in layers.split(",") if s.strip()}
    h, w = img.shape
    if "zones" in want:
        zones, _ = repo.zones(case_id)
        names = [z for z in zones if z not in ("lungs", "right_lung", "left_lung")]
        for i, z in enumerate(names):
            m = zones[z]
            if m.shape != (h, w):
                continue
            col = np.array(_color(i, len(names)), np.float32)
            out[m] = (0.75 * out[m] + 0.25 * col).astype(np.uint8)
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts:
                c = max(cnts, key=cv2.contourArea)
                x, y, bw, bh = cv2.boundingRect(c)
                cv2.putText(
                    out,
                    z,
                    (x + 2, y + bh // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.25, w / 2600),
                    _color(i, len(names)),
                    1,
                    cv2.LINE_AA,
                )
    if "anatomy" in want and case.anatomy_path and (repo.root / case.anatomy_path).exists():
        d = np.load(repo.root / case.anatomy_path, allow_pickle=False)
        shape = tuple(d["shape"])
        masks = np.unpackbits(d["masks"], axis=-1)[..., : shape[-1]].astype(bool)
        for m in masks:
            if m.shape != (h, w):
                m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(out, cnts, -1, GRATICULE_BGR, 1)
    if "findings" in want:
        for f in case.findings:
            m = repo.mask(case_id, f.finding_id)
            if m is not None:
                cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(out, cnts, -1, CYAN_BGR, max(1, w // 512))
            else:
                x0, y0, x1, y1 = (int(v) for v in f.geometry.bbox)
                cv2.rectangle(out, (x0, y0), (x1, y1), CYAN_BGR, max(1, w // 512))
            cx, cy = (int(v) for v in f.centroid)
            cv2.putText(
                out,
                f"{f.short_id} {f.label}",
                (cx, cy),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.3, w / 2000),
                CYAN_BGR,
                1,
                cv2.LINE_AA,
            )
    ok, buf = cv2.imencode(".png", out)
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})
