"""Images sent with a debrief (SPEC §8.2). Rendered only after submit; PNG bytes, ≤ 1568 px long edge.

1. full: the whole radiograph with expert outlines in cyan (F1, F2, ...) and learner marks in amber (M1, M2, ...)
2. crop: unannotated window around the primary missed/mislabeled finding (half the image width; a quarter-width
   window upscaled ×2 when the finding is small) so the sign is not hidden under an outline
3. crop_outlined: the same window with thin cyan outlines
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from shared.contracts import Case, DebriefFacts, Finding, Mark

CYAN_BGR = (221, 201, 53)  # #35C9DD lightbox cyan (truth)
AMBER_BGR = (46, 169, 240)  # #F0A92E grease-pencil amber (the learner)
MAX_EDGE = 1568
SMALL_FINDING_FRAC = 0.1  # bbox long side < 10% of width → zoomed crop
IMAGE_KEYS = ("full", "crop", "crop_outlined")


def _contours(f: Finding, case: Case, root: Path) -> list[np.ndarray]:
    g = f.geometry
    if g.polygon and len(g.polygon) >= 3:
        return [np.round(np.asarray(g.polygon, dtype=np.float32)).astype(np.int32).reshape(-1, 1, 2)]
    if g.mask_path and (root / g.mask_path).exists():
        m = cv2.imread(str(root / g.mask_path), cv2.IMREAD_GRAYSCALE)
        if m is not None:
            if m.shape != (case.height, case.width):
                m = cv2.resize(m, (case.width, case.height), interpolation=cv2.INTER_NEAREST)
            cs, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cs:
                return list(cs)
    x0, y0, x1, y1 = (int(round(v)) for v in g.bbox)
    return [np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32).reshape(-1, 1, 2)]


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float) -> None:
    th = max(1, int(round(scale * 2)))
    x = int(np.clip(org[0], 0, img.shape[1] - 1))
    y = int(np.clip(org[1], 12, img.shape[0] - 1))
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 2, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, th, cv2.LINE_AA)


def _fit(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = MAX_EDGE / max(h, w)
    if s >= 1.0:
        return img
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", _fit(img))
    if not ok:  # pragma: no cover
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def primary_target(
    case: Case, facts: DebriefFacts | None, marks: Sequence[Mark]
) -> tuple[float, float, Finding | None]:
    """Centre for the crops: first missed focal finding, then mislabeled, then any focal, then any finding,
    then the first false-positive mark, then the image centre."""
    res = {o.target: o.result for o in (facts.outcomes if facts else [])}
    focal = [f for f in case.findings if f.kind == "focal"]
    for want in (("missed_search", "missed_recognition", "missed_decision"), ("mislabeled",)):
        for f in focal:
            if res.get(f.short_id) in want:
                return f.centroid[0], f.centroid[1], f
    if focal:
        return focal[0].centroid[0], focal[0].centroid[1], focal[0]
    if case.findings:
        f = case.findings[0]
        return f.centroid[0], f.centroid[1], f
    fps = {o.target for o in (facts.outcomes if facts else []) if o.result == "false_positive"}
    for m in marks:
        if m.mark_id in fps or not fps:
            return m.x, m.y, None
    return case.width / 2, case.height / 2, None


def render_images(
    case: Case, facts: DebriefFacts | None, marks: Sequence[Mark], data_root: Path | str
) -> dict[str, bytes]:
    """Return {"full", "crop", "crop_outlined"} PNG bytes. Raises FileNotFoundError if the image is missing."""
    root = Path(data_root)
    gray = cv2.imread(str(root / case.image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(root / case.image_path)
    h, w = gray.shape
    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    contours = {f.short_id: _contours(f, case, root) for f in case.findings}
    thick = max(1, int(round(w / 512)))
    fscale = max(0.35, w / 1024 * 0.8)

    full = base.copy()
    for f in case.findings:
        cs = contours[f.short_id]
        cv2.drawContours(full, cs, -1, CYAN_BGR, thick, cv2.LINE_AA)
        x0, y0, _, _ = f.geometry.bbox
        _label(full, f.short_id, (int(x0), int(y0) - 4 * thick), CYAN_BGR, fscale)
    r = max(4, int(round(0.012 * w)))
    for m in marks:
        c = (int(round(m.x)), int(round(m.y)))
        cv2.circle(full, c, r, AMBER_BGR, thick, cv2.LINE_AA)
        _label(full, m.mark_id, (c[0] + r + 2, c[1] - r), AMBER_BGR, fscale)

    cx, cy, target = primary_target(case, facts, marks)
    small = (
        target is not None
        and max(target.geometry.bbox[2] - target.geometry.bbox[0], target.geometry.bbox[3] - target.geometry.bbox[1])
        < SMALL_FINDING_FRAC * w
    )
    win = int(round(w / 4)) if small else int(round(w / 2))
    win = max(8, min(win, w, h))
    x0 = int(np.clip(round(cx - win / 2), 0, w - win))
    y0 = int(np.clip(round(cy - win / 2), 0, h - win))
    zoom = 2 if small else 1
    crop = base[y0 : y0 + win, x0 : x0 + win].copy()
    if zoom != 1:
        crop = cv2.resize(crop, (win * zoom, win * zoom), interpolation=cv2.INTER_CUBIC)
    outlined = crop.copy()
    for f in case.findings:
        for cnt in contours[f.short_id]:
            shifted = ((cnt.astype(np.float32) - np.array([x0, y0], np.float32)) * zoom).round().astype(np.int32)
            cv2.drawContours(outlined, [shifted], -1, CYAN_BGR, 1, cv2.LINE_AA)
    return {"full": _png(full), "crop": _png(crop), "crop_outlined": _png(outlined)}


def ordered(images: dict[str, bytes] | None) -> list[bytes]:
    """Images in the order the prompt describes them."""
    if not images:
        return []
    return [images[k] for k in IMAGE_KEYS if k in images]
