"""Mark → finding spatial relations in patient-side anatomical language (SPEC §4.4). Never centimetres.

Patient RIGHT lung appears on the image LEFT; "lateral" for the right lung = smaller x, for the left lung = larger x.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from backend.app.config import display, zone_human

ROWS = {"upper": 0, "mid": 1, "lower": 2}
STEP_WORDS = {1: "one zone", 2: "two zones"}


def lung_of(zone: str | None) -> str | None:
    if not zone:
        return None
    if zone.startswith("right_"):
        return "right"
    if zone.startswith("left_"):
        return "left"
    return None


def zone_row(zone: str | None) -> int | None:
    if not zone:
        return None
    if zone.endswith("_apex"):
        return 0
    if zone.endswith("_costophrenic_angle"):
        return 2
    for k, v in ROWS.items():
        if zone.endswith(f"_{k}_zone"):
            return v
    return None


def lung_box(zones: Mapping[str, np.ndarray], side: str) -> tuple[float, float, float, float] | None:
    m = zones.get(f"{side}_lung")
    if m is None or not m.any():
        return None
    ys, xs = np.nonzero(m)
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def direction_words(
    mark_xy: tuple[float, float],
    target_xy: tuple[float, float],
    side: str | None,
    box: tuple[float, float, float, float] | None,
    min_frac: float = 0.1,
) -> list[str]:
    """Direction from the mark to the target, in units of lung height/width ('lower', 'more lateral')."""
    x0, y0, x1, y1 = box if box else (0.0, 0.0, 1.0, 1.0)
    lw, lh = max(1.0, x1 - x0), max(1.0, y1 - y0)
    dx = (target_xy[0] - mark_xy[0]) / lw
    dy = (target_xy[1] - mark_xy[1]) / lh
    words = []
    if dy > min_frac:
        words.append("lower")
    elif dy < -min_frac:
        words.append("higher")
    if side in ("right", "left") and abs(dx) > min_frac:
        # image x grows toward the patient's left
        lateral = (dx < 0) if side == "right" else (dx > 0)
        words.append("more lateral" if lateral else "more medial")
    return words


def relation_text(
    finding_label: str,
    finding_zone: str | None,
    finding_side: str | None,
    finding_xy: tuple[float, float],
    mark_zone: str | None,
    mark_xy: tuple[float, float],
    zones: Mapping[str, np.ndarray],
) -> str:
    name = display(finding_label).lower()
    fz, mz = zone_human(finding_zone), zone_human(mark_zone)
    f_lung = finding_side if finding_side in ("right", "left") else lung_of(finding_zone)
    m_lung = lung_of(mark_zone)
    if mark_zone is None:
        return f"Your mark was outside the lungs; the {name} is in the {fz}."
    if f_lung and m_lung and f_lung != m_lung:
        return f"The {name} is in the other lung: your mark was in the {mz}; the {name} is in the {fz}."
    parts = []
    fr, mr = zone_row(finding_zone), zone_row(mark_zone)
    if fr is not None and mr is not None and fr != mr and f_lung == m_lung:
        steps = abs(fr - mr)
        parts.append(f"{STEP_WORDS.get(steps, f'{steps} zones')} {'lower' if fr > mr else 'higher'}")
    dirs = direction_words(mark_xy, finding_xy, f_lung, lung_box(zones, f_lung) if f_lung else None)
    if parts:
        dirs = [d for d in dirs if d not in ("lower", "higher")]
    desc = ", ".join(parts + dirs)
    if finding_zone == mark_zone:
        lead = f"Same zone: your mark was in the {mz}"
        return f"{lead}; the {name} is {desc} than your mark." if desc else f"{lead}, close to the {name}."
    if desc:
        return f"Your mark was in the {mz}; the {name} is {desc}, in the {fz}."
    return f"Your mark was in the {mz}; the {name} is in the {fz}."


def no_mark_text(finding_label: str, relative_location: str | None, finding_zone: str | None) -> str:
    where = relative_location or zone_human(finding_zone)
    return f"The {display(finding_label).lower()} is in the {where}."
