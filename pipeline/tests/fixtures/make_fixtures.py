"""Generate 10 tiny synthetic cases (256×256) so engine/tutor tests never need the real dataset.

Run: uv run python -m pipeline.tests.fixtures.make_fixtures   → pipeline/tests/fixtures/synthetic/
Layout mirrors data/processed/: cases.jsonl, images/, masks/, zones/.
Patient RIGHT lung is on the image LEFT (x < 128). Labeled synthetic; never shown in the UI.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shared.contracts import Case, Finding, Geometry
from shared.rle import write_zones

W = H = 256
ROOT = Path(__file__).resolve().parent / "synthetic"

# (label, kind, side, centre (x, y) in image px, radius) — image-left = patient-right
SPECS: list[tuple[str, bool, list[tuple[str, str, float, float, int]]]] = [
    ("syn_001", False, [("nodule", "right", 70, 150, 7)]),  # small, right lower zone
    ("syn_002", False, [("pneumothorax", "left", 185, 40, 9)]),  # left apex
    ("syn_003", False, [("effusion", "right", 55, 215, 14)]),  # right CP angle
    ("syn_004", False, [("consolidation", "left", 175, 120, 20)]),  # left mid zone
    ("syn_005", False, [("mass", "right", 80, 95, 16), ("nodule", "left", 190, 170, 6)]),  # two findings
    ("syn_006", False, [("effusion", "right", 55, 215, 12), ("effusion", "left", 200, 215, 12)]),  # bilateral
    ("syn_007", False, [("cardiomegaly", "midline", 128, 170, 0)]),  # pattern only
    ("syn_008", True, []),
    ("syn_009", True, []),
    ("syn_010", True, []),
]


def lungs() -> tuple[np.ndarray, np.ndarray]:
    r = np.zeros((H, W), np.uint8)
    lf = np.zeros((H, W), np.uint8)
    cv2.ellipse(r, (72, 135), (48, 100), 0, 0, 360, 255, -1)
    cv2.ellipse(lf, (184, 135), (48, 100), 0, 0, 360, 255, -1)
    return r > 0, lf > 0


def heart() -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (140, 175), (40, 45), 0, 0, 360, 255, -1)
    return m > 0


def zones_for(rl: np.ndarray, ll: np.ndarray, ht: np.ndarray) -> dict[str, np.ndarray]:
    yy, xx = np.mgrid[0:H, 0:W]
    z: dict[str, np.ndarray] = {}
    for name, lung, lateral_small_x in (("right", rl, True), ("left", ll, False)):
        ys, xs = np.where(lung)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        ext = y1 - y0
        z[f"{name}_upper_zone"] = lung & (yy < y0 + ext / 3)
        z[f"{name}_mid_zone"] = lung & (yy >= y0 + ext / 3) & (yy < y0 + 2 * ext / 3)
        z[f"{name}_lower_zone"] = lung & (yy >= y0 + 2 * ext / 3)
        z[f"{name}_apex"] = lung & (yy < y0 + 0.18 * ext)
        lat = (xx < x0 + 0.45 * (x1 - x0)) if lateral_small_x else (xx > x1 - 0.45 * (x1 - x0))
        z[f"{name}_costophrenic_angle"] = lung & (yy > y1 - 0.18 * ext) & lat
        k = max(1, int(0.08 * (x1 - x0)))
        inner = cv2.erode(lung.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
        z[f"{name}_periphery"] = lung & ~inner
        hil = np.zeros((H, W), np.uint8)
        cx = x1 - 10 if lateral_small_x else x0 + 10
        cv2.circle(hil, (int(cx), 130), 14, 255, -1)
        z[f"{name}_hilum"] = hil > 0
        z[f"{name}_lung"] = lung
    z["cardiac_silhouette"] = ht
    z["retrocardiac"] = ht & (xx > 128) & (yy > 130)
    z["mediastinum"] = (np.abs(xx - 128) < 18) & (yy > 40) & (yy < 180)
    z["subdiaphragmatic"] = (yy >= 235) & (yy < 255) & (xx > 24) & (xx < 232)
    z["spine"] = (np.abs(xx - 128) < 8) & (yy > 20)
    z["lungs"] = rl | ll
    return z


def main() -> None:
    for d in ("images", "masks", "zones"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    ht = heart()
    rl, ll = lungs()
    zones = zones_for(rl, ll, ht)
    base = np.full((H, W), 150, np.uint8)
    base[rl | ll] = 60
    base[ht] = 170
    base[zones["spine"]] = 200
    lines = []
    for case_id, is_normal, specs in SPECS:
        img = base.copy()
        findings: list[Finding] = []
        for i, (label, side, cx, cy, rad) in enumerate(specs, start=1):
            fid = f"{case_id}#F{i}"
            kind = "pattern" if label == "cardiomegaly" else "focal"
            if kind == "pattern":
                m = ht.copy()
            else:
                m8 = np.zeros((H, W), np.uint8)
                cv2.circle(m8, (int(cx), int(cy)), rad, 255, -1)
                m = m8 > 0
                img[m] = np.clip(img[m].astype(int) + 90, 0, 255).astype(np.uint8)
            ys, xs = np.where(m)
            bbox = (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))
            mask_path = f"masks/{fid.replace('#', '_')}.png"
            cv2.imwrite(str(ROOT / mask_path), (m * 255).astype(np.uint8))
            ov = {z: float((m & zones[z]).sum() / m.sum()) for z in zones if not z.endswith("_lung") and z != "lungs"}
            zs = [z for z, o in sorted(ov.items(), key=lambda kv: -kv[1]) if o >= 0.15][:3]
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            poly = [(float(p[0][0]), float(p[0][1])) for p in cnts[0]] if cnts else None
            findings.append(
                Finding(
                    finding_id=fid,
                    label=label,
                    source_label=label.title(),
                    kind=kind,
                    geometry=Geometry(kind="polygon", bbox=bbox, polygon=poly, mask_path=mask_path),
                    centroid=(float(xs.mean()), float(ys.mean())),
                    area_frac=float(m.sum() / (H * W)),
                    side=side,
                    zones=zs,
                    primary_zone=zs[0] if zs else None,
                    relative_location=f"{zs[0].replace('_', ' ')}" if zs else None,
                    difficulty=0.5 if rad and rad < 10 else -0.5,
                )
            )
        cv2.imwrite(str(ROOT / "images" / f"{case_id}.png"), img)
        write_zones(ROOT / "zones" / f"{case_id}.json", case_id, zones, approximate=False, midline_x=128.0)
        case = Case(
            case_id=case_id,
            source="synthetic",
            source_split="synthetic",
            split="practice",
            image_path=f"images/{case_id}.png",
            width=W,
            height=H,
            is_normal=is_normal,
            findings=findings,
            zones_path=f"zones/{case_id}.json",
            cardiothoracic_ratio=0.62 if case_id == "syn_007" else 0.45,
            difficulty_prior=max([f.difficulty or 0.0 for f in findings], default=0.0),
            license_tag="synthetic",
            attribution="synthetic test fixture — not a radiograph",
            qa_flags=["synthetic"],
        )
        lines.append(case.model_dump_json())
    (ROOT / "cases.jsonl").write_text("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} synthetic cases to {ROOT}")


if __name__ == "__main__":
    main()
