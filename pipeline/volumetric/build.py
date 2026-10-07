"""Turn one raw MSD volume into Blindspot slab cases: a lesion slab (findings) and, when the rule allows, a
lesion-free slab (normal). Pure given a RawVolume + TaskSpec; file writing happens in run.py.

Finding rule: lesion mask values → 26-connected components ≥ 30 voxels → one Finding each (brain: ONE finding =
union of values 1+2+3 with components). Anatomy values → zones, never findings.
Measurements and geometry are computed on the FULL-RESOLUTION cropped slab, then scaled into packed coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from pipeline.volumetric import geometry as G
from pipeline.volumetric import pack
from pipeline.volumetric.msd import RawVolume, TaskSpec
from shared.contracts import Case, Component, Finding, Geometry, Measure, Provenance, VolumeInfo, Window

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_AREAS_PATH = REPO_ROOT / "config" / "review_areas.yaml"

FLAG_LESION_FREE = "lesion_free_slab"
FLAG_CROP_ABANDONED = "body_crop_abandoned"
FLAG_FINDING_CLIPPED = "finding_clipped_by_slab"
FLAG_FINDING_LOST = "finding_lost_in_downsample"
FLAG_SMALL_DROPPED = "small_components_dropped"
FLAG_MR_SCALED = "mr_intensity_scaled"
BRAIN_COMPONENTS = {1: "oedema", 2: "tumour core", 3: "enhancing tumour"}
THIRD_WORDS = {"superior": "upper", "mid": "middle", "inferior": "lower"}
HALF_ZONE = {"right": "right_half", "left": "left_half", "midline": "midline_volume"}
BRAIN_HALF_ZONE = {"right": "brain_right", "left": "brain_left", "midline": "brain_midline"}
VESSEL_ZONES = {"hepatic_vessels"}
ORGAN_OF_VESSELS = {"hepatic_vessels": "in the liver, "}


@dataclass
class BuildOptions:
    margin: int = 6
    vol_slices: int = 32
    vol_side: int | None = None  # None → task default
    min_component_voxels: int = G.MIN_COMPONENT_VOXELS


@dataclass
class Built:
    case: Case
    vol: np.ndarray  # int16 (z,y,x)
    mask: np.ndarray  # uint8
    zones_doc: dict
    preview: np.ndarray  # BGR
    bytes_estimate: int = 0
    contrast: dict[str, float] = field(default_factory=dict)


def load_zone_config(path: Path = REVIEW_AREAS_PATH) -> dict[str, dict]:
    return yaml.safe_load(Path(path).read_text())["volumetric"]["zones"]


def zone_human(zcfg: dict[str, dict], zone_id: str) -> str:
    return str(zcfg.get(zone_id, {}).get("human", zone_id.replace("_", " ")))


def zone_hardness(zcfg: dict[str, dict], zone_id: str | None) -> float:
    return float(zcfg.get(zone_id or "", {}).get("hardness", 0.5))


# --------------------------------------------------------------------------- intensities
def mr_scale(vol: np.ndarray) -> float:
    """Factor bringing MR floats into int16 range: shrink if the peak exceeds int16, expand ×1000 if the data
    look normalised (peak < 100). 1.0 otherwise."""
    mx = float(np.nanmax(vol)) if vol.size else 0.0
    if mx > 32767:
        return 32767.0 / mx
    if 0 < mx < 100:
        return 1000.0
    return 1.0


def slab_window(spec: TaskSpec, vol: np.ndarray) -> tuple[float, float]:
    return spec.window if spec.window is not None else pack.mr_window(vol)


# --------------------------------------------------------------------------- location text
def _third_phrase(fracs: dict[str, float]) -> tuple[list[str], str]:
    hit = [k for k in ("superior", "mid", "inferior") if fracs[k] >= G.ZONE_OVERLAP]
    if not hit:
        hit = [max(fracs, key=fracs.get)]  # type: ignore[arg-type]
    words = [THIRD_WORDS[k] for k in hit]
    text = (" and ".join(words) if len(words) <= 2 else "upper, middle and lower") + " slices"
    return [f"{k}_slab" for k in hit], text


def locate(
    spec: TaskSpec,
    comp: np.ndarray,
    organ_zones: dict[str, np.ndarray],
    zcfg: dict[str, dict],
) -> tuple[list[str], str, str, str]:
    """(zones, primary_zone, side, relative_location) for one component on the full-res cropped slab."""
    cx = float(np.nonzero(comp)[2].mean())
    side = G.side_of(cx, comp.shape[2])
    third_zones, third_text = _third_phrase(G.slab_third_fractions(comp))
    zones: list[str] = []
    parts: list[str] = []
    primary: str | None = None
    if spec.body_region == "brain":
        hf = G.half_fractions(comp)
        hemis = [h for h in ("right", "left", "midline") if hf[h] >= G.ZONE_OVERLAP]
        if hf["right"] >= 0.3 and hf["left"] >= 0.3:
            parts.append("both cerebral hemispheres, crossing the midline")
        else:
            best = max(hf, key=hf.get)  # type: ignore[arg-type]
            parts.append(zone_human(zcfg, BRAIN_HALF_ZONE[best]))
        zones += [BRAIN_HALF_ZONE[h] for h in hemis] or [BRAIN_HALF_ZONE[max(hf, key=hf.get)]]  # type: ignore[arg-type]
        primary = zones[0]
    else:
        best_organ, best_frac = None, -1.0
        for zid, zmask in organ_zones.items():
            f = G.overlap_fraction(comp, zmask)
            if f >= G.ZONE_OVERLAP:
                zones.append(zid)
            if f > best_frac:
                best_organ, best_frac = zid, f
        if best_organ is not None:
            human = zone_human(zcfg, best_organ)
            if best_organ in VESSEL_ZONES:  # a vessel map, not an organ: every Task08 tumour is hepatic by definition
                prefix = ORGAN_OF_VESSELS.get(best_organ, "")
                rel = "touching the labelled" if best_frac >= G.ZONE_OVERLAP else "away from the labelled"
                parts.append(f"{prefix}{rel} {human}")
            elif best_frac >= 0.5:
                parts.append(f"inside the {human}")
            elif best_frac >= G.ZONE_OVERLAP:
                parts.append(f"at the edge of the {human}")
            else:
                parts.append(f"outside the labelled {human}")
        if zones:
            primary = zones[0]
    zones += third_zones
    parts.append(third_text)
    if primary is None:
        primary = third_zones[0]
    if spec.body_region != "brain":
        parts.append(
            {"right": "patient's right of midline", "left": "patient's left of midline", "midline": "near the midline"}[
                side
            ]
        )
    return zones, primary, side, ", ".join(parts)


# --------------------------------------------------------------------------- shared slab preparation
@dataclass
class Slab:
    z0: int
    z1: int
    crop: G.CropBox | None
    vol: np.ndarray  # full-res cropped float32
    label: np.ndarray  # full-res cropped uint8
    flags: list[str]


def prepare_slab(spec: TaskSpec, raw: RawVolume, z0: int, z1: int) -> Slab:
    vol_s, lab_s = raw.vol[z0:z1], raw.label[z0:z1]
    flags: list[str] = []
    crop = G.body_crop(vol_s, lab_s, spec.modality)
    if crop is None and G.body_mask(vol_s, spec.modality).any():
        bb = G._bbox_yx(G.body_mask(vol_s, spec.modality))
        if bb is not None and (bb[0] > G.CROP_MARGIN or bb[2] > G.CROP_MARGIN):
            flags.append(FLAG_CROP_ABANDONED)
    if crop is not None:
        vol_s, lab_s = crop.apply(vol_s), crop.apply(lab_s)
    return Slab(z0, z1, crop, np.ascontiguousarray(vol_s), np.ascontiguousarray(lab_s), flags)


def _pack_slab(
    spec: TaskSpec, slab: Slab, side: int
) -> tuple[np.ndarray, np.ndarray, tuple[float, float], float, tuple[float, float]]:
    """Downsample + int16 conversion. Returns (vol_i16, mask_u8, (sy_scale, sx_scale), mr_scale, window)."""
    vol = slab.vol
    scale = 1.0
    if spec.modality == "mr":
        scale = mr_scale(vol)
        if scale != 1.0:
            vol = vol * scale
    vol_p, mask_p, (sy, sx) = G.downsample_inplane(vol, slab.label, side)
    vol_i16 = pack.to_int16(vol_p, spec.modality)
    window = slab_window(spec, vol_i16.astype(np.float32))
    return vol_i16, mask_p.astype(np.uint8), (sy, sx), scale, window


def _spacing_after(raw_spacing: tuple[float, float, float], scales: tuple[float, float]) -> tuple[float, float, float]:
    sz, sy, sx = raw_spacing
    return (round(sz, 5), round(sy / scales[0], 5), round(sx / scales[1], 5))


def _volume_info(
    spec: TaskSpec, case_id: str, shape: tuple[int, int, int], spacing, window, labels, raw: RawVolume, slab: Slab
) -> VolumeInfo:
    crop = slab.crop
    return VolumeInfo(
        shape=shape,
        spacing=spacing,
        window=Window(wc=float(window[0]), ww=float(window[1])),
        data_path=f"volumes/{case_id}.i16.gz",
        mask_path=f"masks/{case_id}.u8.gz",
        labels=labels,
        sequence=spec.sequence,
        original_shape=list(raw.original_shape),
        crop_origin=[slab.z0 * raw.z_stride, crop.y0 if crop else 0, crop.x0 if crop else 0],
    )


def _case_common(spec: TaskSpec, provenance: dict, split: str) -> dict:
    prov = Provenance(**provenance)
    return {
        "source": "msd",
        "modality": spec.modality,
        "body_region": spec.body_region,
        "provenance": prov,
        "source_split": "imagesTr",
        "split": split,
        "pixel_spacing_mm": None,
        "license_tag": prov.license or "CC BY-SA 4.0",
        "attribution": f"{prov.dataset} ({prov.institution}); {prov.citation} Licence {prov.license}. {prov.url}",
    }


# --------------------------------------------------------------------------- lesion case
def build_lesion_case(
    spec: TaskSpec,
    raw: RawVolume,
    case_id: str,
    provenance: dict,
    opts: BuildOptions,
    zcfg: dict[str, dict] | None = None,
    split: str = "practice",
) -> Built | None:
    zcfg = zcfg or load_zone_config()
    side_px = opts.vol_side or spec.side
    lesion_full = np.isin(raw.label, spec.lesion_values)
    if not lesion_full.any():
        return None
    z0, z1 = G.lesion_slab(lesion_full, opts.margin, opts.vol_slices)
    slab = prepare_slab(spec, raw, z0, z1)
    flags = list(slab.flags)
    lesion = np.isin(slab.label, spec.lesion_values)
    nz, ny, nx = slab.label.shape
    sz, sy_mm, sx_mm = raw.spacing
    if spec.union:
        comps = [lesion] if lesion.sum() >= opts.min_component_voxels else []
    else:
        comps = G.components(lesion, opts.min_component_voxels)
        if int(lesion.sum()) > sum(int(c.sum()) for c in comps):
            flags.append(FLAG_SMALL_DROPPED)
    if not comps:
        return None
    if lesion_full.sum() > lesion.sum():
        flags.append(FLAG_FINDING_CLIPPED)
    organ_zones = {zid: G.organ_zone_mask(slab.label == v, raw.spacing) for v, zid in spec.anatomy.items()}

    vol_i16, mask_p, scales, scale_mr, window = _pack_slab(spec, slab, side_px)
    spacing_p = _spacing_after(raw.spacing, scales)
    if scale_mr != 1.0:
        flags.append(FLAG_MR_SCALED)
    pz, py, px = vol_i16.shape
    sy_s, sx_s = scales

    def sx(x: float) -> float:
        return (x + 0.5) * sx_s - 0.5

    def sy(y: float) -> float:
        return (y + 0.5) * sy_s - 0.5

    findings: list[Finding] = []
    contrasts: dict[str, float] = {}
    n = 0
    for comp in comps:
        # a union finding (brain: oedema + core + enhancing) may have satellite blobs; calipers go on its largest
        # connected part so the measure is a lesion size, not the distance between two blobs
        body = comp if not spec.union else (G.components(comp, 1) or [comp])[0]
        if spec.measure_values:
            core = body & np.isin(slab.label, spec.measure_values)
            body = core if core.any() else body
        long_mm, zm = G.longest_inplane_diameter(body, (sy_mm, sx_mm))
        cx, cy, cz = G.centroid3(comp)
        zs = np.flatnonzero(comp.reshape(nz, -1).any(axis=1))
        slice_range = (int(zs[0]), int(zs[-1]))
        sl = body[zm]
        ys, xs = np.nonzero(sl)
        bbox_full = (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
        # survives the downsample? (nearest-neighbour can erase tiny components)
        pb = (
            int(math.floor(bbox_full[0] * sx_s)),
            int(math.floor(bbox_full[1] * sy_s)),
            int(math.ceil(bbox_full[2] * sx_s)),
            int(math.ceil(bbox_full[3] * sy_s)),
        )
        packed_hit = np.isin(
            mask_p[slice_range[0] : slice_range[1] + 1, pb[1] : pb[3] + 1, pb[0] : pb[2] + 1], spec.lesion_values
        ).any()
        if not packed_hit:
            flags.append(FLAG_FINDING_LOST)
            continue
        n += 1
        fid = f"{case_id}#F{n}"
        zones, primary, side, rel = locate(spec, comp, organ_zones, zcfg)
        poly_full = pack.slice_polygon(sl)
        polygon = [(sx(x), sy(y)) for x, y in poly_full] if poly_full else None
        bbox = (sx(bbox_full[0] - 0.5), sy(bbox_full[1] - 0.5), sx(bbox_full[2] - 0.5), sy(bbox_full[3] - 0.5))
        bbox = (max(bbox[0], 0.0), max(bbox[1], 0.0), min(bbox[2], float(px)), min(bbox[3], float(py)))
        comps_meta = None
        values = list(spec.lesion_values)
        if spec.union:
            present = [v for v in spec.lesion_values if (slab.label[comp] == v).any()]
            comps_meta = [Component(name=BRAIN_COMPONENTS.get(v, f"value {v}"), label_value=v) for v in present]
            values = present or values
        contrast = G.contrast_of(slab.vol * (scale_mr if spec.modality == "mr" else 1.0), comp, window[1])
        contrasts[fid] = contrast
        findings.append(
            Finding(
                finding_id=fid,
                label=spec.lesion_label,  # type: ignore[arg-type]
                source_label=f"{spec.task}:{'+'.join(str(v) for v in values)}",
                kind="focal",
                geometry=Geometry(kind="polygon" if polygon else "bbox", bbox=bbox, polygon=polygon),
                centroid=(sx(cx), sy(cy)),
                area_frac=float(sl.sum() / (ny * nx)),
                label_value=values[0],
                label_values=values,
                centroid3=(sx(cx), sy(cy), cz),
                slice_range=slice_range,
                measure=Measure(long_mm=round(long_mm, 1), slice=zm),
                components=comps_meta,
                volume_mm3=round(float(comp.sum()) * sz * sy_mm * sx_mm, 1),
                side=side,  # type: ignore[arg-type]
                zones=zones,
                primary_zone=primary,
                relative_location=rel,
                contrast=round(contrast, 4),
                readers=provenance.get("readers"),
            )
        )
    if not findings:
        return None
    labels = spec.mask_labels
    vi = _volume_info(spec, case_id, (pz, py, px), spacing_p, window, labels, raw, slab)
    features: dict[str, float] = {
        "lesion_voxels_full_res": float(lesion.sum()),
        "n_lesion_components": float(len(findings)),
    }
    if scale_mr != 1.0:
        features["mr_intensity_scale"] = float(scale_mr)
    for ax in spec.flip:
        features[f"header_flip_{ax}"] = 1.0
    features["z_stride"] = float(raw.z_stride)
    case = Case(
        case_id=case_id,
        **_case_common(spec, provenance, split),
        volume=vi,
        image_path=f"previews/{case_id}_axial.png",
        width=px,
        height=py,
        is_normal=False,
        findings=findings,
        zones_path=f"zones3d/{case_id}.json",
        features=features,
        qa_flags=sorted(set(flags)),
    )
    zones_doc = _zones_doc(spec, (pz, py, px), spacing_p)
    preview = pack.render_preview(
        vol_i16, mask_p, findings[0].measure.slice, window, spec.lesion_values, tuple(spec.anatomy)
    )
    return Built(case=case, vol=vol_i16, mask=mask_p, zones_doc=zones_doc, preview=preview, contrast=contrasts)


def _zones_doc(spec: TaskSpec, shape: tuple[int, int, int], spacing: tuple[float, float, float]) -> dict:
    organ = {zid: [v] for v, zid in spec.anatomy.items()}
    halves = {z: f"half:{w}" for w, z in (BRAIN_HALF_ZONE if spec.body_region == "brain" else HALF_ZONE).items()}
    return pack.zones_document(
        shape, spacing, organ, halves, organ_dilation_mm=G.ORGAN_DILATION_MM, midline_frac=G.MIDLINE_FRAC
    )


# --------------------------------------------------------------------------- normal (lesion-free) slab
def organ_present_slices(spec: TaskSpec, raw: RawVolume, min_frac: float = 0.3) -> np.ndarray:
    """(nz,) bool: the organ (anatomy labels) is on the slice; for tasks without anatomy labels (brain), tissue
    area on the slice is at least `min_frac` of the largest slice's tissue area."""
    nz = raw.label.shape[0]
    if spec.anatomy:
        return np.isin(raw.label, list(spec.anatomy)).reshape(nz, -1).any(axis=1)
    area = G.body_mask(raw.vol, spec.modality).reshape(nz, -1).sum(axis=1)
    return area >= min_frac * max(int(area.max()), 1)


def build_normal_case(
    spec: TaskSpec,
    raw: RawVolume,
    case_id: str,
    provenance: dict,
    opts: BuildOptions,
    split: str = "practice",
) -> Built | None:
    side_px = opts.vol_side or spec.side
    lesion_full = np.isin(raw.label, spec.lesion_values)
    nz = raw.label.shape[0]
    rng = G.normal_slab(lesion_full.reshape(nz, -1).any(axis=1), organ_present_slices(spec, raw), opts.vol_slices)
    if rng is None:
        return None
    z0, z1 = rng
    slab = prepare_slab(spec, raw, z0, z1)
    if np.isin(slab.label, spec.lesion_values).any():  # cannot happen by construction; belt and braces
        raise AssertionError(f"{case_id}: lesion voxels inside a lesion-free slab")
    slab.label[~np.isin(slab.label, list(spec.anatomy))] = 0
    vol_i16, mask_p, scales, scale_mr, window = _pack_slab(spec, slab, side_px)
    spacing_p = _spacing_after(raw.spacing, scales)
    pz, py, px = vol_i16.shape
    flags = [FLAG_LESION_FREE, *slab.flags]
    features: dict[str, float] = {
        "normal_slab_z0": float(z0),
        "normal_slab_z1": float(z1),
        "z_stride": float(raw.z_stride),
    }
    for ax in spec.flip:
        features[f"header_flip_{ax}"] = 1.0
    if scale_mr != 1.0:
        flags.append(FLAG_MR_SCALED)
        features["mr_intensity_scale"] = float(scale_mr)
    labels = {str(v): z for v, z in sorted(spec.anatomy.items())}
    vi = _volume_info(spec, case_id, (pz, py, px), spacing_p, window, labels, raw, slab)
    case = Case(
        case_id=case_id,
        **_case_common(spec, provenance, split),
        volume=vi,
        image_path=f"previews/{case_id}_axial.png",
        width=px,
        height=py,
        is_normal=True,
        findings=[],
        zones_path=f"zones3d/{case_id}.json",
        features=features,
        qa_flags=sorted(set(flags)),
    )
    preview = pack.render_preview(vol_i16, mask_p, pz // 2, window, (), tuple(spec.anatomy))
    return Built(
        case=case, vol=vol_i16, mask=mask_p, zones_doc=_zones_doc(spec, (pz, py, px), spacing_p), preview=preview
    )


# --------------------------------------------------------------------------- orientation evidence
def liver_side_score(vol_i16: np.ndarray) -> float:
    """Abdominal CT sanity check: share of liver-density voxels (40–200 HU, the enhanced liver and spleen) that lie in
    the patient-RIGHT half (low x). The liver dominates, so a correctly oriented volume scores > 0.5."""
    dense = (vol_i16 >= 40) & (vol_i16 <= 200)
    nx = vol_i16.shape[2]
    right = dense[:, :, : nx // 2].sum()
    total = dense.sum()
    return float(right / total) if total else 0.5


# --------------------------------------------------------------------------- difficulty
DIFF_WEIGHTS = {"neg_log_area": 0.9, "neg_contrast": 0.6, "hardness": 0.5}
DIFF_CLIP = 2.5


def assign_difficulty(cases: list[Case], zcfg: dict[str, dict] | None = None) -> list[Case]:
    """b0 = 0.9·z(−log area_frac) + 0.6·z(−contrast) + 0.5·z(zone hardness), z fit over these cases' findings
    (one task at a time), clipped to ±2.5; Case.difficulty_prior = max over findings (0 for normals)."""
    zcfg = zcfg or load_zone_config()
    rows: list[tuple[Case, Finding, dict[str, float]]] = []
    for c in cases:
        for f in c.findings:
            rows.append(
                (
                    c,
                    f,
                    {
                        "neg_log_area": -math.log(max(f.area_frac, 1e-7)),
                        "neg_contrast": -float(f.contrast or 0.0),
                        "hardness": zone_hardness(zcfg, f.primary_zone),
                    },
                )
            )
    params: dict[str, tuple[float, float]] = {}
    for k in DIFF_WEIGHTS:
        v = np.array([r[2][k] for r in rows], dtype=float)
        sd = float(v.std()) if v.size else 1.0
        params[k] = (float(v.mean()) if v.size else 0.0, sd if sd > 1e-9 else 1.0)
    out: dict[str, Case] = {c.case_id: c for c in cases}
    per_case: dict[str, list[Finding]] = {c.case_id: [] for c in cases}
    for c, f, feats in rows:
        b0 = sum(w * (feats[k] - params[k][0]) / params[k][1] for k, w in DIFF_WEIGHTS.items())
        per_case[c.case_id].append(
            f.model_copy(update={"difficulty": round(float(np.clip(b0, -DIFF_CLIP, DIFF_CLIP)), 3)})
        )
    result = []
    for c in cases:
        fs = per_case[c.case_id]
        prior = max((f.difficulty or 0.0) for f in fs) if fs else 0.0
        result.append(out[c.case_id].model_copy(update={"findings": fs, "difficulty_prior": round(prior, 3)}))
    return result
