"""Image rendering for eval prompts and galleries (grid overlay, learner marks, expert outlines, crops).

Rendered images go to the API (base64) or to data/eval_galleries/ — never to eval/reports/ (no patient images in
committed reports).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from eval.common import sha256_bytes
from shared.contracts import Case

CYAN = (221, 201, 53)  # BGR of #35C9DD (expert truth)
AMBER = (46, 169, 240)  # BGR of #F0A92E (learner)
GRID = (0, 230, 255)  # BGR bright yellow
BLACK = (0, 0, 0)
COLS = "ABCDEFGH"


def load_gray(root: Path, case: Case) -> np.ndarray:
    img = cv2.imread(str(Path(root) / case.image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(Path(root) / case.image_path)
    return img


def to_rgb(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) if gray.ndim == 2 else gray.copy()


def png_bytes(img_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise RuntimeError("png encode failed")
    return buf.tobytes()


def image_block(img_bgr: np.ndarray) -> tuple[dict[str, Any], str]:
    """Anthropic image content block + sha256 of the PNG bytes."""
    b = png_bytes(img_bgr)
    return (
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(b).decode("ascii"),
            },
        },
        sha256_bytes(b),
    )


def _text(img: np.ndarray, s: str, org: tuple[int, int], scale: float, color: tuple[int, int, int], th: int) -> None:
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, BLACK, th + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, th, cv2.LINE_AA)


# ------------------------------------------------------------------------------------------------ grid (§12.1)
def cell_of(x: float, y: float, w: int, h: int, n: int = 8) -> str:
    c = int(np.clip(np.floor(x / (w / n)), 0, n - 1))
    r = int(np.clip(np.floor(y / (h / n)), 0, n - 1))
    return f"{COLS[c]}{r + 1}"


def cell_bbox(cell: str, w: int, h: int, n: int = 8) -> tuple[int, int, int, int]:
    c = COLS.index(cell[0].upper())
    r = int(cell[1:]) - 1
    if not (0 <= c < n and 0 <= r < n):
        raise ValueError(cell)
    return (int(round(c * w / n)), int(round(r * h / n)), int(round((c + 1) * w / n)), int(round((r + 1) * h / n)))


def all_cells(n: int = 8) -> list[str]:
    return [f"{COLS[c]}{r + 1}" for r in range(n) for c in range(n)]


def grid_overlay(gray: np.ndarray, n: int = 8) -> np.ndarray:
    """Columns A–H left→right (image x), rows 1–8 top→bottom (image y); thin lines, edge labels."""
    img = to_rgb(gray)
    h, w = img.shape[:2]
    th = max(1, int(round(w / 700)))
    for i in range(1, n):
        x = int(round(i * w / n))
        y = int(round(i * h / n))
        cv2.line(img, (x, 0), (x, h - 1), GRID, th, cv2.LINE_AA)
        cv2.line(img, (0, y), (w - 1, y), GRID, th, cv2.LINE_AA)
    scale = w / 1100
    tth = max(1, int(round(w / 500)))
    for c in range(n):
        cx = int(round((c + 0.5) * w / n))
        _text(img, COLS[c], (cx - int(10 * scale), int(28 * scale) + 4), scale, GRID, tth)
    for r in range(n):
        cy = int(round((r + 0.5) * h / n))
        _text(img, str(r + 1), (4, cy + int(10 * scale)), scale, GRID, tth)
    return img


# ------------------------------------------------------------------------------------------------ overlays
def draw_marks(img: np.ndarray, marks: list[Any]) -> np.ndarray:
    h, w = img.shape[:2]
    r = max(4, int(round(w / 80)))
    th = max(1, int(round(w / 400)))
    for m in marks:
        x, y = int(round(m.x)), int(round(m.y))
        cv2.circle(img, (x, y), r, AMBER, th, cv2.LINE_AA)
        cv2.line(img, (x - r // 2, y), (x + r // 2, y), AMBER, th)
        cv2.line(img, (x, y - r // 2), (x, y + r // 2), AMBER, th)
        _text(img, m.mark_id, (x + r + 2, y - r), w / 1300, AMBER, th)
    return img


def draw_outlines(img: np.ndarray, case: Case, repo: Any, findings: list[Any] | None = None) -> np.ndarray:
    h, w = img.shape[:2]
    th = max(1, int(round(w / 450)))
    for f in findings if findings is not None else case.findings:
        m = repo.mask(case.case_id, f.finding_id)
        if m is not None:
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(img, cnts, -1, CYAN, th, cv2.LINE_AA)
        else:
            x0, y0, x1, y1 = (int(round(v)) for v in f.geometry.bbox)
            cv2.rectangle(img, (x0, y0), (x1, y1), CYAN, th)
        x0, y0 = int(f.geometry.bbox[0]), int(f.geometry.bbox[1])
        _text(img, f.short_id, (max(0, x0), max(12, y0 - 4)), w / 1300, CYAN, th)
    return img


def crop(img: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
    h, w = img.shape[:2]
    size = min(size, w, h)
    x0 = int(np.clip(round(cx - size / 2), 0, w - size))
    y0 = int(np.clip(round(cy - size / 2), 0, h - size))
    out = img[y0 : y0 + size, x0 : x0 + size].copy()
    if size < 512:
        out = cv2.resize(out, (size * 2, size * 2), interpolation=cv2.INTER_CUBIC)
    return out


def point(img: np.ndarray, x: float, y: float, color: tuple[int, int, int], label: str = "") -> None:
    h, w = img.shape[:2]
    r = max(3, int(round(w / 100)))
    cv2.drawMarker(img, (int(round(x)), int(round(y))), color, cv2.MARKER_TILTED_CROSS, 2 * r, max(1, w // 400))
    if label:
        _text(img, label, (int(x) + r, int(y) + r), w / 1400, color, max(1, w // 500))
