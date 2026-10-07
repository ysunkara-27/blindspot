"""Tiny synthetic CT/MR volumes for tests (never the real dataset). Writes pipeline/tests/fixtures/synthetic/{cases_msd.jsonl,volumes,masks}.

Run: uv run python -m pipeline.tests.fixtures.make_volumetric_fixtures
Pack format = docs/VOLUMETRIC_PLAN.md: volumes/<id>.i16.gz int16 little-endian (z,y,x), masks/<id>.u8.gz uint8 same shape.
Patient RIGHT is at low x (image left), as in the X-ray convention. Slice 0 = most superior.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np

from shared.contracts import Case, Component, Finding, Geometry, Measure, Provenance, VolumeInfo, Window

ROOT = Path(__file__).resolve().parent / "synthetic"
NZ, NY, NX = 16, 64, 64
SPACING = (3.0, 1.5, 1.5)  # mm


def sphere(center: tuple[float, float, float], r: float) -> np.ndarray:
    z, y, x = np.mgrid[0:NZ, 0:NY, 0:NX]
    cz, cy, cx = center
    return ((z - cz) * SPACING[0]) ** 2 + ((y - cy) * SPACING[1]) ** 2 + ((x - cx) * SPACING[2]) ** 2 <= r * r


def write_gz(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(np.ascontiguousarray(arr).tobytes())


def finding_from_mask(
    case_id: str, n: int, label: str, mask: np.ndarray, values: list[int], components=None
) -> Finding:
    zs, ys, xs = np.where(mask)
    z0, z1 = int(zs.min()), int(zs.max())
    # longest in-plane diameter on any axial slice (approx: max extent in mm)
    best, best_z = 0.0, z0
    for z in range(z0, z1 + 1):
        yy, xx = np.where(mask[z])
        if len(xx) == 0:
            continue
        d = max((xx.max() - xx.min() + 1) * SPACING[2], (yy.max() - yy.min() + 1) * SPACING[1])
        if d > best:
            best, best_z = d, z
    cx, cy, cz = float(xs.mean()), float(ys.mean()), float(zs.mean())
    return Finding(
        finding_id=f"{case_id}#F{n}",
        label=label,
        source_label=label,
        kind="focal",
        geometry=Geometry(
            kind="bbox", bbox=(float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
        ),
        centroid=(cx, cy),
        area_frac=float(mask[int(round(cz))].sum() / (NY * NX)),
        label_value=values[0],
        label_values=values,
        centroid3=(cx, cy, cz),
        slice_range=(z0, z1),
        measure=Measure(long_mm=round(best, 1), slice=best_z),
        components=components,
        volume_mm3=float(mask.sum() * SPACING[0] * SPACING[1] * SPACING[2]),
        side="right" if cx < NX / 2 else "left",
        zones=["mid_slab"],
        primary_zone="mid_slab",
        relative_location="middle slices of the volume",
    )


def main() -> None:
    rng = np.random.default_rng(1)
    prov_ct = Provenance(dataset="synthetic", segmented_by="a test script", grade="unknown")
    cases: list[Case] = []

    def make(
        case_id: str,
        modality: str,
        region: str,
        organ: np.ndarray | None,
        lesions: list[tuple[np.ndarray, int]],
        labels: dict[str, str],
        findings_spec,
        is_normal: bool,
        window=(50.0, 400.0),
    ):
        vol = rng.normal(0, 25, (NZ, NY, NX)).astype(np.float32)
        body = sphere((NZ / 2, NY / 2, NX / 2), 44)
        vol[~body] = -1000
        vol[body] += 40
        mask = np.zeros((NZ, NY, NX), np.uint8)
        if organ is not None:
            vol[organ] += 30
            mask[organ] = 1
        for m, v in lesions:
            vol[m] += 120
            mask[m] = v
        vol = np.clip(vol, -1024, 3071).astype("<i2")
        write_gz(ROOT / "volumes" / f"{case_id}.i16.gz", vol)
        write_gz(ROOT / "masks" / f"{case_id}.u8.gz", mask)
        findings = [
            finding_from_mask(case_id, i + 1, lab, m, vals, comps)
            for i, (lab, m, vals, comps) in enumerate(findings_spec)
        ]
        cases.append(
            Case(
                case_id=case_id,
                source="synthetic",
                source_split="synthetic",
                split="practice",
                modality=modality,
                body_region=region,
                image_path=f"previews/{case_id}_axial.png",
                width=NX,
                height=NY,
                is_normal=is_normal,
                findings=findings,
                volume=VolumeInfo(
                    shape=(NZ, NY, NX),
                    spacing=SPACING,
                    window=Window(wc=window[0], ww=window[1]),
                    data_path=f"volumes/{case_id}.i16.gz",
                    mask_path=f"masks/{case_id}.u8.gz",
                    labels=labels,
                    sequence="T1c" if modality == "mr" else None,
                ),
                provenance=prov_ct,
                license_tag="synthetic",
                attribution="synthetic test fixture — not a scan",
                qa_flags=["synthetic"],
            )
        )

    pancreas = sphere((8, 36, 30), 18)
    tumour = sphere((8, 36, 24), 6)
    make(
        "vol_001",
        "ct",
        "abdomen",
        pancreas,
        [(tumour, 2)],
        {"1": "pancreas", "2": "pancreatic_tumour"},
        [("pancreatic_tumour", tumour, [2], None)],
        False,
    )
    vessels = sphere((7, 30, 20), 10)
    t1, t2 = sphere((5, 24, 18), 5), sphere((11, 40, 22), 7)
    make(
        "vol_002",
        "ct",
        "abdomen",
        vessels,
        [(t1, 2), (t2, 2)],
        {"1": "hepatic_vessels", "2": "liver_tumour"},
        [("liver_tumour", t1, [2], None), ("liver_tumour", t2, [2], None)],
        False,
        window=(80.0, 180.0),
    )
    oedema, core, enh = sphere((8, 28, 40), 14), sphere((8, 28, 40), 8), sphere((8, 28, 40), 4)
    make(
        "vol_003",
        "mr",
        "brain",
        None,
        [(oedema, 1), (core, 2), (enh, 3)],
        {"1": "brain_tumour", "2": "brain_tumour", "3": "brain_tumour"},
        [
            (
                "brain_tumour",
                oedema | core | enh,
                [1, 2, 3],
                [
                    Component(name="oedema", label_value=1),
                    Component(name="tumour core", label_value=2),
                    Component(name="enhancing tumour", label_value=3),
                ],
            )
        ],
        False,
        window=(300.0, 600.0),
    )
    make("vol_004", "ct", "abdomen", sphere((8, 36, 30), 18), [], {"1": "pancreas"}, [], True)
    (ROOT / "previews").mkdir(parents=True, exist_ok=True)
    import cv2

    for c in cases:
        with gzip.open(ROOT / c.volume.data_path, "rb") as fh:
            v = np.frombuffer(fh.read(), dtype="<i2").reshape(NZ, NY, NX)
        wc, ww = c.volume.window.wc, c.volume.window.ww
        img = np.clip((v[NZ // 2].astype(np.float32) - (wc - ww / 2)) / ww * 255, 0, 255).astype(np.uint8)
        cv2.imwrite(str(ROOT / c.image_path), img)
    (ROOT / "cases_msd.jsonl").write_text("\n".join(c.model_dump_json() for c in cases) + "\n")
    print(f"wrote {len(cases)} synthetic volumetric cases to {ROOT}")


if __name__ == "__main__":
    main()
