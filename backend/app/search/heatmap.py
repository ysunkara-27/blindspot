"""SPEC §7.4 search-trace heatmap: gaussian splats (σ = ρ) of dwell-weighted samples → 256×256 RGBA PNG (base64).

Colour = grease-pencil amber (#F0A92E); alpha encodes density. Client overlays it on the image.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np

from backend.app.search.dwell import DwellSamples

AMBER_BGR = (0x2E, 0xA9, 0xF0)
OUT = 256


def density(samples: DwellSamples, width: int, height: int, sigma_px: float, out: int = OUT) -> np.ndarray:
    """Normalised [0, 1] density on an out×out grid."""
    acc = np.zeros((out, out), np.float32)
    if samples.n:
        sx, sy = out / width, out / height
        for xs, ys, ws in ((samples.x, samples.y, samples.w_point), (samples.cx, samples.cy, samples.w_zoom)):
            keep = (ws > 0) & (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
            xi = np.clip((xs[keep] * sx).astype(int), 0, out - 1)
            yi = np.clip((ys[keep] * sy).astype(int), 0, out - 1)
            np.add.at(acc, (yi, xi), ws[keep].astype(np.float32))
    sig = max(0.5, sigma_px * out / width)
    acc = cv2.GaussianBlur(acc, (0, 0), sigmaX=sig, sigmaY=sig)
    mx = float(acc.max())
    return acc / mx if mx > 0 else acc


def heatmap_png_b64(samples: DwellSamples, width: int, height: int, sigma_px: float) -> str:
    d = density(samples, width, height, sigma_px)
    rgba = np.zeros((OUT, OUT, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = AMBER_BGR
    rgba[..., 3] = (np.sqrt(d) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", rgba)
    return base64.b64encode(buf.tobytes()).decode() if ok else ""
