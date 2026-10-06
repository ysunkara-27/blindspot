"""Anatomy segmentation (TXV ChestX-Det PSPNet, 14 structures) + TXV DenseNet classifier probs — SPEC §4.1.

Empirical check (2026-10-05, 8 real ChestX-Det images): PSPNet returns LOGITS (min −25.5, max 14.3), so masks
are sigmoid(logit) > 0.5, i.e. logit > 0. Masks are predicted at 512² and upsampled to the image size with
nearest-neighbour. The DenseNet (densenet121-res224-all) returns calibrated probabilities (sigmoid + op_norm,
0.5 = the model's operating point); stored as-is.

Output per case: data/processed/anatomy/<case_id>.npz — masks (packbits bool (14,H,W)), targets (14 names),
shape, txv_probs (float32, 18), txv_pathologies (18 names). Atomic writes; --resume skips existing files.

Order (logged): assess_A, assess_B, first 800 practice by case id, bench, rest of practice. Holdout skipped.
Run in the background:
  nohup uv run python -m pipeline.anatomy.segment --resume >> logs/anatomy.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from typing import Any

import cv2
import numpy as np

from pipeline.anatomy import common as C

PRACTICE_PRIORITY_N = 800


def _cid_num(cid: str) -> tuple[int, str]:
    tail = cid.rsplit("_", 1)[-1]
    return (int(tail), cid) if tail.isdigit() else (1 << 60, cid)


def order_cases(cases: list[dict[str, Any]], splits: list[str]) -> list[dict[str, Any]]:
    """assess_A, assess_B, practice[:800 by id], bench, practice[800:]; restricted to `splits`."""
    by: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        by.setdefault(c["split"], []).append(c)
    for v in by.values():
        v.sort(key=lambda c: _cid_num(c["case_id"]))
    prac = by.get("practice", [])
    seq = (
        by.get("assess_A", [])
        + by.get("assess_B", [])
        + prac[:PRACTICE_PRIORITY_N]
        + by.get("bench", [])
        + prac[PRACTICE_PRIORITY_N:]
    )
    allowed = set(splits)
    extra = [c for s, v in by.items() if s not in ("assess_A", "assess_B", "practice", "bench") for c in v]
    return [c for c in seq + extra if c["split"] in allowed]


def preprocess(img: np.ndarray, size: int) -> np.ndarray:
    """uint8 grayscale → float32 (1, size, size) in TXV range [−1024, 1024] (center crop if not square)."""
    import torchxrayvision as xrv

    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape
    if h != w:
        s = min(h, w)
        y0, x0 = (h - s) // 2, (w - s) // 2
        img = img[y0 : y0 + s, x0 : x0 + s]
    x = xrv.datasets.normalize(img, 255).astype(np.float32)
    x = cv2.resize(x, (size, size), interpolation=cv2.INTER_AREA)  # anti-aliased downsample
    return x[None]


def upsample_nearest(m: np.ndarray, h: int, w: int) -> np.ndarray:
    """bool (K, s, s) → bool (K, h, w), nearest-neighbour."""
    k, s, _ = m.shape
    if h == w and h % s == 0:
        f = h // s
        return m.repeat(f, axis=1).repeat(f, axis=2)
    return np.stack([cv2.resize(ch.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0 for ch in m])


def pick_device(name: str | None = None):
    import torch

    if name:
        return torch.device(name)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _swapped_names() -> bool:
    rep = C.qa_dir() / "orientation_report.json"
    if rep.exists():
        try:
            return bool(json.loads(rep.read_text()).get("swapped_channel_names"))
        except Exception:  # noqa: BLE001
            return False
    return False


def anatomy_coverage(splits: list[str] | None = None) -> dict[str, Any]:
    """Fraction of in-scope cases with an anatomy npz (M2 acceptance: ≥ 95%)."""
    proc = C.processed_dir()
    cases = [c for c in C.read_cases() if c["split"] in set(splits or C.IN_SCOPE_SPLITS)]
    have = sum((proc / C.anatomy_rel(c["case_id"])).exists() for c in cases)
    return {"in_scope": len(cases), "with_anatomy": have, "frac": have / max(1, len(cases))}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="TXV anatomy segmentation + classifier probs (SPEC §4.1)")
    ap.add_argument("--resume", action="store_true", help="skip cases whose npz already exists")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--splits", default="practice,assess_A,assess_B,bench")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default=None)
    ap.add_argument("--no-classifier", action="store_true")
    args = ap.parse_args(argv)

    import torch
    import torchxrayvision as xrv

    log = C.get_logger("segment")
    proc = C.processed_dir()
    out_dir = proc / "anatomy"
    out_dir.mkdir(parents=True, exist_ok=True)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    todo = order_cases(C.read_cases(), splits)
    n_scope = len(todo)
    if args.resume:
        todo = [c for c in todo if not (out_dir / f"{c['case_id']}.npz").exists()]
    if args.limit:
        todo = todo[: args.limit]
    log.info(
        "segment: %d in scope (%s), %d to do (resume=%s); order A, B, practice[:%d], bench, practice[rest]",
        n_scope,
        ",".join(splits),
        len(todo),
        args.resume,
        PRACTICE_PRIORITY_N,
    )
    if not todo:
        return

    dev = pick_device(args.device)
    seg = xrv.baseline_models.chestx_det.PSPNet().eval().to(dev)
    targets = list(seg.targets)
    assert tuple(targets) == C.TXV_TARGETS, targets
    if _swapped_names():
        from pipeline.anatomy.orientation import swap_name

        targets = [swap_name(t) for t in targets]
        log.warning("orientation report says swap: writing patient-side (swapped) names")
    cls = None
    if not args.no_classifier:
        cls = xrv.models.DenseNet(weights="densenet121-res224-all").eval().to(dev)
        pathologies = np.array(list(cls.pathologies))
    log.info("device=%s batch=%d  weights: %s", dev, args.batch, seg.weights_filename_local)

    # background loader: decode + preprocess the next batches while the GPU works
    q: queue.Queue = queue.Queue(maxsize=4)

    def loader() -> None:
        for i in range(0, len(todo), args.batch):
            chunk = todo[i : i + args.batch]
            items = []
            for c in chunk:
                img = cv2.imread(str(proc / c["image_path"]), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    items.append((c, None, None, None))
                    continue
                items.append((c, preprocess(img, 512), preprocess(img, 224) if cls is not None else None, img.shape))
            q.put(items)
        q.put(None)

    th = threading.Thread(target=loader, daemon=True)
    th.start()
    t0 = time.time()
    done = failed = 0
    logits_checked = False
    while True:
        items = q.get()
        if items is None:
            break
        ok = [it for it in items if it[1] is not None]
        for it in items:
            if it[1] is None:
                failed += 1
                log.error("could not read image for %s", it[0]["case_id"])
        if not ok:
            continue
        with torch.no_grad():
            xs = torch.from_numpy(np.stack([it[1] for it in ok])).to(dev)
            out = seg(xs)
            if not logits_checked:
                lo, hi = float(out.min()), float(out.max())
                is_logit = lo < 0.0 or hi > 1.0
                log.info(
                    "PSPNet output range on first batch: min=%.3f max=%.3f → %s",
                    lo,
                    hi,
                    "logits (sigmoid applied: mask = logit > 0)" if is_logit else "probabilities (mask = p > 0.5)",
                )
                logits_checked = True
            masks512 = (out > 0.0 if is_logit else out > 0.5).cpu().numpy()
            probs = None
            if cls is not None:
                probs = cls(torch.from_numpy(np.stack([it[2] for it in ok])).to(dev)).float().cpu().numpy()
        for j, (c, _, _, shape) in enumerate(ok):
            h, w = shape
            m = upsample_nearest(masks512[j], h, w)
            extra: dict[str, np.ndarray] = {}
            if probs is not None:
                extra = {"txv_probs": probs[j].astype(np.float32), "txv_pathologies": pathologies}
            C.save_anatomy(out_dir / f"{c['case_id']}.npz", m, targets, **extra)
            done += 1
        if done % (args.batch * 10) < len(ok) or done == len(todo):
            el = time.time() - t0
            rate = done / el
            log.info(
                "segment %d/%d  %.2f img/s (%.0f/min)  elapsed %.0fs  eta %.1f min  failed=%d",
                done,
                len(todo),
                rate,
                rate * 60,
                el,
                (len(todo) - done) / max(rate, 1e-9) / 60,
                failed,
            )
    el = time.time() - t0
    log.info(
        "segment done: %d written, %d failed in %.1f min (%.2f img/s)", done, failed, el / 60, done / max(el, 1e-9)
    )


if __name__ == "__main__":
    main()
