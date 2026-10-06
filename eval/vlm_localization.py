"""SPEC §12.1 — "Can a frontier VLM find the finding?" (grid-overlay method adapted from Gosai & Kavishwar, ML4H 2025).

For bench cases with exactly one focal finding of a core label, the subject model (BLINDSPOT_MODEL_BENCH, or
--model) sees the radiograph with an A–H × 1–8 grid, is told which finding a radiologist marked, and returns
{cell, x, y, patient_side} as structured output. Scored against the radiologist instance mask:
point hit (inside the mask dilated by τ = 0.02·W), cell hit (named cell intersects the mask), patient-side
accuracy, primary-zone accuracy (point inside the finding's primary zone). Baselines: label-prior centroid
(practice split) and a random point inside the lungs (mean of 100 draws). Bootstrap 95% CIs over cases.

  uv run python -m eval.vlm_localization --dry-run            # mock VLM (label prior + noise), no API calls
  uv run python -m eval.vlm_localization                      # live: prints the estimate, needs --yes to spend
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from eval import adapters, render
from eval.common import (
    CORE_FOCAL,
    GALLERY_DIR,
    PALETTE,
    PRICES_SOURCE,
    SEQ_BLUES,
    CallPlan,
    CaseSource,
    ResponseCache,
    SpendTracker,
    add_common_args,
    bootstrap_ci,
    bootstrap_paired_diff,
    canonical_json,
    cases_for_split,
    chart_style,
    check_budget,
    estimate_cost,
    fmt_num,
    fmt_pct,
    image_tokens,
    live_preflight,
    load_cases,
    md_table,
    parse_price_overrides,
    provenance_lines,
    resolve_source,
    run_title,
    stable_seed,
    text_tokens,
    watermark,
    write_json,
)
from eval.llm import LLMResult, StructuredCaller
from eval.scenarios import distance_from
from shared.contracts import Case, Finding

EXCLUDE_FLAGS = {"orientation_suspect", "negative_flag_mismatch"}
SIDES = ("right", "left", "midline")
EXPECTED_OUT_TOKENS = {"default": 1500, "high": 1500, "medium": 800, "low": 400}  # assumption; calibrated by cache
MAX_TOKENS = 8000  # generous: adaptive thinking at default effort must not truncate the answer
PROMPT = (
    "This is a frontal chest radiograph with a reference grid (columns A–H, rows 1–8). A radiologist "
    "identified a {display} on this image. Return the grid cell containing its center, your estimate of its "
    "center in pixels (image {w}×{h}, x right, y down), and which side of the patient it is on."
)


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["cell", "x", "y", "patient_side"],
        "properties": {
            "cell": {"type": "string", "enum": render.all_cells()},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "patient_side": {"type": "string", "enum": list(SIDES)},
        },
    }


# ------------------------------------------------------------------------------------------------ selection
def focal_of(c: Case) -> list[Finding]:
    return [f for f in c.findings if f.kind == "focal"]


SELECTIONS = ("strict", "single-label", "labeled")


def candidate_labels(c: Case, selection: str) -> list[str]:
    """Core focal labels this case can be asked about under `selection`.
    strict (SPEC §12.1): exactly one focal finding. single-label: every focal instance has the same label.
    labeled: any core focal label present (other findings may also be on the film)."""
    f = focal_of(c)
    if c.is_normal or not f or set(c.qa_flags) & EXCLUDE_FLAGS:
        return []
    labels = sorted({x.label for x in f} & set(CORE_FOCAL))
    if selection == "strict":
        return labels if len(f) == 1 else []
    if selection == "single-label":
        return labels if len({x.label for x in f}) == 1 else []
    return labels


def select_cases(
    cases: list[Case],
    src: CaseSource,
    per_label: int = 25,
    max_total: int = 200,
    seed: int = 0,
    selection: str = "strict",
) -> list[tuple[Case, str]]:
    """(case, target label) pairs; each case used once; ≤ per_label per label (rarest labels filled first),
    ≤ max_total overall (seeded, label-balanced round-robin)."""
    bench = cases_for_split(cases, "bench", src)
    by_label: dict[str, list[Case]] = defaultdict(list)
    for c in sorted(bench, key=lambda c: c.case_id):
        for lab in candidate_labels(c, selection):
            by_label[lab].append(c)
    rng = random.Random(seed)
    used: set[str] = set()
    pools: dict[str, list[Case]] = {}
    for lab in sorted(by_label, key=lambda k: (len(by_label[k]), k)):
        lst = [c for c in by_label[lab] if c.case_id not in used]
        rng.shuffle(lst)
        pools[lab] = lst[:per_label]
        used |= {c.case_id for c in pools[lab]}
    out: list[tuple[Case, str]] = []
    while len(out) < max_total and any(pools.values()):  # round-robin so a total cap keeps the label mix
        for lab in sorted(pools):
            if pools[lab] and len(out) < max_total:
                out.append((pools[lab].pop(0), lab))
    return out


def eligible_counts(cases: list[Case], src: CaseSource) -> dict[str, dict[str, int]]:
    bench = cases_for_split(cases, "bench", src)
    return {sel: dict(Counter(lab for c in bench for lab in candidate_labels(c, sel))) for sel in SELECTIONS}


# ------------------------------------------------------------------------------------------------ geometry
@dataclass
class CaseGeom:
    case: Case
    findings: list[Finding]  # every focal instance of the target label (1 in strict mode)
    mask: np.ndarray  # union of their masks
    dist: np.ndarray  # px distance to the union mask
    zones: dict[str, np.ndarray]
    zones_approx: bool
    midline: float
    lungs: np.ndarray
    lungs_source: str

    @property
    def finding(self) -> Finding:
        return self.findings[0]

    @property
    def label(self) -> str:
        return self.findings[0].label

    @property
    def side(self) -> str | None:
        sides = {f.side for f in self.findings}
        if None in sides:
            return None
        return sides.pop() if len(sides) == 1 else "bilateral"

    @property
    def tau(self) -> float:
        return float(adapters.cfg_scoring()["hit"]["tolerance_frac"]) * self.case.width


def geom(case: Case, repo: Any, label: str | None = None) -> CaseGeom:
    fs = [f for f in focal_of(case) if label is None or f.label == label]
    m = np.zeros((case.height, case.width), bool)
    for f in fs:
        fm = repo.mask(case.case_id, f.finding_id)
        if fm is None:
            x0, y0, x1, y1 = (int(round(v)) for v in f.geometry.bbox)
            fm = np.zeros_like(m)
            fm[y0:y1, x0:x1] = True
        m |= fm
    zones, meta = repo.zones(case.case_id)
    approx = bool(meta.get("approximate")) or case.zones_approximate
    if "lungs" in zones and zones["lungs"].any():
        lungs, ls = zones["lungs"], "zones:lungs"
    elif "right_lung" in zones and "left_lung" in zones:
        lungs, ls = zones["right_lung"] | zones["left_lung"], "zones:right_lung|left_lung"
    else:
        lungs, ls = np.ones_like(m), "whole image (no lung mask)"
    return CaseGeom(
        case,
        fs,
        m,
        distance_from(m),
        zones,
        approx,
        float(meta.get("midline_x") or case.width / 2),
        lungs,
        ls + (" (approximate fixed-fraction zones)" if approx else ""),
    )


def side_of_point(g: CaseGeom, x: float) -> str:
    return "right" if x < g.midline else "left"  # patient right is displayed on the image left


@dataclass
class Score:
    valid: bool
    point_hit: float
    cell_hit: float
    side_correct: float | None
    point_side_correct: float | None
    zone_hit: float | None
    cell_consistent: float | None
    dist_norm: float | None
    stated_side: str | None = None
    point_side: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def score_point(g: CaseGeom, x: float, y: float, cell: str | None, side: str | None) -> Score:
    w, h = g.case.width, g.case.height
    inb = 0 <= x < w and 0 <= y < h
    xi, yi = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
    point_hit = float(inb and g.dist[yi, xi] <= g.tau)
    cell_hit = 0.0
    if cell:
        x0, y0, x1, y1 = render.cell_bbox(cell, w, h)
        cell_hit = float(g.mask[y0:y1, x0:x1].any())
    truth = g.side
    side_ok = None if truth not in SIDES else float(side == truth)
    pside = side_of_point(g, x)
    pside_ok = None if truth not in ("right", "left") else float(pside == truth)
    pzs = {f.primary_zone for f in g.findings if f.primary_zone and f.primary_zone in g.zones}
    zone_hit = None
    if pzs and not g.zones_approx:
        zone_hit = float(inb and any(bool(g.zones[z][yi, xi]) for z in pzs))
    dist = min(math.hypot(x - f.centroid[0], y - f.centroid[1]) for f in g.findings) / w
    return Score(
        True,
        point_hit,
        cell_hit,
        side_ok,
        pside_ok,
        zone_hit,
        None if cell is None else float(render.cell_of(x, y, w, h) == cell),
        dist,
        side,
        pside,
    )


def invalid_score(g: CaseGeom, reason: str) -> Score:
    truth = g.side
    has_zone = any(f.primary_zone for f in g.findings) and not g.zones_approx
    return Score(
        False,
        0.0,
        0.0,
        None if truth not in SIDES else 0.0,
        None,
        0.0 if has_zone else None,
        None,
        None,
        None,
        None,
        {"invalid": reason},
    )


# ------------------------------------------------------------------------------------------------ baselines
def label_priors(cases: list[Case], src: CaseSource) -> tuple[dict[str, tuple[float, float, int]], str]:
    """Mean normalized centroid per label over focal findings in the practice split."""
    pool = cases_for_split(cases, "practice", src)
    acc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for c in pool:
        for f in focal_of(c):
            acc[f.label].append((f.centroid[0] / c.width, f.centroid[1] / c.height))
    allpts = [p for v in acc.values() for p in v]
    pri = {k: (float(np.mean([p[0] for p in v])), float(np.mean([p[1] for p in v])), len(v)) for k, v in acc.items()}
    if allpts:
        pri["__all__"] = (float(np.mean([p[0] for p in allpts])), float(np.mean([p[1] for p in allpts])), len(allpts))
    note = (
        "practice split"
        if not src.synthetic
        else "ALL fixture cases (fixtures have no separate practice split, so the prior includes the test cases)"
    )
    return pri, note


def prior_point(g: CaseGeom, pri: dict[str, tuple[float, float, int]]) -> tuple[float, float]:
    px, py, _ = pri.get(g.label) or pri["__all__"]
    return px * g.case.width, py * g.case.height


def score_prior(g: CaseGeom, pri: dict[str, tuple[float, float, int]]) -> Score:
    x, y = prior_point(g, pri)
    return score_point(g, x, y, render.cell_of(x, y, g.case.width, g.case.height), side_of_point(g, x))


def score_random_lungs(g: CaseGeom, n_draws: int, seed: int) -> Score:
    ys, xs = np.nonzero(g.lungs)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, xs.size, size=n_draws)
    scores = [
        score_point(
            g,
            float(xs[i]) + 0.5,
            float(ys[i]) + 0.5,
            render.cell_of(xs[i] + 0.5, ys[i] + 0.5, g.case.width, g.case.height),
            side_of_point(g, float(xs[i])),
        )
        for i in idx
    ]

    def mean(attr: str) -> float | None:
        v = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
        return float(np.mean(v)) if v else None

    return Score(
        True,
        mean("point_hit") or 0.0,
        mean("cell_hit") or 0.0,
        mean("side_correct"),
        mean("point_side_correct"),
        mean("zone_hit"),
        None,
        mean("dist_norm"),
    )


# ------------------------------------------------------------------------------------------------ model calls
def mock_vlm(pri: dict[str, tuple[float, float, int]], seed: int):  # noqa: ANN201
    """Dry-run VLM: label prior + Gaussian noise (σ = 0.05·W); side and cell consistent with the point."""

    def fn(_req: dict[str, Any], g: CaseGeom) -> dict[str, Any]:
        rng = np.random.default_rng(stable_seed(seed, g.case.case_id))
        x, y = prior_point(g, pri)
        w, h = g.case.width, g.case.height
        x = float(np.clip(x + rng.normal(0, 0.05 * w), 0, w - 1))
        y = float(np.clip(y + rng.normal(0, 0.05 * h), 0, h - 1))
        return {
            "cell": render.cell_of(x, y, w, h),
            "x": round(x, 1),
            "y": round(y, 1),
            "patient_side": "right" if x < w / 2 else "left",
        }

    return fn


def request_content(g: CaseGeom, src_root: Path) -> list[dict[str, Any]]:
    gray = render.load_gray(src_root, g.case)
    block, _ = render.image_block(render.grid_overlay(gray))
    text = PROMPT.format(display=adapters.display(g.label).lower(), w=g.case.width, h=g.case.height)
    return [block, {"type": "text", "text": text}]


def score_vlm(g: CaseGeom, r: LLMResult) -> Score:
    if not r.ok:
        return invalid_score(g, r.error or "no output")
    p = r.parsed or {}
    try:
        x, y = float(p["x"]), float(p["y"])
        cell = str(p["cell"]).upper()
        render.cell_bbox(cell, g.case.width, g.case.height)
        side = str(p["patient_side"])
    except (KeyError, TypeError, ValueError) as e:
        return invalid_score(g, f"schema: {e}")
    if not (math.isfinite(x) and math.isfinite(y)):
        return invalid_score(g, "non-finite coordinates")
    return score_point(g, x, y, cell, side)


# ------------------------------------------------------------------------------------------------ analysis
METRICS = (
    ("point_hit", "Point hit"),
    ("cell_hit", "Cell hit"),
    ("side_correct", "Patient side"),
    ("zone_hit", "Primary zone"),
)


def summarize(rows: list[dict[str, Any]], methods: list[str], n_boot: int, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {"overall": {}, "by_label": {}}
    labels = sorted({r["label"] for r in rows})
    for scope, sub in [("overall", rows)] + [(lab, [r for r in rows if r["label"] == lab]) for lab in labels]:
        d: dict[str, Any] = {"n": len(sub)}
        for m in methods:
            d[m] = {k: bootstrap_ci([r[m][k] for r in sub], n_boot=n_boot, seed=seed) for k, _ in METRICS}
            d[m]["dist_norm_median"] = bootstrap_ci(
                [r[m]["dist_norm"] for r in sub], stat="median", n_boot=n_boot, seed=seed
            )
        if scope == "overall":
            out["overall"] = d
        else:
            out["by_label"][scope] = d
    return out


def laterality(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    conf: dict[str, Counter[str]] = defaultdict(Counter)
    convention = Counter()
    for r in rows:
        s = r[method]
        stated = s["stated_side"] or "no answer"
        conf[r["true_side"] or "unknown"][stated] += 1
        if (
            s["stated_side"] in ("right", "left")
            and s["point_side"] in ("right", "left")
            and r["true_side"] in ("right", "left")
        ):
            pt_ok = s["point_side"] == r["true_side"]
            st_ok = s["stated_side"] == r["true_side"]
            convention[
                ("point " + ("correct" if pt_ok else "wrong") + " half, side " + ("correct" if st_ok else "wrong"))
            ] += 1
    return {"confusion": {k: dict(v) for k, v in conf.items()}, "decomposition": dict(convention)}


def _short(ci: Any) -> str:
    return "n/a" if ci.n == 0 else fmt_pct(ci).split(", n=")[0] + f" (n={ci.n})"


def figures(
    summary: dict[str, Any], methods: list[str], names: dict[str, str], lat: dict[str, Any], out: Path, mark: str | None
) -> list[str]:
    chart_style()
    import matplotlib.pyplot as plt

    files = []
    groups = ["overall"] + sorted(summary["by_label"])
    colors = [PALETTE["s1"], PALETTE["s4"], PALETTE["s5"], PALETTE["s2"], PALETTE["s3"]]
    # models first (slots 1, 4, 5), then baselines (2, 3) — fixed by role, never by rank
    nmod = len([m for m in methods if not m.startswith("baseline:")])
    order_colors = colors[:nmod] + [PALETTE["s2"], PALETTE["s3"]]
    fig, ax = plt.subplots(figsize=(max(8, 1.6 * len(groups) + 3), 5.2))
    width = 0.8 / len(methods)
    for i, m in enumerate(methods):
        xs, ys, lo, hi = [], [], [], []
        for j, gname in enumerate(groups):
            d = summary["overall"] if gname == "overall" else summary["by_label"][gname]
            ci = d[m]["point_hit"]
            if ci.n == 0 or math.isnan(ci.point):
                continue
            xs.append(j + (i - (len(methods) - 1) / 2) * width)
            ys.append(100 * ci.point)
            lo.append(100 * (ci.point - ci.lo))
            hi.append(100 * (ci.hi - ci.point))
        ax.bar(
            xs,
            ys,
            width * 0.92,
            color=order_colors[i],
            label=names[m],
            yerr=[lo, hi],
            capsize=3,
            error_kw={"elinewidth": 1, "ecolor": PALETTE["ink2"]},
        )
    ns = [summary["overall"]["n"]] + [summary["by_label"][g]["n"] for g in groups[1:]]
    ax.set_xticks(range(len(groups)), [f"{g}\n(n={n})" for g, n in zip(groups, ns)])
    ax.set_ylabel("Point inside radiologist mask (± τ), %")
    ax.set_ylim(0, 100)
    ax.set_title("VLM localization vs baselines (95% bootstrap CI)")
    ax.legend(loc="upper right", ncol=1, fontsize=10)
    watermark(fig, mark)
    fig.tight_layout()
    p = out / "vlm_localization.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    files.append(p.name)

    first_model = methods[0]
    conf = lat[first_model]["confusion"]
    rows_ = [s for s in ("right", "left", "midline", "bilateral") if s in conf]
    cols_ = ["right", "left", "midline", "no answer"]
    if rows_:
        mat = np.array([[conf[r].get(c, 0) for c in cols_] for r in rows_], dtype=float)
        fig, ax = plt.subplots(figsize=(6.2, 1.2 + 0.9 * len(rows_)))
        from matplotlib.colors import LinearSegmentedColormap

        cmap = LinearSegmentedColormap.from_list("blues", SEQ_BLUES)
        ax.imshow(mat, cmap=cmap, vmin=0, vmax=max(1.0, mat.max()), aspect="auto")
        ax.grid(False)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(
                    j,
                    i,
                    int(mat[i, j]),
                    ha="center",
                    va="center",
                    color="white" if mat[i, j] > 0.6 * mat.max() else PALETTE["ink"],
                    fontsize=12,
                )
        ax.set_xticks(range(len(cols_)), [c if c == "no answer" else f"said {c}" for c in cols_])
        ax.set_yticks(range(len(rows_)), [f"truly {r}" for r in rows_])
        ax.set_title(f"Patient-side answers — {names[first_model]}", fontsize=12)
        watermark(fig, mark)
        fig.tight_layout()
        p = out / "vlm_laterality.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        files.append(p.name)
    return files


def write_gallery(rows: list[dict[str, Any]], geoms: dict[str, CaseGeom], src: CaseSource, k: int, tag: str) -> int:
    d = GALLERY_DIR / "vlm" / tag
    d.mkdir(parents=True, exist_ok=True)
    repo = adapters.repo_for(src.root)
    n = 0
    for r in rows[:k]:
        g = geoms[r["case_id"]]
        img = render.draw_outlines(render.grid_overlay(render.load_gray(src.root, g.case)), g.case, repo)
        for m, color in r.get("_points", []):
            render.point(img, m[0], m[1], color, "")
        import cv2

        cv2.imwrite(str(d / f"{r['case_id']}.png"), img)
        n += 1
    return n


# ------------------------------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--model", action="append", default=[], help="subject model(s); default BLINDSPOT_MODEL_BENCH")
    ap.add_argument("--per-label", type=int, default=25)
    ap.add_argument(
        "--selection",
        choices=list(SELECTIONS),
        default="strict",
        help="strict = exactly one focal finding (SPEC); single-label = all focal instances share one core label; "
        "labeled = any case containing the label (other findings may be present). Hit = any instance of the label.",
    )
    ap.add_argument("--max-total", type=int, default=200)
    ap.add_argument("--random-draws", type=int, default=100)
    ap.add_argument("--gallery", type=int, default=0, help="write K overlay PNGs to data/eval_galleries/vlm/")
    args = ap.parse_args(argv)

    from backend.app.settings import get_settings

    models = args.model or [get_settings().blindspot_model_bench]
    prices = parse_price_overrides(args.price)
    src = resolve_source(args.source)
    cases = load_cases(src)
    repo = adapters.repo_for(src.root)
    sel = select_cases(cases, src, args.per_label, args.limit or args.max_total, args.seed, args.selection)
    elig = eligible_counts(cases, src)
    print(
        f"[vlm] source={src.name} ({src.description}); selection={args.selection}; selected {len(sel)} cases: "
        f"{dict(Counter(lab for _, lab in sel))}"
    )
    if not sel:
        raise SystemExit("no eligible cases")
    pri, pri_note = label_priors(cases, src)
    geoms = {c.case_id: geom(c, repo, lab) for c, lab in sel}

    ns = "vlm/mock" if args.dry_run else "vlm/live"
    cache = ResponseCache(args.cache_dir, ns)
    contents = {cid: request_content(g, src.root) for cid, g in geoms.items()}
    schema = output_schema()
    callers = {}
    plans = []
    for m in models:
        c = StructuredCaller(
            model=m,
            cache=cache,
            dry_run=args.dry_run,
            mock_fn=mock_vlm(pri, args.seed),
            max_tokens=MAX_TOKENS,
            effort=args.effort,
        )
        callers[m] = c
        todo = [
            cid
            for cid in geoms
            if c.key_for(c.build_kwargs(system=None, content=contents[cid], schema=schema)) not in cache
        ]
        w, h = sel[0][0].width, sel[0][0].height
        in_tok = image_tokens(w, h) + text_tokens(PROMPT) + text_tokens(canonical_json(schema)) + 50
        observed = ResponseCache(args.cache_dir, "vlm/live").observed_output_tokens(m)
        out_tok = int(observed) if observed else EXPECTED_OUT_TOKENS[args.effort]
        plans.append(
            CallPlan(
                f"VLM localization{' (calibrated)' if observed else ''}", m, len(todo), in_tok, out_tok, MAX_TOKENS
            )
        )
    est = estimate_cost(plans, prices)
    check_budget(est, args.max_cost, dry_run=args.dry_run)
    live = live_preflight(args)
    if not args.dry_run and not live:
        return 0
    tracker = SpendTracker(args.max_cost, prices)
    for c in callers.values():
        c.tracker = tracker

    results: dict[str, dict[str, LLMResult]] = {m: {} for m in models}
    for m, c in callers.items():

        def one(cid: str, c: StructuredCaller = c) -> tuple[str, LLMResult]:
            return cid, c.call(system=None, content=contents[cid], schema=schema, mock_ctx=geoms[cid])

        if args.dry_run:
            pairs = [one(cid) for cid in geoms]
        else:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
                pairs = list(ex.map(one, geoms))
        results[m] = dict(pairs)

    methods = [f"model:{m}" for m in models] + ["baseline:label_prior", "baseline:random_lungs"]
    names = {f"model:{m}": (f"{m} (MOCK)" if args.dry_run else m) for m in models}
    names.update({"baseline:label_prior": "Label-prior centroid", "baseline:random_lungs": "Random point in lungs"})
    rows = []
    for i, (cid, g) in enumerate(geoms.items()):
        r: dict[str, Any] = {
            "case_id": cid,
            "label": g.label,
            "true_side": g.side,
            "n_instances": len(g.findings),
            "primary_zones": sorted({f.primary_zone or "" for f in g.findings}),
            "area_frac": float(sum(f.area_frac for f in g.findings)),
            "lungs_source": g.lungs_source,
        }
        for m in models:
            res = results[m][cid]
            r[f"model:{m}"] = score_vlm(g, res).__dict__
            r[f"model:{m}"]["raw"] = res.parsed
            r[f"model:{m}"]["error"] = res.error
        r["baseline:label_prior"] = score_prior(g, pri).__dict__
        r["baseline:random_lungs"] = score_random_lungs(g, args.random_draws, args.seed * 100_003 + i).__dict__
        pts = [(prior_point(g, pri), (0, 128, 255))]
        if results[models[0]][cid].ok:
            p = results[models[0]][cid].parsed or {}
            pts.append(((float(p.get("x", 0)), float(p.get("y", 0))), (46, 169, 240)))
        r["_points"] = pts
        rows.append(r)

    summary = summarize(rows, methods, args.n_boot, args.seed)
    lat = {m: laterality(rows, m) for m in methods}
    paired = {}
    for m in models:
        for b in ("baseline:label_prior", "baseline:random_lungs"):
            paired[(m, b)] = bootstrap_paired_diff(
                [r[f"model:{m}"]["point_hit"] for r in rows],
                [r[b]["point_hit"] for r in rows],
                n_boot=args.n_boot,
                seed=args.seed,
            )
    invalid = {
        m: Counter(str(r[f"model:{m}"]["extra"].get("invalid")) for r in rows if not r[f"model:{m}"]["valid"])
        for m in models
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mark = "DRY RUN — MOCK OUTPUTS" if args.dry_run else ("SYNTHETIC FIXTURES" if src.synthetic else None)
    figs = figures(summary, methods, names, lat, args.out_dir, mark)
    if args.gallery:
        n = write_gallery(rows, geoms, src, args.gallery, "mock" if args.dry_run else "live")
        print(f"[vlm] wrote {n} gallery PNGs to {GALLERY_DIR / 'vlm'} (never committed)")

    title = run_title("VLM localization benchmark", dry_run=args.dry_run, src=src)
    md = [f"# {title}", ""]
    if args.dry_run:
        md += [
            "> **DRY RUN.** The 'model' column is a mock (label prior + Gaussian noise), not a VLM. "
            "These numbers test the harness only and must not be quoted.",
            "",
        ]
    m0 = f"model:{models[0]}"
    o = summary["overall"]
    md += [
        "## Headline",
        "",
        f"- {names[m0]}: point inside the radiologist mask (±τ) in {fmt_pct(o[m0]['point_hit'])} of cases; "
        f"label-prior baseline {fmt_pct(o['baseline:label_prior']['point_hit'])}; random point in the lungs "
        f"{fmt_pct(o['baseline:random_lungs']['point_hit'])}.",
        f"- Difference vs label prior (paired, cases): {fmt_num(paired[(models[0], 'baseline:label_prior')], 2)} "
        "(proportion points).",
        f"- Patient side correct: {fmt_pct(o[m0]['side_correct'])}; cell hit: {fmt_pct(o[m0]['cell_hit'])}; "
        f"primary zone: {fmt_pct(o[m0]['zone_hit'])}.",
        f"- Invalid / refused / unparseable answers: {sum(invalid[models[0]].values())} of {o['n']} "
        f"({dict(invalid[models[0]]) or 'none'}) — scored as misses.",
        "",
    ]
    md += ["## Results by label (point hit, % [95% CI])", ""]
    header = ["label", "n"] + [names[m] for m in methods]
    tab = []
    for lab in ["overall"] + sorted(summary["by_label"]):
        d = o if lab == "overall" else summary["by_label"][lab]
        tab.append(
            [f"**{lab}**" if lab == "overall" else lab, d["n"]]
            + [fmt_pct(d[m]["point_hit"]).split(", n=")[0] for m in methods]
        )
    md += [md_table(header, tab), ""]
    md += ["## All metrics, overall", ""]
    tab = []
    for m in methods:
        tab.append([names[m]] + [_short(o[m][k]) for k, _ in METRICS] + [fmt_num(o[m]["dist_norm_median"], 3)])
    md += [md_table(["method"] + [n for _, n in METRICS] + ["median distance to centroid (× image width)"], tab), ""]
    md += [
        "## Laterality",
        "",
        "Rows: the finding's true patient side. Columns: the side the model stated. "
        "Patient right is displayed on the image left.",
        "",
    ]
    for m in [f"model:{mm}" for mm in models]:
        conf = lat[m]["confusion"]
        cols = ["right", "left", "midline", "no answer"]
        md += [
            f"**{names[m]}**",
            "",
            md_table(["true \\ said"] + cols, [[k] + [conf[k].get(c, 0) for c in cols] for k in sorted(conf)]),
            "",
        ]
        if lat[m]["decomposition"]:
            md += [
                "Decomposition (does a wrong side come from pointing at the wrong half, or from naming the side "
                "with the image-left/patient-right convention reversed?):",
                "",
            ]
            md += [md_table(["pattern", "cases"], sorted(lat[m]["decomposition"].items())), ""]
    sel_text = {
        "strict": "exactly one focal finding, of a core label (SPEC §12.1)",
        "single-label": "every focal instance shares one core label; a point on any instance of that label counts "
        "as a hit; side is 'bilateral' (side metric n/a) when instances span both sides",
        "labeled": "the case contains the asked-about core label (other findings may be present; each case is "
        "asked about one label, rarest labels assigned first); a point on any instance of that label counts as a "
        "hit; side is 'bilateral' (n/a) when its instances span both sides",
    }[args.selection]
    md += [
        "## Method",
        "",
        f"- Cases: bench split; {sel_text}; ≤ {args.per_label} per label, ≤ {args.max_total} total, seeded "
        f"sample (seed {args.seed}); excluded qa flags {sorted(EXCLUDE_FLAGS)}.",
        "- Eligible bench cases per label, by selection rule: "
        + "; ".join(f"{k}: {dict(sorted(v.items()))} (total {sum(v.values())})" for k, v in elig.items())
        + ".",
        "- Lung mask for the random baseline: "
        + ", ".join(f"{k} ×{v}" for k, v in Counter(r["lungs_source"] for r in rows).items())
        + ".",
        '- Prompt (structured output {cell, x, y, patient_side}): "'
        + PROMPT.format(display="{display}", w="{W}", h="{H}")
        + '"',
        "- Grid: columns A–H left→right, rows 1–8 top→bottom, drawn on the image (no padding, so pixel "
        "coordinates are the image's own).",
        f"- Point hit: inside the instance mask dilated by τ = {adapters.cfg_scoring()['hit']['tolerance_frac']}·W."
        " Cell hit: the named cell intersects the undilated mask. Primary zone: the point lies inside the finding's"
        " primary zone (n/a when zones are approximate). Patient side: stated side equals the finding's side.",
        f"- Label prior: mean normalized centroid of that label in the {pri_note}.",
        f"- Random in lungs: mean over {args.random_draws} uniform draws from the lung mask per case.",
        f"- CIs: percentile bootstrap over cases, {args.n_boot} resamples, seed {args.seed}; paired differences "
        "bootstrap the per-case difference.",
        "- Refusals, truncations and schema failures count as misses (no server-side model fallback, so every "
        "answer comes from the named model).",
        "",
    ]
    md += ["## Figures", ""] + [f"![{f}]({f})" for f in figs] + [""]
    md += (
        ["## Provenance", ""]
        + provenance_lines(
            models=", ".join(models),
            effort=args.effort,
            source=f"{src.name} — {src.description}",
            n_cases=len(rows),
            cache=str(cache.dir),
            prices=PRICES_SOURCE,
            spend=f"${tracker.spent:.2f} actual over {tracker.calls} live calls"
            if not args.dry_run
            else "$0.00 (dry run)",
        )
        + adapters.engine_status_lines()
    )
    md += [
        "",
        "## Interpretation",
        "",
        "Report the number as it is. Even a strong localization score would not make a VLM a source of truth "
        "for a tutor: Blindspot's truth comes from radiologist annotations by construction (RESEARCH.md §4).",
    ]
    (args.out_dir / "vlm_localization.md").write_text("\n".join(md) + "\n")

    for r in rows:
        r.pop("_points", None)
    write_json(
        args.out_dir / "vlm_localization.json",
        {
            "title": title,
            "dry_run": args.dry_run,
            "synthetic": src.synthetic,
            "models": models,
            "n": len(rows),
            "selection": args.selection,
            "eligible": elig,
            "summary": summary,
            "paired_vs_baselines": {f"{k[0]} - {k[1]}": v for k, v in paired.items()},
            "laterality": lat,
            "invalid": {m: dict(v) for m, v in invalid.items()},
            "estimate": est.__dict__,
            "spend_usd": tracker.spent,
            "rows": rows,
            "engine_status": dict(adapters.ENGINE_STATUS),
        },
    )
    print(f"[vlm] wrote {args.out_dir / 'vlm_localization.md'} and {', '.join(figs)}")
    print(
        f"[vlm] {names[m0]}: point hit {fmt_pct(o[m0]['point_hit'])}; label prior "
        f"{fmt_pct(o['baseline:label_prior']['point_hit'])}; random-in-lungs "
        f"{fmt_pct(o['baseline:random_lungs']['point_hit'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
