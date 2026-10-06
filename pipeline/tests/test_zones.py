"""derive_zones on SYNTHETIC masks (SPEC §4.3). Patient RIGHT is on the image LEFT."""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.anatomy.common import zone_ids
from pipeline.anatomy.synthetic import LL, RL, H, W, disk, rect, synth_anatomy
from pipeline.anatomy.zones import approximate_zones, derive_zones, extent


@pytest.fixture(scope="module")
def zm():
    return derive_zones(synth_anatomy(), W, H)


def rows(m: np.ndarray) -> tuple[int, int]:
    r = np.flatnonzero(m.any(axis=1))
    return int(r[0]), int(r[-1])


def cols(m: np.ndarray) -> tuple[int, int]:
    c = np.flatnonzero(m.any(axis=0))
    return int(c[0]), int(c[-1])


def test_all_zone_ids_present(zm):
    zones, meta = zm
    for z in zone_ids():
        assert z in zones, z
        assert zones[z].shape == (H, W) and zones[z].dtype == bool
    for z in ("right_lung", "left_lung", "lungs"):
        assert z in zones
    assert meta["approximate"] is False
    assert meta["flags"] == []


def test_midline_is_spine_centroid(zm):
    _, meta = zm
    assert meta["midline_x"] == pytest.approx(127.5)


def test_midline_fallback_without_spine():
    _, meta = derive_zones(synth_anatomy(spine=False), W, H)
    assert meta["midline_x"] == W / 2
    assert "spine_missing" in meta["flags"]


@pytest.mark.parametrize("side,box", [("right", RL), ("left", LL)])
def test_thirds_of_own_extent(zm, side, box):
    zones, _ = zm
    x0, y0, x1, y1 = box
    h = y1 - y0 + 1  # 180 → thirds at 100 and 160
    u, m, lo = zones[f"{side}_upper_zone"], zones[f"{side}_mid_zone"], zones[f"{side}_lower_zone"]
    assert rows(u) == (y0, y0 + h // 3 - 1)
    assert rows(m) == (y0 + h // 3, y0 + 2 * h // 3 - 1)
    assert rows(lo) == (y0 + 2 * h // 3, y1)
    # partition of the lung, pairwise disjoint
    lung = zones[f"{side}_lung"]
    assert np.array_equal(u | m | lo, lung)
    assert not (u & m).any() and not (m & lo).any() and not (u & lo).any()


def test_thirds_follow_each_lungs_own_extent():
    a = synth_anatomy()
    a["Left Lung"] = rect(146, 70, 225, 219)  # shorter left lung (150 rows)
    zones, _ = derive_zones(a, W, H)
    assert rows(zones["left_upper_zone"]) == (70, 119)
    assert rows(zones["right_upper_zone"]) == (40, 99)


def test_apex_is_top_18_percent(zm):
    zones, _ = zm
    for side, (x0, y0, x1, y1) in (("right", RL), ("left", LL)):
        apex = zones[f"{side}_apex"]
        h = y1 - y0 + 1
        assert rows(apex) == (y0, int(np.ceil(y0 + 0.18 * h)) - 1)  # y < y0 + 32.4 → 40..72
        assert not (apex & ~zones[f"{side}_upper_zone"]).any()  # apex ⊂ upper zone


def test_costophrenic_angles_are_lateral_and_basal(zm):
    zones, _ = zm
    h = RL[3] - RL[1] + 1
    w = RL[2] - RL[0] + 1
    rcp, lcp = zones["right_costophrenic_angle"], zones["left_costophrenic_angle"]
    # bottom 18% of the lung's extent
    assert rows(rcp) == (int(np.ceil(RL[3] + 1 - 0.18 * h)), RL[3])
    # patient-right lung: lateral = image-left (small x)
    assert cols(rcp) == (RL[0], int(np.ceil(RL[0] + 0.45 * w)) - 1)
    # patient-left lung: lateral = image-right (large x)
    assert cols(lcp) == (int(np.ceil(LL[2] + 1 - 0.45 * w)), LL[2])
    assert cols(rcp)[1] < 128 < cols(lcp)[0]


def test_periphery_is_outer_band(zm):
    zones, _ = zm
    per = zones["right_periphery"]
    k = 0.08 * (RL[2] - RL[0] + 1)  # 6.4 px
    cy = (RL[1] + RL[3]) // 2
    # band = pixels within k of the outside: x0..x0+5 (distance 1..6 <= 6.4); x0+6 is at distance 7
    assert per[cy, RL[0]] and per[cy, RL[0] + int(k) - 1] and not per[cy, RL[0] + int(k)]
    assert not per[cy, (RL[0] + RL[2]) // 2]  # lung centre is not periphery
    assert not (per & ~zones["right_lung"]).any()


def test_hila_dilated_by_1_5_percent_width(zm):
    zones, _ = zm
    r = 0.015 * W  # 3.84 px
    x0, _, x1, _ = extent(zones["right_hilum"])
    assert (x1 - x0 + 1) == pytest.approx(2 * (6 + r) + 1, abs=2)
    assert zones["right_hilum"][110, 100] and zones["left_hilum"][115, 156]


def test_retrocardiac_is_heart_left_of_patient_below_left_hilum(zm):
    zones, meta = zm
    rc = zones["retrocardiac"]
    assert rc.any()
    ys, xs = np.nonzero(rc)
    assert xs.min() > meta["midline_x"]  # patient-left = image right of midline
    assert ys.min() > 115  # below the left hilum centroid
    assert not (rc & ~zones["cardiac_silhouette"]).any()
    heart = synth_anatomy()["Heart"]
    assert np.array_equal(rc, heart & (np.arange(W)[None, :] > 127.5) & (np.arange(H)[:, None] > 115))


def test_mediastinum_union(zm):
    zones, _ = zm
    a = synth_anatomy()
    assert np.array_equal(zones["mediastinum"], a["Mediastinum"] | a["Aorta"] | a["Weasand"])
    assert np.array_equal(zones["cardiac_silhouette"], a["Heart"])
    assert np.array_equal(zones["spine"], a["Spine"])
    assert np.array_equal(zones["right_clavicle"], a["Right Clavicle"])


def test_subdiaphragmatic_band(zm):
    zones, _ = zm
    sd = zones["subdiaphragmatic"]
    assert rows(sd) == (220, int(np.ceil(220 + 0.08 * H)) - 1)
    assert cols(sd) == (RL[0], LL[2])  # within the lungs' x-range


def test_patient_side_naming_blob_at_image_left_is_right(zm):
    zones, _ = zm
    blob = disk(60, 130, 5)  # image LEFT
    hit = [z for z in zones if (zones[z] & blob).any() and z not in ("lungs",)]
    assert hit and all(z.startswith("right_") for z in hit), hit
    blob2 = disk(200, 130, 5)  # image RIGHT
    hit2 = [z for z in zones if (zones[z] & blob2).any() and z not in ("lungs",)]
    assert hit2 and all(z.startswith("left_") for z in hit2), hit2


def test_right_lung_zones_are_on_image_left(zm):
    zones, meta = zm
    for z, m in zones.items():
        if z.startswith("right_") and m.any():
            assert np.nonzero(m)[1].mean() < meta["midline_x"], z
        if z.startswith("left_") and m.any():
            assert np.nonzero(m)[1].mean() > meta["midline_x"], z


def test_approximate_fallback_when_lung_tiny():
    a = synth_anatomy()
    a["Left Lung"] = rect(150, 100, 160, 110)  # 121 px << 3% of the image
    zones, meta = derive_zones(a, W, H)
    assert meta["approximate"] is True
    assert "anatomy_failed" in meta["flags"]
    for z in zone_ids():
        assert zones[z].any(), z
    # still patient-side: right lung zones on the image left
    assert np.nonzero(zones["right_lung"])[1].max() < W / 2 < np.nonzero(zones["left_lung"])[1].min()


def test_approximate_zones_standalone_any_size():
    zones, meta = approximate_zones(1024, 1024)
    assert meta["approximate"] and meta["midline_x"] == 512
    assert zones["retrocardiac"].any() and zones["subdiaphragmatic"].any()


def test_missing_lung_is_failure():
    a = synth_anatomy()
    del a["Right Lung"]
    _, meta = derive_zones(a, W, H)
    assert meta["approximate"] and "anatomy_failed" in meta["flags"]


def test_rle_roundtrip(tmp_path, zm):
    from shared.rle import read_zones, write_zones

    zones, meta = zm
    p = tmp_path / "z.json"
    write_zones(p, "syn_x", zones, approximate=meta["approximate"], midline_x=meta["midline_x"])
    back, m2 = read_zones(p)
    assert set(back) == set(zones)
    for k in zones:
        assert np.array_equal(back[k], zones[k]), k
    assert m2["midline_x"] == pytest.approx(127.5)
