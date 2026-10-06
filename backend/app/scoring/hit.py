"""SPEC §6.1 hit test: inside the instance mask dilated by τ, else inside the bbox expanded by τ."""

from __future__ import annotations

import numpy as np

from shared.contracts import Finding


def tolerance_px(width: int, cfg: dict) -> float:
    """τ = tolerance_frac · W (scoring.yaml: hit.tolerance_frac)."""
    return float(cfg["hit"]["tolerance_frac"]) * width


def hits(x: float, y: float, finding: Finding, tau: float, dilated_mask: np.ndarray | None) -> bool:
    """Pure hit test. `dilated_mask` is the finding mask dilated by τ (or None → bbox ± τ)."""
    if dilated_mask is not None:
        h, w = dilated_mask.shape
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < w and 0 <= yi < h):
            return False
        return bool(dilated_mask[yi, xi])
    x0, y0, x1, y1 = finding.geometry.bbox
    return x0 - tau <= x <= x1 + tau and y0 - tau <= y <= y1 + tau
