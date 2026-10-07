"""Pure array functions for volumetric cases: orientation, body crop, slab choice, downsampling, components,
measurements, sides and zones. No I/O, no config reads — easy to test on synthetic volumes.

Array convention (docs/VOLUMETRIC_PLAN.md): (z, y, x); z=0 most SUPERIOR, y increases POSTERIOR (down the axial
image), x increases to the PATIENT'S LEFT (patient right at low x = image left, as on the X-ray display).
Spacing is (sz, sy, sx) in mm. Coordinates are voxel indices (floats allowed); never resampled through-plane.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import nibabel as nib
import numpy as np
from scipy import ndimage

CT_BODY_HU = -500.0
MR_BODY_FRAC = 0.06
CROP_MARGIN = 6
MIN_COMPONENT_VOXELS = 30
MIDLINE_FRAC = 0.10
ZONE_OVERLAP = 0.15
ORGAN_DILATION_MM = 5.0
NORMAL_GAP = 8
MIN_NORMAL_SLICES = 12
MIN_NORMAL_ORGAN_SLICES = 4
STRUCT26 = np.ones((3, 3, 3), dtype=bool)


# --------------------------------------------------------------------------- orientation
def ras_to_zyx(arr_ras: np.ndarray) -> np.ndarray:
    """RAS+ array (x→left, y→anterior, z→superior; nibabel canonical) → our (z,y,x) view.

    z flipped so index 0 is most superior; y flipped so index 0 is most anterior (top of the axial image);
    x kept: index 0 is the patient's RIGHT.
    """
    if arr_ras.ndim != 3:
        raise ValueError(f"expected a 3-D array, got shape {arr_ras.shape}")
    return np.ascontiguousarray(arr_ras.transpose(2, 1, 0)[::-1, ::-1, :])


def nifti_to_zyx(img: nib.Nifti1Image, channel: int | None = None) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Reorient any axis-aligned NIfTI to (z,y,x) per the module convention; spacing comes back as (sz,sy,sx)."""
    if channel is not None:
        if img.ndim != 4:
            raise ValueError(f"channel={channel} requested but the image is {img.ndim}-D")
        data = np.asarray(img.dataobj[..., channel])
        img = nib.Nifti1Image(data, img.affine, img.header)
    elif img.ndim != 3:
        raise ValueError(f"expected a 3-D image (or 4-D with a channel), got {img.ndim}-D")
    can = nib.as_closest_canonical(img)
    zooms = [float(z) for z in can.header.get_zooms()[:3]]
    arr = np.asanyarray(can.dataobj)
    return ras_to_zyx(arr), (zooms[2], zooms[1], zooms[0])


# --------------------------------------------------------------------------- body crop
@dataclass(frozen=True)
class CropBox:
    y0: int
    y1: int  # exclusive
    x0: int
    x1: int  # exclusive

    def apply(self, arr: np.ndarray) -> np.ndarray:
        return arr[:, self.y0 : self.y1, self.x0 : self.x1]


def body_mask(vol: np.ndarray, modality: str) -> np.ndarray:
    if modality == "ct":
        return vol > CT_BODY_HU
    peak = float(np.percentile(vol, 99.5)) if vol.size else 0.0
    return vol > MR_BODY_FRAC * peak


def _bbox_yx(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask.any(axis=0))
    if ys.size == 0:
        return None
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def body_crop(vol: np.ndarray, label: np.ndarray, modality: str, margin: int = CROP_MARGIN) -> CropBox | None:
    """In-plane bbox of body voxels (largest 3-D component of the threshold mask, so the table drops out),
    plus `margin` voxels. Falls back to the bbox of every thresholded voxel, then to None (no crop), whenever
    a crop would clip a labelled voxel. Returns None when nothing would be cropped.
    """
    _, ny, nx = vol.shape
    thresh = body_mask(vol, modality)
    if not thresh.any():
        return None
    lab, n = ndimage.label(thresh, structure=STRUCT26)
    candidates: list[np.ndarray] = []
    if n > 1:
        sizes = ndimage.sum(thresh, lab, index=np.arange(1, n + 1))
        candidates.append(lab == (int(np.argmax(sizes)) + 1))
    candidates.append(thresh)
    labelled = label > 0
    for cand in candidates:
        bb = _bbox_yx(cand)
        if bb is None:
            continue
        y0, y1, x0, x1 = bb
        box = CropBox(max(y0 - margin, 0), min(y1 + margin, ny), max(x0 - margin, 0), min(x1 + margin, nx))
        if box == CropBox(0, ny, 0, nx):
            return None
        keep = np.zeros((ny, nx), dtype=bool)
        keep[box.y0 : box.y1, box.x0 : box.x1] = True
        if labelled.any() and (labelled & ~keep[None]).any():
            continue  # this crop would clip a labelled voxel
        return box
    return None


# --------------------------------------------------------------------------- slabs
def slab_around(z_lo: int, z_hi: int, nz: int, margin: int, cap: int) -> tuple[int, int]:
    """[z0, z1) of at most `cap` slices covering [z_lo, z_hi] ± margin, shifted to stay inside the volume.
    When the extent itself exceeds the cap the slab is centred on it."""
    if not (0 <= z_lo <= z_hi < nz):
        raise ValueError(f"bad extent {z_lo}..{z_hi} for nz={nz}")
    cap = min(cap, nz)
    want_lo, want_hi = z_lo - margin, z_hi + margin + 1
    if want_hi - want_lo > cap:
        centre = (z_lo + z_hi + 1) / 2
        want_lo = int(round(centre - cap / 2))
        want_hi = want_lo + cap
    if want_lo < 0:
        want_hi -= want_lo
        want_lo = 0
    if want_hi > nz:
        want_lo -= want_hi - nz
        want_hi = nz
    return max(want_lo, 0), want_hi


def lesion_slab(lesion: np.ndarray, margin: int, cap: int) -> tuple[int, int]:
    """Slab containing the lesion voxels (all of them when they fit, else the `cap` slices holding most)."""
    per_slice = lesion.reshape(lesion.shape[0], -1).sum(axis=1)
    zs = np.flatnonzero(per_slice)
    if zs.size == 0:
        raise ValueError("no lesion voxels")
    z_lo, z_hi = int(zs[0]), int(zs[-1])
    nz = lesion.shape[0]
    if z_hi - z_lo + 1 <= cap:
        return slab_around(z_lo, z_hi, nz, margin, cap)
    csum = np.concatenate([[0], np.cumsum(per_slice)])
    best = max(range(0, nz - cap + 1), key=lambda z0: csum[z0 + cap] - csum[z0])
    return best, best + cap


def normal_slab(
    lesion_slices: np.ndarray,
    organ_slices: np.ndarray,
    length: int,
    gap: int = NORMAL_GAP,
    min_len: int = MIN_NORMAL_SLICES,
    min_organ: int = MIN_NORMAL_ORGAN_SLICES,
) -> tuple[int, int] | None:
    """A lesion-free slab: a run of slices at least `gap` from any lesion slice, at least `min_len` long, trimmed to
    `length`; among all such windows the one showing the organ on the most slices wins (ties → nearest the lesion,
    so the anatomy stays comparable). None when no window shows the organ on at least `min_organ` slices."""
    nz = len(lesion_slices)
    forbidden = np.zeros(nz, dtype=bool)
    lesion_idx = np.flatnonzero(lesion_slices)
    for z in lesion_idx:
        forbidden[max(z - gap, 0) : min(z + gap + 1, nz)] = True
    organ = organ_slices.astype(bool)
    lesion_centre = float(lesion_idx.mean()) if lesion_idx.size else nz / 2
    best: tuple[int, int] | None = None
    best_key: tuple[int, float] | None = None
    z = 0
    while z < nz:
        if forbidden[z]:
            z += 1
            continue
        z0 = z
        while z < nz and not forbidden[z]:
            z += 1
        run_len = z - z0
        if run_len < min_len:
            continue
        win = min(length, run_len)
        for start in range(z0, z - win + 1):
            n_org = int(organ[start : start + win].sum())
            key = (n_org, -abs((start + win / 2) - lesion_centre))
            if best_key is None or key > best_key:
                best, best_key = (start, start + win), key
    if best is None or best_key is None or best_key[0] < min_organ:
        return None
    return best


# --------------------------------------------------------------------------- resampling
def downsample_inplane(
    vol: np.ndarray, mask: np.ndarray, side: int
) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """Scale the in-plane axes so the longer one equals `side` (never upsampled). Image: area interpolation,
    mask: nearest. Returns (vol, mask, (scale_y, scale_x)) where new_index = old_index * scale."""
    nz, ny, nx = vol.shape
    longest = max(ny, nx)
    if longest <= side:
        return vol, mask, (1.0, 1.0)
    new_y, new_x = max(int(round(ny * side / longest)), 1), max(int(round(nx * side / longest)), 1)
    out_v = np.empty((nz, new_y, new_x), dtype=np.float32)
    out_m = np.empty((nz, new_y, new_x), dtype=mask.dtype)
    for z in range(nz):
        out_v[z] = cv2.resize(vol[z].astype(np.float32), (new_x, new_y), interpolation=cv2.INTER_AREA)
        out_m[z] = cv2.resize(mask[z], (new_x, new_y), interpolation=cv2.INTER_NEAREST)
    return out_v, out_m, (new_y / ny, new_x / nx)


# --------------------------------------------------------------------------- components and measurements
def components(mask: np.ndarray, min_voxels: int = MIN_COMPONENT_VOXELS) -> list[np.ndarray]:
    """26-connected components with at least `min_voxels` voxels, largest first."""
    lab, n = ndimage.label(mask.astype(bool), structure=STRUCT26)
    if n == 0:
        return []
    sizes = ndimage.sum(np.ones_like(lab, dtype=np.uint8), lab, index=np.arange(1, n + 1))
    order = sorted(range(n), key=lambda i: (-sizes[i], i))
    return [lab == (i + 1) for i in order if sizes[i] >= min_voxels]


def _caliper_mm(points_yx: np.ndarray, spacing_yx: tuple[float, float]) -> float:
    """Edge-to-edge length of a pixel set along its longest axis: the max distance between pixel CENTRES
    (over the convex hull), plus one pixel along that direction (so a 1-pixel object is one pixel long, not zero).
    This is what calipers on the image measure; skimage's feret_diameter_max (hull of pixel SQUARES) adds the
    staircase corners and overestimates round lesions by ~1.5 px, so it is not used."""
    sy, sx = spacing_yx
    pts = points_yx.astype(float) * np.array([sy, sx])
    if len(pts) > 3:
        try:
            from scipy.spatial import ConvexHull

            pts = pts[ConvexHull(pts).vertices]
        except Exception:  # collinear / degenerate sets: brute force on all points
            pass
    d = pts[:, None, :] - pts[None, :, :]
    dist = np.sqrt((d**2).sum(axis=-1))
    i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
    best = float(dist[i, j])
    if best <= 0:
        return float(max(sy, sx))
    uy, ux = d[i, j] / best
    return best + float(np.sqrt((uy * sy) ** 2 + (ux * sx) ** 2))  # one pixel (as an ellipse) along the caliper


def longest_inplane_diameter(comp: np.ndarray, spacing_yx: tuple[float, float]) -> tuple[float, int]:
    """(longest in-plane diameter in mm over all axial slices, slice index): see _caliper_mm."""
    best, best_z = 0.0, -1
    for z in np.flatnonzero(comp.reshape(comp.shape[0], -1).any(axis=1)):
        pts = np.argwhere(comp[z])
        d = _caliper_mm(pts, spacing_yx)
        if d > best:
            best, best_z = d, int(z)
    return best, best_z


def centroid3(comp: np.ndarray) -> tuple[float, float, float]:
    zs, ys, xs = np.nonzero(comp)
    return float(xs.mean()), float(ys.mean()), float(zs.mean())


def contrast_of(vol: np.ndarray, comp: np.ndarray, ww: float, shell_vox: int = 3) -> float:
    """|mean(inside) − mean(shell around)| / window width; the shell excludes the lesion itself."""
    shell = ndimage.binary_dilation(comp, structure=STRUCT26, iterations=shell_vox) & ~comp
    if not shell.any():
        return 0.0
    return float(abs(vol[comp].mean() - vol[shell].mean()) / max(ww, 1e-6))


# --------------------------------------------------------------------------- sides and zones
def side_of(cx: float, nx: int, midline_frac: float = MIDLINE_FRAC) -> str:
    """Patient side from the x centroid: low x is the patient's RIGHT. Within ±midline_frac of the centre → midline."""
    mid = (nx - 1) / 2
    if abs(cx - mid) <= midline_frac * nx:
        return "midline"
    return "right" if cx < mid else "left"


def half_mask(nx: int, which: str, midline_frac: float = MIDLINE_FRAC) -> np.ndarray:
    """(nx,) boolean: which x columns belong to half:right | half:left | half:midline."""
    xs = np.arange(nx)
    mid = (nx - 1) / 2
    near = np.abs(xs - mid) <= midline_frac * nx
    if which == "midline":
        return near
    if which == "right":
        return (xs < mid) & ~near
    if which == "left":
        return (xs > mid) & ~near
    raise ValueError(which)


def third_ranges(nz: int) -> dict[str, tuple[int, int]]:
    """slab:superior | mid | inferior → [z0, z1) with the remainder going to the middle third."""
    a = nz // 3
    b = nz - 2 * a
    return {"superior": (0, a), "mid": (a, a + b), "inferior": (a + b, nz)}


def ball_structure(radius_mm: float, spacing: tuple[float, float, float]) -> np.ndarray:
    """Boolean ellipsoid kernel reaching `radius_mm` in every axis for anisotropic voxels."""
    r = [int(np.ceil(radius_mm / max(sp, 1e-6))) for sp in spacing]
    z, y, x = np.mgrid[-r[0] : r[0] + 1, -r[1] : r[1] + 1, -r[2] : r[2] + 1]
    return (z * spacing[0]) ** 2 + (y * spacing[1]) ** 2 + (x * spacing[2]) ** 2 <= radius_mm**2 + 1e-9


def organ_zone_mask(
    organ: np.ndarray, spacing: tuple[float, float, float], dilation_mm: float = ORGAN_DILATION_MM
) -> np.ndarray:
    """An organ's zone: the organ dilated by `dilation_mm` (Euclidean, spacing-aware) with holes filled, so a lesion
    sitting inside the organ (where the mask value is the lesion's, not the organ's) still counts as inside."""
    if not organ.any():
        return organ.astype(bool)
    out = ndimage.binary_dilation(organ.astype(bool), structure=ball_structure(dilation_mm, spacing))
    return ndimage.binary_fill_holes(out)


def overlap_fraction(comp: np.ndarray, zone: np.ndarray) -> float:
    n = int(comp.sum())
    return float((comp & zone).sum() / n) if n else 0.0


def slab_third_fractions(comp: np.ndarray) -> dict[str, float]:
    nz = comp.shape[0]
    per = comp.reshape(nz, -1).sum(axis=1).astype(float)
    tot = per.sum() or 1.0
    return {k: float(per[a:b].sum() / tot) for k, (a, b) in third_ranges(nz).items()}


def half_fractions(comp: np.ndarray) -> dict[str, float]:
    nx = comp.shape[2]
    per = comp.reshape(-1, nx).sum(axis=0).astype(float)
    tot = per.sum() or 1.0
    return {w: float(per[half_mask(nx, w)].sum() / tot) for w in ("right", "left", "midline")}
