"""SYNTHETIC toy anatomy for unit tests only — not derived from any radiograph; never used for real cases.

256×256, patient RIGHT on the image LEFT. Rectangular lungs make zone boundaries exactly computable:
right lung x 30..109, y 40..219 (80×180); left lung x 146..225, same rows; spine x 124..131 (centroid 127.5).
"""

from __future__ import annotations

import cv2
import numpy as np

W = H = 256
RL = (30, 40, 109, 219)  # inclusive x0, y0, x1, y1
LL = (146, 40, 225, 219)


def rect(x0: int, y0: int, x1: int, y1: int, w: int = W, h: int = H) -> np.ndarray:
    m = np.zeros((h, w), bool)
    m[y0 : y1 + 1, x0 : x1 + 1] = True
    return m


def disk(cx: int, cy: int, r: int, w: int = W, h: int = H) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.circle(m, (cx, cy), r, 1, -1)
    return m > 0


def ellipse(cx: int, cy: int, ax: int, ay: int, w: int = W, h: int = H) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (cx, cy), (ax, ay), 0, 0, 360, 1, -1)
    return m > 0


def synth_anatomy(*, spine: bool = True, swap: bool = False) -> dict[str, np.ndarray]:
    """Patient-side TXV-named masks. swap=True mislabels Left/Right (simulates image-side naming)."""
    m = {
        "Right Lung": rect(*RL),
        "Left Lung": rect(*LL),
        "Heart": ellipse(140, 180, 40, 35),
        "Right Hilus Pulmonis": disk(100, 110, 6),
        "Left Hilus Pulmonis": disk(156, 115, 6),
        "Mediastinum": rect(112, 30, 143, 150),
        "Aorta": disk(145, 60, 8),
        "Weasand": rect(124, 10, 131, 60),
        "Facies Diaphragmatica": rect(30, 220, 225, 235),
        "Right Clavicle": rect(40, 30, 115, 37),
        "Left Clavicle": rect(140, 30, 215, 37),
        "Right Scapula": rect(5, 50, 25, 120),
        "Left Scapula": rect(230, 50, 250, 120),
    }
    if spine:
        m["Spine"] = rect(124, 0, 131, 255)
    if swap:
        from pipeline.anatomy.orientation import swap_name

        m = {swap_name(k): v for k, v in m.items()}
    return m
