"""Anatomy: TXV segmentation → patient-side zones, review areas, finding locations.

Public, torch-free API (safe for the backend to import):
- derive_zones(masks, width, height) -> (zones, meta)            SPEC §4.3
- locate_finding(mask, zones, midline_x, label=None) -> {side, zones, primary_zone, relative_location}   §4.4
- zone_at(x, y, zones, nearest=False) -> zone id | None           (zone of a learner mark)
- spatial_relation(mark_xy, finding, zones, midline_x, finding_name=None) -> {text, same_side, zone_steps, ...}
Zones come from shared.rle.read_zones(data/processed/<zones_path>) → (zones, meta); meta["midline_x"].
Patient RIGHT is on the image LEFT (x < midline_x).
"""

from __future__ import annotations

from typing import Any

__all__ = ["approximate_zones", "derive_zones", "locate_finding", "spatial_relation", "zone_at"]

_WHERE = {
    "approximate_zones": "pipeline.anatomy.zones",
    "derive_zones": "pipeline.anatomy.zones",
    "locate_finding": "pipeline.anatomy.locate",
    "spatial_relation": "pipeline.anatomy.locate",
    "zone_at": "pipeline.anatomy.locate",
}


def __getattr__(name: str) -> Any:  # lazy, so `python -m pipeline.anatomy.zones` does not double-import
    if name in _WHERE:
        import importlib

        return getattr(importlib.import_module(_WHERE[name]), name)
    raise AttributeError(name)
