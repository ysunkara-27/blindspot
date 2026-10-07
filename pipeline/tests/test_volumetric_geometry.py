"""Pure-function tests for pipeline/volumetric/geometry.py and pack.py on synthetic volumes (no network, no data/)."""

from __future__ import annotations

import io
import tarfile

import nibabel as nib
import numpy as np
import pytest

from pipeline.volumetric import geometry as G
from pipeline.volumetric import pack, tarindex


def sphere(shape, centre, r_mm, spacing=(1.0, 1.0, 1.0)):
    z, y, x = np.mgrid[0 : shape[0], 0 : shape[1], 0 : shape[2]]
    cz, cy, cx = centre
    return ((z - cz) * spacing[0]) ** 2 + ((y - cy) * spacing[1]) ** 2 + ((x - cx) * spacing[2]) ** 2 <= r_mm**2


# --------------------------------------------------------------------------- orientation
def _marker_nifti(shape_ijk, idx, affine):
    arr = np.zeros(shape_ijk, dtype=np.int16)
    arr[idx] = 1000
    return nib.Nifti1Image(arr, affine)


def test_ras_identity_affine_marker_right_posterior_inferior_lands_low_x_high_y_high_z():
    # identity affine: voxel (0,0,0) is the most RIGHT, most POSTERIOR, most INFERIOR point.
    img = _marker_nifti((5, 7, 9), (0, 0, 0), np.eye(4))
    out, spacing = G.nifti_to_zyx(img)
    assert out.shape == (9, 7, 5)  # (z, y, x)
    z, y, x = np.argwhere(out == 1000)[0]
    assert (x, y, z) == (0, 6, 8), "patient right → x=0; posterior → bottom row; inferior → last slice"
    assert spacing == (1.0, 1.0, 1.0)


def test_lps_affine_marker_left_anterior_inferior():
    # DICOM-like LPS storage: voxel i increases toward patient RIGHT, j toward POSTERIOR.
    aff = np.diag([-1.0, -1.0, 1.0, 1.0])
    img = _marker_nifti((5, 7, 9), (0, 0, 0), aff)
    out, _ = G.nifti_to_zyx(img)
    z, y, x = np.argwhere(out == 1000)[0]
    assert (x, y, z) == (4, 0, 8), "most LEFT → x = nx-1; most ANTERIOR → y = 0; most INFERIOR → last slice"


def test_permuted_axes_affine_and_anisotropic_spacing():
    # voxel axis0 → world y (anterior), axis1 → world z (superior), axis2 → world x (left); spacings 2, 3, 0.5 mm
    aff = np.array([[0, 0, 0.5, 0], [2, 0, 0, 0], [0, 3, 0, 0], [0, 0, 0, 1]], dtype=float)
    img = _marker_nifti((5, 7, 9), (2, 0, 4), aff)
    out, spacing = G.nifti_to_zyx(img)
    assert out.shape == (7, 5, 9)
    z, y, x = np.argwhere(out == 1000)[0]
    assert (z, y, x) == (6, 2, 4)
    assert spacing == (3.0, 2.0, 0.5)  # (sz, sy, sx) carried exactly


def test_ras_to_zyx_is_a_pure_view_transform():
    arr = np.arange(2 * 3 * 4).reshape(2, 3, 4)  # (x, y, z)
    out = G.ras_to_zyx(arr)
    assert out.shape == (4, 3, 2)
    assert out[0, 0, 0] == arr[0, 2, 3]  # z=0 ← last z, y=0 ← last y, x=0 ← first x


def test_4d_channel_selection():
    arr = np.zeros((4, 4, 4, 3), dtype=np.float32)
    arr[..., 2] = 7
    img = nib.Nifti1Image(arr, np.eye(4))
    out, _ = G.nifti_to_zyx(img, channel=2)
    assert out.shape == (4, 4, 4) and (out == 7).all()
    with pytest.raises(ValueError):
        G.nifti_to_zyx(img)


# --------------------------------------------------------------------------- body crop
def test_body_crop_boxes_the_body_with_margin_and_drops_the_table():
    vol = np.full((4, 100, 120), -1000.0, np.float32)
    vol[:, 20:70, 30:90] = 40  # body
    vol[:, 90:94, 10:110] = 100  # table (separate component)
    label = np.zeros_like(vol, dtype=np.uint8)
    label[:, 40:45, 50:55] = 1
    box = G.body_crop(vol, label, "ct", margin=6)
    assert box == G.CropBox(14, 76, 24, 96)


def test_body_crop_refuses_to_clip_labelled_voxels():
    vol = np.full((4, 100, 120), -1000.0, np.float32)
    vol[:, 20:70, 30:90] = 40
    label = np.zeros_like(vol, dtype=np.uint8)
    label[:, 2:5, 2:5] = 2  # labelled voxel far outside the body threshold (and outside any margin)
    assert G.body_crop(vol, label, "ct", margin=6) is None


def test_body_crop_falls_back_to_all_voxels_when_largest_component_would_clip():
    vol = np.full((4, 100, 120), -1000.0, np.float32)
    vol[:, 20:70, 30:90] = 40
    vol[:, 90:94, 10:110] = 100
    label = np.zeros_like(vol, dtype=np.uint8)
    label[:, 91:93, 50:52] = 1  # labelled inside the "table" component
    box = G.body_crop(vol, label, "ct", margin=6)
    assert box == G.CropBox(14, 100, 4, 116)


def test_mr_body_mask_uses_fraction_of_peak():
    vol = np.zeros((2, 10, 10), np.float32)
    vol[:, 3:7, 3:7] = 1000
    vol[:, 0, 0] = 30  # below 6 % of peak
    m = G.body_mask(vol, "mr")
    assert m[:, 3:7, 3:7].all() and not m[:, 0, 0].any()


# --------------------------------------------------------------------------- slabs
def test_slab_around_margin_cap_and_edges():
    assert G.slab_around(10, 12, 100, 6, 32) == (4, 19)
    assert G.slab_around(2, 3, 100, 6, 32) == (0, 14)  # shifted (length kept) off the top edge
    assert G.slab_around(97, 99, 100, 6, 32) == (85, 100)  # shifted off the bottom edge
    z0, z1 = G.slab_around(10, 60, 100, 6, 32)  # extent exceeds cap → centred, capped
    assert z1 - z0 == 32 and z0 <= 35 <= z1
    assert G.slab_around(3, 5, 20, 6, 32) == (0, 15)  # cap larger than the volume: margin kept, shifted inside


def test_lesion_slab_picks_window_with_most_lesion_when_too_long():
    lesion = np.zeros((100, 4, 4), bool)
    lesion[10:15] = True
    lesion[60:62] = True
    z0, z1 = G.lesion_slab(lesion, 6, 32)
    assert z1 - z0 == 32 and z0 <= 10 and z1 >= 15 and not (z0 <= 60 < z1)
    lesion2 = np.zeros((100, 4, 4), bool)
    lesion2[40:44] = True
    assert G.lesion_slab(lesion2, 6, 32) == (34, 50)


def test_normal_slab_rule_gap_organ_and_length():
    lesion = np.zeros(120, bool)
    lesion[50:55] = True
    organ = np.zeros(120, bool)
    organ[20:100] = True
    rng = G.normal_slab(lesion, organ, 32, gap=8, min_len=12)
    assert rng is not None
    z0, z1 = rng
    assert z1 - z0 == 32
    assert organ[z0:z1].all()
    assert z1 <= 50 - 8 or z0 >= 55 + 8
    # below the lesion the organ fills a whole 32-slice window; the one nearest the lesion wins
    assert (z0, z1) == (63, 95)
    # the organ is only on slices inside the forbidden band → None
    organ2 = np.zeros(120, bool)
    organ2[45:60] = True
    assert G.normal_slab(lesion, organ2, 32) is None
    # organ on a few slices (≥ 4) of an allowed run → that window is used even if the organ is not on every slice
    organ3 = np.zeros(120, bool)
    organ3[70:75] = True
    z0, z1 = G.normal_slab(lesion, organ3, 32)
    assert z0 >= 63 and z1 - z0 == 32 and organ3[z0:z1].sum() == 5
    # a run shorter than min_len never qualifies
    lesion4 = np.zeros(30, bool)
    lesion4[10:12] = True
    assert G.normal_slab(lesion4, np.ones(30, bool), 32, gap=8, min_len=12) is None


# --------------------------------------------------------------------------- resampling and components
def test_downsample_inplane_keeps_aspect_and_never_upsamples():
    vol = np.random.default_rng(0).normal(size=(3, 300, 200)).astype(np.float32)
    mask = np.zeros((3, 300, 200), np.uint8)
    mask[:, 100:200, 50:150] = 2
    v, m, (sy, sx) = G.downsample_inplane(vol, mask, 144)
    assert v.shape == (3, 144, 96) and m.shape == v.shape
    assert abs(sy - 0.48) < 1e-9 and abs(sx - 0.48) < 1e-9
    assert set(np.unique(m)) <= {0, 2}
    v2, m2, s2 = G.downsample_inplane(vol[:, :100, :80], mask[:, :100, :80], 144)
    assert v2.shape == (3, 100, 80) and s2 == (1.0, 1.0)


def test_components_26_connected_and_min_size():
    m = np.zeros((10, 20, 20), bool)
    m[2:6, 2:6, 2:6] = True  # 64 voxels
    m[6, 6, 6] = True  # touches the cube only diagonally (26-connectivity joins it)
    m[8, 15, 15] = True  # a lone voxel (< 30)
    m[0:2, 12:18, 12:18] = True  # 72 voxels
    comps = G.components(m, 30)
    assert len(comps) == 2
    assert comps[0].sum() == 72 and comps[1].sum() == 65


def test_longest_inplane_diameter_of_20mm_sphere():
    comp = sphere((40, 40, 40), (20, 20.5, 20.5), 10.0)  # centre between voxels: 20 px edge to edge
    d, z = G.longest_inplane_diameter(comp, (1.0, 1.0))
    assert abs(d - 20.0) <= 1.0
    assert z in (19, 20)  # the two discs either side of the equator are identical
    comp2 = sphere((40, 40, 40), (20, 20, 20), 10.0)  # centre on a voxel: 21 px edge to edge
    d2, _ = G.longest_inplane_diameter(comp2, (1.0, 1.0))
    assert abs(d2 - 21.0) <= 0.6
    one = np.zeros((1, 5, 5), bool)
    one[0, 2, 2] = True
    assert G.longest_inplane_diameter(one, (0.7, 0.7)) == (0.7, 0)


def test_longest_inplane_diameter_respects_anisotropic_spacing():
    comp = np.zeros((3, 20, 20), bool)
    comp[1, 5:15, 5:7] = True  # 10 rows × 2 cols; with (sy, sx) = (2.0, 0.5) → ~20 mm tall
    d, z = G.longest_inplane_diameter(comp, (2.0, 0.5))
    assert z == 1 and 19.0 <= d <= 21.0


def test_sides_and_halves():
    assert G.side_of(10, 100) == "right"
    assert G.side_of(90, 100) == "left"
    assert G.side_of(52, 100) == "midline"
    r, lf, m = (G.half_mask(100, w) for w in ("right", "left", "midline"))
    assert (r | lf | m).all() and not (r & lf).any() and not (r & m).any()
    assert r[0] and lf[99] and m[50]


def test_thirds_and_zone_fractions():
    assert G.third_ranges(32) == {"superior": (0, 10), "mid": (10, 22), "inferior": (22, 32)}
    comp = np.zeros((30, 10, 10), bool)
    comp[12:18, 2:5, 7:9] = True
    fr = G.slab_third_fractions(comp)
    assert fr == {"superior": 0.0, "mid": 1.0, "inferior": 0.0}
    hf = G.half_fractions(comp)
    assert hf["left"] == 1.0


def test_organ_zone_mask_covers_embedded_lesion():
    organ = sphere((30, 60, 60), (15, 30, 30), 20.0)
    lesion = sphere((30, 60, 60), (15, 30, 30), 8.0)
    organ_only = organ & ~lesion  # as in MSD masks: the lesion voxels carry the lesion value, not the organ's
    zone = G.organ_zone_mask(organ_only, (1.0, 1.0, 1.0))
    assert G.overlap_fraction(lesion, zone) == 1.0
    far = sphere((30, 60, 60), (15, 10, 10), 3.0)
    assert G.overlap_fraction(far, zone) == 0.0


# --------------------------------------------------------------------------- pack format
def test_pack_round_trip_int16_and_uint8(tmp_path):
    rng = np.random.default_rng(3)
    vol = rng.integers(-1024, 3071, size=(5, 7, 9)).astype("<i2")
    mask = rng.integers(0, 4, size=(5, 7, 9)).astype(np.uint8)
    pack.write_gz(tmp_path / "v.i16.gz", vol)
    pack.write_gz(tmp_path / "m.u8.gz", mask)
    assert np.array_equal(pack.read_gz(tmp_path / "v.i16.gz", "<i2", (5, 7, 9)), vol)
    assert np.array_equal(pack.read_gz(tmp_path / "m.u8.gz", "u1", (5, 7, 9)), mask)
    with pytest.raises(ValueError):
        pack.read_gz(tmp_path / "v.i16.gz", "<i2", (5, 7, 8))


def test_to_int16_clips_ct():
    v = np.array([[[-5000.0, 0.0, 9000.0]]], np.float32)
    out = pack.to_int16(v, "ct")
    assert out.dtype == np.dtype("<i2") and out.tolist() == [[[-1024, 0, 3071]]]


def test_mr_window_percentiles():
    v = np.zeros((1, 10, 100), np.float32)
    v[0, :, :] = np.linspace(1, 1000, 100)[None]
    wc, ww = pack.mr_window(v)
    assert 490 < wc < 510 and 960 < ww < 1000


def test_zones_document_shape():
    doc = pack.zones_document(
        (32, 120, 144),
        (2.5, 0.9, 0.9),
        {"pancreas": [1]},
        {"right_half": "half:right", "left_half": "half:left", "midline_volume": "half:midline"},
        organ_dilation_mm=5.0,
        midline_frac=0.1,
    )
    assert doc["shape"] == [32, 120, 144] and doc["spacing"] == [2.5, 0.9, 0.9]
    assert doc["zones"]["pancreas"] == [1]
    assert doc["zones"]["superior_slab"] == "slab:superior" and doc["zones"]["mid_slab"] == "slab:mid"
    assert doc["zones"]["inferior_slab"] == "slab:inferior" and doc["zones"]["left_half"] == "half:left"
    assert doc["rules"]["organ_dilation_mm"] == 5.0 and doc["rules"]["patient_right_is_low_x"] is True


# --------------------------------------------------------------------------- tar index
def test_tar_walk_matches_tarfile_offsets():
    buf = io.BytesIO()
    payloads = {"Task/dataset.json": b"{}", "Task/imagesTr/a.nii.gz": bytes(range(256)) * 5, "Task/._x": b"\0" * 10}
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        d = tarfile.TarInfo("Task/")
        d.type = tarfile.DIRTYPE
        tf.addfile(d)
        for name, data in payloads.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    members = list(tarindex.walk(lambda off, n: raw[off : off + n], total=len(raw)))
    assert [m.name for m in members] == ["Task/", *payloads]
    for m in members[1:]:
        assert raw[m.offset : m.offset + m.size] == payloads[m.name]
    assert members[0].typeflag == "5" and not members[0].is_file
    assert members[-1].is_appledouble and not members[1].is_appledouble
