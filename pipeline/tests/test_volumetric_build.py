"""Case assembly tests (pipeline/volumetric/build.py, msd.py, run.py) on synthetic volumes written to tmp. No network."""

from __future__ import annotations

import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from pipeline.volumetric import build as B
from pipeline.volumetric import msd, pack, run
from pipeline.volumetric.msd import RawVolume, TaskSpec
from shared.contracts import Case

SPACING = (2.5, 0.8, 0.8)  # (sz, sy, sx) mm


def sphere(shape, centre, r_mm, spacing=SPACING):
    z, y, x = np.mgrid[0 : shape[0], 0 : shape[1], 0 : shape[2]]
    cz, cy, cx = centre
    return ((z - cz) * spacing[0]) ** 2 + ((y - cy) * spacing[1]) ** 2 + ((x - cx) * spacing[2]) ** 2 <= r_mm**2


def pancreas_spec() -> TaskSpec:
    return TaskSpec(
        task="Task07_Pancreas",
        short="pan",
        modality="ct",
        body_region="abdomen",
        lesion_label="pancreatic_tumour",
        lesion_values=(2,),
        union=False,
        anatomy={1: "pancreas"},
        window=(50.0, 400.0),
        side=144,
    )


def brain_spec() -> TaskSpec:
    return TaskSpec(
        task="Task01_BrainTumour",
        short="brain",
        modality="mr",
        body_region="brain",
        lesion_label="brain_tumour",
        lesion_values=(1, 2, 3),
        union=True,
        anatomy={},
        window=None,
        side=144,
        sequence="T1c",
        target_z_mm=2.0,
        measure_values=(2, 3),
        dataset_modality={"0": "FLAIR", "1": "T1w", "2": "t1gd", "3": "T2w"},
    )


PROV = {
    "dataset": "Medical Segmentation Decathlon, Task07 Pancreas",
    "segmented_by": "an abdominal radiologist (single reader)",
    "readers": 1,
    "institution": "MSKCC",
    "license": "CC BY-SA 4.0",
    "citation": "Antonelli M et al. Nat Commun 2022.",
    "url": "http://medicaldecathlon.com/",
    "grade": "radiologist",
}


def synthetic_ct(nz=120, ny=320, nx=400, seed=0):
    """Body ellipse in air, a 'pancreas' sphere, two tumours (one inside the organ at the patient's left, one far
    right), lesions on slices ~60..70 only. Returns (vol, label)."""
    rng = np.random.default_rng(seed)
    vol = rng.normal(-1000, 10, (nz, ny, nx)).astype(np.float32)
    z, y, x = np.mgrid[0:nz, 0:ny, 0:nx]
    body = ((y - ny / 2) / (ny * 0.4)) ** 2 + ((x - nx / 2) / (nx * 0.42)) ** 2 <= 1
    vol[body] = rng.normal(40, 15, int(body.sum()))
    table = (y > ny - 12) & (x > 40) & (x < nx - 40)
    vol[table] = 200
    label = np.zeros((nz, ny, nx), np.uint8)
    organ = sphere((nz, ny, nx), (65, 170, 230), 40.0)
    organ |= (((y - 170) * 0.8) ** 2 + ((x - 230) * 0.8) ** 2 <= 15**2) & (z >= 15) & (z < 115)  # a long tail along z
    label[organ] = 1
    vol[organ] += 30
    t_left = sphere((nz, ny, nx), (65, 170, 245), 12.0)  # inside the organ, patient's left (high x)
    t_right = sphere((nz, ny, nx), (63, 150, 60), 8.0)  # far patient-right, outside the organ
    for t in (t_left, t_right):
        label[t] = 2
        vol[t] += 120
    return vol, label


def raw_ct(name="pancreas_001") -> RawVolume:
    vol, label = synthetic_ct()
    return RawVolume(name=name, vol=vol, label=label, spacing=SPACING, channel=None, original_shape=vol.shape)


# --------------------------------------------------------------------------- lesion case
@pytest.fixture(scope="module")
def pancreas_case():
    spec = pancreas_spec()
    b = B.build_lesion_case(spec, raw_ct(), "msd_pan_0001", PROV, B.BuildOptions())
    assert b is not None
    return spec, b


def test_lesion_case_validates_and_has_two_findings(pancreas_case):
    _, b = pancreas_case
    Case.model_validate_json(b.case.model_dump_json())
    c = b.case
    assert c.modality == "ct" and c.body_region == "abdomen" and c.source == "msd" and not c.is_normal
    assert len(c.findings) == 2, "two separate tumours → two findings (satisfaction of search)"
    assert [f.finding_id for f in c.findings] == ["msd_pan_0001#F1", "msd_pan_0001#F2"]
    assert c.provenance is not None and c.provenance.badge.startswith("Segmented by an abdominal radiologist")
    assert c.volume is not None and c.volume.labels == {"1": "pancreas", "2": "pancreatic_tumour"}
    assert c.zones_path == "zones3d/msd_pan_0001.json" and c.image_path == "previews/msd_pan_0001_axial.png"
    assert c.width == c.volume.shape[2] and c.height == c.volume.shape[1]
    assert c.pixel_spacing_mm is None


def test_slab_shape_crop_and_spacing_carried_exactly(pancreas_case):
    _, b = pancreas_case
    v = b.case.volume
    assert v is not None
    nz, ny, nx = v.shape
    assert nz <= 32 and max(ny, nx) == 144 and b.vol.shape == tuple(v.shape) and b.mask.shape == tuple(v.shape)
    assert b.vol.dtype == np.dtype("<i2") and b.mask.dtype == np.uint8
    # body crop happened (original in-plane 320×400 → body ≈ 256×336 + margins) and spacing scaled by the exact factor
    assert v.original_shape == [120, 320, 400]
    assert v.crop_origin is not None and v.crop_origin[1] > 0 and v.crop_origin[2] > 0
    assert abs(v.spacing[0] - 2.5) < 1e-9
    from pipeline.volumetric import geometry as G

    z0 = v.crop_origin[0]
    raw = raw_ct()
    box = G.body_crop(raw.vol[z0 : z0 + nz], raw.label[z0 : z0 + nz], "ct")
    assert box is not None and (box.y0, box.x0) == (v.crop_origin[1], v.crop_origin[2])
    assert abs(v.spacing[2] - 0.8 * (box.x1 - box.x0) / nx) < 1e-4
    assert abs(v.spacing[1] - 0.8 * (box.y1 - box.y0) / ny) < 1e-4
    assert int(b.vol.min()) >= -1024 and int(b.vol.max()) <= 3071
    assert "body_crop_abandoned" not in b.case.qa_flags
    # the slab brackets every lesion slice by the margin (6)
    lesion_z = np.flatnonzero((raw.label == 2).reshape(120, -1).any(axis=1))
    assert v.crop_origin[0] == lesion_z.min() - 6 and v.crop_origin[0] + nz == lesion_z.max() + 7


def test_finding_measurements_and_geometry(pancreas_case):
    _, b = pancreas_case
    big, small = b.case.findings  # largest component first
    assert big.measure is not None and abs(big.measure.long_mm - 24.0) <= 1.5
    assert small.measure is not None and abs(small.measure.long_mm - 16.0) <= 1.5
    assert big.volume_mm3 is not None and abs(big.volume_mm3 - 4 / 3 * np.pi * 12**3) / (4 / 3 * np.pi * 12**3) < 0.15
    assert big.slice_range is not None and big.slice_range[0] < big.measure.slice <= big.slice_range[1]
    assert big.centroid3 is not None and big.centroid3[2] == pytest.approx(
        (big.slice_range[0] + big.slice_range[1]) / 2, abs=1
    )
    assert big.geometry.kind == "polygon" and big.geometry.polygon and len(big.geometry.polygon) <= 60
    x0, y0, x1, y1 = big.geometry.bbox
    assert x0 <= big.centroid[0] <= x1 and y0 <= big.centroid[1] <= y1
    assert all(x0 - 1 <= px <= x1 + 1 and y0 - 1 <= py <= y1 + 1 for px, py in big.geometry.polygon)
    assert 0 < big.area_frac < 0.05
    assert big.label_value == 2 and big.label_values == [2] and big.components is None
    assert big.contrast is not None and big.contrast > 0.1
    assert big.readers == 1
    # the packed mask carries lesion voxels where the finding says it is
    z0, z1 = big.slice_range
    assert (b.mask[z0 : z1 + 1, int(y0) : int(y1) + 1, int(x0) : int(x1) + 1] == 2).any()


def test_sides_zones_and_relative_location(pancreas_case):
    _, b = pancreas_case
    big, small = b.case.findings
    assert big.side == "left" and small.side == "right", "patient right is low x"
    assert big.centroid[0] > b.case.width / 2 > small.centroid[0]
    assert big.primary_zone == "pancreas" and "pancreas" in big.zones and "mid_slab" in big.zones
    assert big.relative_location == "inside the pancreas, middle slices, patient's left of midline"
    assert "pancreas" not in small.zones and small.primary_zone == "mid_slab"
    assert small.relative_location.startswith("outside the labelled pancreas")
    assert small.relative_location.endswith("patient's right of midline")
    for f in b.case.findings:
        assert "cm" not in (f.relative_location or "")


def test_zones_file_document(pancreas_case):
    _, b = pancreas_case
    doc = b.zones_doc
    assert doc["shape"] == list(b.case.volume.shape) and doc["spacing"] == list(b.case.volume.spacing)
    assert doc["zones"]["pancreas"] == [1]
    assert doc["zones"]["superior_slab"] == "slab:superior"
    assert doc["zones"]["right_half"] == "half:right" and doc["zones"]["midline_volume"] == "half:midline"
    assert "brain_left" not in doc["zones"]
    assert set(doc) == {"version", "shape", "spacing", "zones", "rules"}


def test_preview_is_the_measure_slice_with_patient_right_marker(pancreas_case):
    _, b = pancreas_case
    assert b.preview.shape[:2] == b.vol.shape[1:] and b.preview.shape[2] == 3


# --------------------------------------------------------------------------- brain union
def test_brain_union_is_one_finding_with_components():
    spec = brain_spec()
    nz, ny, nx = 80, 200, 200
    rng = np.random.default_rng(1)
    vol = np.zeros((nz, ny, nx), np.float32)
    brain = sphere((nz, ny, nx), (40, 100, 100), 70.0, (2.0, 1.0, 1.0))
    vol[brain] = rng.normal(600, 60, int(brain.sum()))
    label = np.zeros((nz, ny, nx), np.uint8)
    oedema = sphere((nz, ny, nx), (40, 90, 140), 20.0, (2.0, 1.0, 1.0))
    core = sphere((nz, ny, nx), (40, 90, 140), 11.0, (2.0, 1.0, 1.0))
    enh = sphere((nz, ny, nx), (40, 90, 140), 5.0, (2.0, 1.0, 1.0))
    satellite = sphere((nz, ny, nx), (44, 120, 60), 6.0, (2.0, 1.0, 1.0))  # a disconnected oedema blob
    label[oedema] = 1
    label[core] = 2
    label[enh] = 3
    label[satellite] = 1
    vol[label > 0] += 300
    raw = RawVolume("BRATS_001", vol, label, (2.0, 1.0, 1.0), channel=2, original_shape=(nz, ny, nx))
    b = B.build_lesion_case(spec, raw, "msd_brain_0001", PROV, B.BuildOptions())
    assert b is not None
    c = b.case
    Case.model_validate_json(c.model_dump_json())
    assert c.modality == "mr" and c.body_region == "brain" and c.volume.sequence == "T1c"
    assert len(c.findings) == 1
    f = c.findings[0]
    assert f.label == "brain_tumour" and f.label_values == [1, 2, 3]
    assert [(k.name, k.label_value) for k in f.components] == [
        ("oedema", 1),
        ("tumour core", 2),
        ("enhancing tumour", 3),
    ]
    assert f.measure is not None and abs(f.measure.long_mm - 22.0) <= 2.0, "calipers on core + enhancing, not oedema"
    assert f.volume_mm3 is not None and f.volume_mm3 > 4 / 3 * np.pi * 20**3 * 0.9, "the finding itself includes oedema"
    assert (
        f.side == "left"
        and f.primary_zone == "brain_left"
        and f.relative_location.startswith("left cerebral hemisphere")
    )
    assert c.volume.labels == {"1": "brain_tumour", "2": "brain_tumour", "3": "brain_tumour"}
    assert b.zones_doc["zones"]["brain_left"] == "half:left" and "pancreas" not in b.zones_doc["zones"]
    assert 0 < c.volume.window.ww and set(np.unique(b.mask)) <= {0, 1, 2, 3}
    assert "mr_intensity_scaled" not in c.qa_flags


def test_mr_intensity_scaling_recorded():
    assert B.mr_scale(np.array([0.0, 0.5, 0.9], np.float32)) == 1000.0
    assert B.mr_scale(np.array([0.0, 70000.0], np.float32)) == pytest.approx(32767 / 70000)
    assert B.mr_scale(np.array([0.0, 2000.0], np.float32)) == 1.0


# --------------------------------------------------------------------------- normals
def test_normal_slab_case_rule():
    spec = pancreas_spec()
    raw = raw_ct()
    nb = B.build_normal_case(spec, raw, "msd_pan_0001n", PROV, B.BuildOptions())
    assert nb is not None
    c = nb.case
    Case.model_validate_json(c.model_dump_json())
    assert c.is_normal and c.findings == [] and "lesion_free_slab" in c.qa_flags
    assert set(np.unique(nb.mask)) <= {0, 1}, "mask keeps only anatomy values"
    assert c.volume.labels == {"1": "pancreas"}
    z0, z1 = int(c.features["normal_slab_z0"]), int(c.features["normal_slab_z1"])
    lesion_z = np.flatnonzero(np.isin(raw.label, (2,)).reshape(raw.label.shape[0], -1).any(axis=1))
    assert z1 <= lesion_z.min() - 8 or z0 >= lesion_z.max() + 8
    assert (raw.label[z0:z1] == 1).reshape(z1 - z0, -1).any(axis=1).all(), "organ present on every slice"
    assert c.volume.crop_origin[0] == z0 and c.volume.shape[0] == z1 - z0 <= 32
    # a volume whose lesion spans everything has no normal slab
    raw2 = raw_ct()
    raw2.label[:, 100:110, 100:110] = 2
    assert B.build_normal_case(spec, raw2, "x", PROV, B.BuildOptions()) is None


# --------------------------------------------------------------------------- difficulty
def test_assign_difficulty_zscores_and_prior(pancreas_case):
    _, b = pancreas_case
    nb = B.build_normal_case(pancreas_spec(), raw_ct(), "msd_pan_0001n", PROV, B.BuildOptions())
    # equalise contrast so the comparison is about size and zone hardness (two samples would otherwise give ±1 z)
    lesion_in = b.case.model_copy(
        update={"findings": [f.model_copy(update={"contrast": 0.3}) for f in b.case.findings]}
    )
    cases = B.assign_difficulty([lesion_in, nb.case])
    lesion, normal = cases
    assert normal.difficulty_prior == 0.0
    assert all(f.difficulty is not None and -2.5 <= f.difficulty <= 2.5 for f in lesion.findings)
    assert lesion.difficulty_prior == max(f.difficulty for f in lesion.findings)
    big, small = lesion.findings
    assert small.difficulty > big.difficulty, "smaller lesion → harder"


# --------------------------------------------------------------------------- end to end on synthetic NIfTIs
def _write_nifti(path: Path, arr_zyx: np.ndarray, spacing, channels: int | None = None) -> None:
    """Write our (z,y,x) array as a NIfTI in LPS-style storage (axes flipped), to exercise the reorientation."""
    sz, sy, sx = spacing
    ras = arr_zyx[::-1, ::-1, :].transpose(2, 1, 0)  # back to (x,y,z) RAS
    stored = ras[::-1, ::-1, :]  # store as LPS: i → right, j → posterior
    if channels is not None:
        stored = np.stack([np.zeros_like(stored)] * 2 + [stored] + [np.zeros_like(stored)], axis=-1)
    aff = np.diag([-sx, -sy, sz, 1.0])
    aff[0, 3] = sx * (stored.shape[0] - 1)
    aff[1, 3] = sy * (stored.shape[1] - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(stored, aff), str(path))


def test_end_to_end_run_on_synthetic_raw(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    out = tmp_path / "processed"
    vol, label = synthetic_ct()
    t = raw_dir / "Task07_Pancreas"
    _write_nifti(t / "imagesTr" / "pancreas_007.nii.gz", vol, SPACING)
    _write_nifti(t / "labelsTr" / "pancreas_007.nii.gz", label, SPACING)
    (t / "dataset.json").write_text(
        json.dumps({"labels": {"0": "background", "1": "pancreas", "2": "cancer"}, "modality": {"0": "CT"}})
    )
    monkeypatch.setattr(msd, "RAW_DIR", raw_dir)
    monkeypatch.setitem(msd.TASK_TABLE["Task07_Pancreas"], "flip", "")  # the synthetic header is correct
    monkeypatch.setattr(run, "QA_DIR", tmp_path / "qa")
    monkeypatch.setattr(run, "LOG_DIR", tmp_path / "logs")
    assert (
        run.main(
            [
                "--tasks",
                "Task07_Pancreas",
                "--limit",
                "5",
                "--no-fetch",
                "--out",
                str(out),
                "--normal-frac",
                "0.5",
                "--bench",
                "1",
            ]
        )
        == 0
    )
    lines = (out / "cases_msd.jsonl").read_text().splitlines()
    cases = [Case.model_validate_json(ln) for ln in lines]
    assert [c.case_id for c in cases] == ["msd_pan_0007", "msd_pan_0007n"]
    lesion, normal = cases
    assert lesion.split == "bench" and normal.split == "practice"
    assert len(lesion.findings) == 2 and lesion.findings[0].side == "left"
    # files exist and round-trip
    for c in cases:
        v = pack.read_gz(out / c.volume.data_path, "<i2", tuple(c.volume.shape))
        m = pack.read_gz(out / c.volume.mask_path, "u1", tuple(c.volume.shape))
        assert v.shape == m.shape == tuple(c.volume.shape)
        assert (out / c.image_path).exists() and (out / c.zones_path).exists()
        doc = json.loads((out / c.zones_path).read_text())
        assert doc["shape"] == list(c.volume.shape)
        size = (out / c.volume.data_path).stat().st_size + (out / c.volume.mask_path).stat().st_size
        assert 100_000 < size < 1_500_000
    stats = json.loads((out / "volumetric_stats.json").read_text())["Task07_Pancreas"]
    assert stats["cases"] == 2 and stats["normals"] == 1 and stats["findings_per_label"] == {"pancreatic_tumour": 2}
    assert (tmp_path / "qa" / "volumetric_contact_sheet.png").exists()
    # orientation survived the LPS storage: the organ-embedded tumour is on the patient's left (high x)
    assert lesion.findings[0].centroid[0] > lesion.width / 2


def test_task_specs_from_taxonomy_and_provenance():
    specs = msd.load_task_specs()
    assert specs["Task07_Pancreas"].lesion_values == (2,) and specs["Task07_Pancreas"].anatomy == {1: "pancreas"}
    assert specs["Task01_BrainTumour"].lesion_values == (1, 2, 3) and specs["Task01_BrainTumour"].union
    assert specs["Task08_HepaticVessel"].anatomy == {1: "hepatic_vessels"}
    assert specs["Task08_HepaticVessel"].mask_labels == {"1": "hepatic_vessels", "2": "liver_tumour"}
    assert msd.channel_index(brain_spec()) == 2
    for t in ("Task07_Pancreas", "Task08_HepaticVessel", "Task01_BrainTumour"):
        assert msd.load_provenance(t)["license"] == "CC BY-SA 4.0"


def test_header_flips_apply_after_reorientation():
    arr = np.zeros((2, 3, 4), np.uint8)
    arr[0, 0, 0] = 1
    assert msd.apply_flips(arr, "")[0, 0, 0] == 1
    assert msd.apply_flips(arr, "x")[0, 0, 3] == 1
    assert msd.apply_flips(arr, "xy")[0, 2, 3] == 1
    assert msd.apply_flips(arr, "z")[1, 0, 0] == 1
    with pytest.raises(ValueError):
        msd.apply_flips(arr, "q")
    # Task07's RAS header mirrors left/right (verified on the cardiac apex, aorta, stomach and liver): x is flipped
    assert msd.load_task_specs()["Task07_Pancreas"].flip == "x"
    assert msd.load_task_specs()["Task08_HepaticVessel"].flip == "x"
    assert msd.load_task_specs()["Task01_BrainTumour"].flip == ""


def test_vessel_map_location_phrase():
    spec = TaskSpec(
        task="Task08_HepaticVessel",
        short="hep",
        modality="ct",
        body_region="abdomen",
        lesion_label="liver_tumour",
        lesion_values=(2,),
        union=False,
        anatomy={1: "hepatic_vessels"},
        window=(80.0, 180.0),
        side=144,
    )
    b = B.build_lesion_case(spec, raw_ct(), "msd_hep_0001", PROV, B.BuildOptions())
    assert b is not None
    big, small = b.case.findings
    assert (
        big.relative_location
        == "in the liver, touching the labelled hepatic vessels, middle slices, patient's left of midline"
    )
    assert small.relative_location.startswith("in the liver, away from the labelled hepatic vessels")
    assert big.primary_zone == "hepatic_vessels" and small.primary_zone == "mid_slab"
    assert b.case.features["z_stride"] == 1.0 and "header_flip_x" not in b.case.features


def test_z_decimation_rule():
    assert msd.z_stride_for(1.0, 2.0) == 2
    assert msd.z_stride_for(2.5, 2.5) == 1
    assert msd.z_stride_for(5.0, 2.5) == 1
    assert msd.z_stride_for(0.8, 2.5) == 3
    assert msd.z_stride_for(1.5, 2.5) == 2
    arr = np.arange(10)[:, None, None]
    assert msd.decimate_z(arr, 3).ravel().tolist() == [0, 3, 6, 9]
    assert msd.decimate_z(arr, 1) is arr
