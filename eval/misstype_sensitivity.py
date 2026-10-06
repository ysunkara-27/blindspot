"""SPEC §12.3 — miss-type engine sanity check: scripted telemetry replays through the PRODUCTION dwell and miss-type
functions (backend.app.search), and sensitivity to ρ and the 300 / 1,000 ms thresholds (±30%).

Pure Python, no API calls (--dry-run / --max-cost are accepted for a uniform CLI and do nothing). Telemetry is
synthetic by design: it is a test input that encodes an intended behaviour.

  uv run python -m eval.misstype_sensitivity [--source fixtures|data] [--limit N]
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from eval import adapters, scenarios
from eval.common import (
    PALETTE,
    add_common_args,
    cases_for_split,
    chart_style,
    load_cases,
    md_table,
    provenance_lines,
    resolve_source,
    watermark,
    write_json,
)
from eval.scenarios import Ctx, Tape, interior_point
from shared.contracts import Case

MULTS = (0.7, 1.0, 1.3)
SHORT = {"missed_search": "search", "missed_recognition": "recognition", "missed_decision": "decision"}
DURATIONS = (0, 100, 200, 250, 300, 350, 400, 500, 700, 800, 900, 1000, 1100, 1300, 1500, 2000)
DISTANCES = (0.25, 0.5, 0.75, 1.0, 1.15, 1.25, 1.5, 2.0)  # × default ρ, from the lesion edge


def configs(base: dict[str, Any]) -> list[dict[str, Any]]:
    """Full factorial: ρ × recognition threshold × decision threshold, each at 0.7 / 1.0 / 1.3 of default."""
    out = []
    for mr in MULTS:
        for m1 in MULTS:
            for m2 in MULTS:
                c = copy.deepcopy(base)
                c["roi"]["roi_frac"] = base["roi"]["roi_frac"] * mr
                c["miss_types"]["recognition_ms"] = base["miss_types"]["recognition_ms"] * m1
                c["miss_types"]["decision_ms"] = base["miss_types"]["decision_ms"] * m2
                c["_name"] = f"ρ×{mr} rec×{m1} dec×{m2}"
                c["_mult"] = (mr, m1, m2)
                out.append(c)
    return out


def pick_cases(cases: list[Case], src: Any, limit: int | None) -> list[Case]:
    pool = [
        c for c in cases_for_split(cases, "bench", src) if any(f.kind == "focal" for f in c.findings) or c.is_normal
    ]
    pool = sorted(pool, key=lambda c: c.case_id)
    if limit:
        abn = [c for c in pool if not c.is_normal][:limit]
        nor = [c for c in pool if c.is_normal][: max(1, limit // 4)]
        pool = abn + nor
    return pool


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, api=False)
    args = ap.parse_args(argv)
    print("[misstype] no API calls; cost $0.00")
    src = resolve_source(args.source)
    cases = pick_cases(load_cases(src), src, args.limit or (None if src.synthetic else 30))
    repo = adapters.repo_for(src.root)
    base = adapters.cfg_scoring()

    # ---- 1. end-to-end: every behaviour through the production scoring + search engines (default config)
    scs, skips = scenarios.generate(cases, repo, base)
    by_case = {c.case_id: c for c in cases}
    e2e: dict[str, Counter[str]] = defaultdict(Counter)
    marks_ok = Counter()
    rows_e2e = []
    for sc in scs:
        res = adapters.score_attempt(by_case[sc.case_id], sc.submit, repo, base)
        actual = res.result_by_target()
        tgt = sc.target
        if tgt:
            e2e[sc.intended[tgt]][actual.get(tgt, "—")] += 1
        cmp = scenarios.compare(sc.intended, actual)
        ok = all(v[2] for v in cmp.values())
        marks_ok["ok" if ok else "mismatch"] += 1
        rows_e2e.append(
            {
                "scenario": sc.scenario_id,
                "behaviour": sc.behaviour,
                "ok": ok,
                "mismatches": {k: v[:2] for k, v in cmp.items() if not v[2]},
                "dwell": res.dwell_by_finding,
            }
        )

    # Geometry and ROIs are computed once per (case, finding, ρ multiplier); dwell once per (telemetry, ρ);
    # thresholds only re-label a dwell value.
    rho0 = base["roi"]["roi_frac"]
    ctxs: dict[str, Ctx] = {}
    rois: dict[tuple[str, str, float], np.ndarray] = {}

    def ctx_of(c: Case) -> Ctx:
        if c.case_id not in ctxs:
            ctxs[c.case_id] = Ctx(c, repo, base)
        return ctxs[c.case_id]

    def roi(c: Case, fid: str, mr: float) -> np.ndarray:
        k = (c.case_id, fid, mr)
        if k not in rois:
            rois[k] = adapters.dilate(ctx_of(c).masks[fid], rho0 * mr * c.width)
        return rois[k]

    def label(dwell: float, m1: float = 1.0, m2: float = 1.0) -> str:
        mt = {
            "recognition_ms": base["miss_types"]["recognition_ms"] * m1,
            "decision_ms": base["miss_types"]["decision_ms"] * m2,
        }
        return adapters.miss_type(dwell, mt)

    # ---- 2. robustness of the three miss behaviours across the 27 configs
    cfgs = configs(base)
    miss = [s for s in scs if s.behaviour in SHORT]
    robust: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    dwell_seen: dict[str, list[float]] = defaultdict(list)
    for sc in miss:
        case = by_case[sc.case_id]
        dw = {mr: adapters.dwell_ms(sc.submit.telemetry, roi(case, sc.target, mr), base["dwell"]) for mr in MULTS}
        dwell_seen[sc.behaviour].append(dw[1.0])
        for c in cfgs:
            mr, m1, m2 = c["_mult"]
            robust[sc.behaviour][c["_name"]].append(float(label(dw[mr], m1, m2) == sc.behaviour))

    # ---- 3. dwell-duration boundary sweep (linger at the lesion's interior point)
    thr_variants = [(m1, m2) for m1 in MULTS for m2 in MULTS]
    targets = []
    for c in cases:
        foc = [f for f in c.findings if f.kind == "focal"]
        if foc:
            targets.append((c, foc[0]))
    sweep: dict[int, dict[str, Counter[str]]] = {
        d: {f"rec×{a} dec×{b}": Counter() for a, b in thr_variants} for d in DURATIONS
    }
    for c, f in targets:
        ctx = ctx_of(c)
        x, y = interior_point(ctx.masks[f.short_id])
        for d in DURATIONS:
            tape = Tape(c.width, c.height)
            if d > 0:
                tape.linger(x, y, d, ctx.jitter)
            else:
                tape.leave()
            dwell = adapters.dwell_ms(tape.events, roi(c, f.short_id, 1.0), base["dwell"])
            for m1, m2 in thr_variants:
                sweep[d][f"rec×{m1} dec×{m2}"][SHORT[label(dwell, m1, m2)]] += 1

    # ---- 4. near-miss distance sweep: linger 2 s at k·ρ from the lesion edge, classify under ρ×{0.7,1,1.3}
    dist_tab: dict[float, dict[float, Counter[str]]] = {k: {mr: Counter() for mr in MULTS} for k in DISTANCES}
    for c, f in targets:
        ctx = ctx_of(c)
        dmap = ctx.dist[f.short_id]
        lungs = ctx.zones.get("lungs")
        cx, cy = f.centroid
        for k in DISTANCES:
            cand = np.abs(dmap - k * rho0 * c.width) <= 1.0
            if lungs is not None and (cand & lungs).any():
                cand &= lungs
            ys, xs = np.nonzero(cand)
            if xs.size == 0:
                continue
            i = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
            tape = Tape(c.width, c.height)
            tape.linger(float(xs[i]) + 0.5, float(ys[i]) + 0.5, 2000.0, 1.1)
            for mr in MULTS:
                dwell = adapters.dwell_ms(tape.events, roi(c, f.short_id, mr), base["dwell"])
                dist_tab[k][mr][SHORT[label(dwell)]] += 1

    # ---- report
    args.out_dir.mkdir(parents=True, exist_ok=True)
    synth = "synthetic scripted telemetry on " + ("synthetic fixtures" if src.synthetic else "ChestX-Det masks")
    title = f"Miss-type engine sanity check — {synth}"
    md = [
        f"# {title}",
        "",
        "> Scripted telemetry is a synthetic test input by design (it encodes an intended behaviour); these tables "
        "check the engine's logic, not learner behaviour.",
        "",
    ]
    n_ok = marks_ok["ok"]
    md += [
        "## 1. Intended vs classified, end to end (default config)",
        "",
        f"All outcome targets (findings and marks) as intended in **{n_ok}/{len(scs)}** scenarios "
        f"across {len({s.case_id for s in scs})} cases.",
        "",
    ]
    res_cols = ["found", "mislabeled", "missed_search", "missed_recognition", "missed_decision", "—"]
    md += [
        md_table(
            ["intended (target finding) \\ classified"] + res_cols,
            [[k] + [e2e[k].get(c, 0) for c in res_cols] for k in sorted(e2e)],
        ),
        "",
    ]
    md += [f"Skipped scenario constructions: {dict(Counter(s.reason for s in skips)) or 'none'}.", ""]
    md += [
        "Measured target dwell at the default config (ms): "
        + "; ".join(
            f"{SHORT[b]}: median {np.median(v):.0f} (min {min(v):.0f}, max {max(v):.0f}, n={len(v)})"
            for b, v in sorted(dwell_seen.items())
        )
        + ".",
        "",
    ]

    md += [
        "## 2. Robustness: % of scripted misses classified as intended, across ρ and thresholds ±30%",
        "",
        "27 configs (ρ, recognition and decision thresholds each at 0.7×, 1.0×, 1.3× of "
        f"ρ = {rho0}·W, {base['miss_types']['recognition_ms']} ms, {base['miss_types']['decision_ms']} ms).",
        "",
    ]
    tab = []
    for b in ("missed_search", "missed_recognition", "missed_decision"):
        if b not in robust:
            continue
        per = {name: float(np.mean(v)) for name, v in robust[b].items()}
        worst = min(per.items(), key=lambda kv: kv[1])
        worst_s = f"{100 * worst[1]:.0f}% ({worst[0]})" if worst[1] < 1.0 else "100% (all configs)"
        tab.append(
            [
                SHORT[b],
                len(robust[b][cfgs[0]["_name"]]),
                f"{100 * per[cfgs[13]['_name']]:.0f}%",
                f"{100 * np.mean(list(per.values())):.0f}%",
                worst_s,
                sum(1 for v in per.values() if v < 1.0),
            ]
        )
    md += [
        md_table(
            ["behaviour", "scenarios", "default config", "mean over 27 configs", "worst config", "configs < 100%"], tab
        ),
        "",
    ]
    flips = []
    for b in robust:
        for name, v in robust[b].items():
            if np.mean(v) < 1.0:
                flips.append((SHORT[b], name, f"{100 * np.mean(v):.0f}%"))
    if flips:
        md += [
            "Configs where a scripted behaviour is not always classified as intended:",
            "",
            md_table(["behaviour", "config", "% as intended"], sorted(flips)[:40]),
            "",
        ]

    md += [
        "## 3. Dwell duration vs label under threshold variants",
        "",
        f"Pointer lingering on the lesion for the scripted duration ({len(targets)} findings each; cell = label "
        "counts, s/r/d = search/recognition/decision).",
        "",
    ]
    hdr = ["scripted ms"] + [f"rec×{m1} dec×{m2}" for m1, m2 in thr_variants]
    md += [md_table(hdr, [[d] + [_fmt_counts(sweep[d][h]) for h in hdr[1:]] for d in DURATIONS]), ""]

    md += [
        "## 4. Near misses: 2 s of dwell at a distance from the lesion edge, under ρ ±30%",
        "",
        f"Distance in units of the default ρ ({rho0}·W). The ROI is the mask dilated by ρ, so attention just "
        "outside the ROI counts as 'never looked there'.",
        "",
    ]
    md += [
        md_table(
            ["distance (×ρ)"] + [f"ρ×{m}" for m in MULTS],
            [[k] + [_fmt_counts(dist_tab[k][m]) for m in MULTS] for k in DISTANCES],
        ),
        "",
    ]

    fig = _figure(sweep, dist_tab, thr_variants, args.out_dir, "SYNTHETIC FIXTURES" if src.synthetic else None)
    md += ["## Figure", "", f"![{fig}]({fig})", ""]
    md += [
        "## Takeaways",
        "",
        f"- The production engine classified {n_ok}/{len(scs)} scripted behaviours as intended.",
        "- Classification is a step function of dwell; ±30% threshold changes only move behaviours whose dwell sits "
        "near a boundary (see §3). The scripted 'recognition' pass (~500 ms) and 'decision' linger (~2 s) are far "
        "from the defaults, so §2 measures robustness of the scripts, while §3–§4 show where labels would flip.",
        "- ρ matters for near misses: attention just outside the ROI is a 'search' error at the default ρ "
        "(see §4). Cursor and loupe dwell is a proxy for gaze; validation against eye tracking is roadmap work.",
        "",
    ]
    md += (
        ["## Provenance", ""]
        + provenance_lines(source=f"{src.name} — {src.description}", n_cases=len(cases), n_scenarios=len(scs))
        + adapters.engine_status_lines()
    )
    (args.out_dir / "misstype_sensitivity.md").write_text("\n".join(md) + "\n")
    write_json(
        args.out_dir / "misstype_sensitivity.json",
        {
            "title": title,
            "dry_run": False,
            "synthetic_telemetry": True,
            "synthetic_cases": src.synthetic,
            "n_scenarios": len(scs),
            "n_ok": n_ok,
            "end_to_end": {k: dict(v) for k, v in e2e.items()},
            "robustness": {SHORT[b]: {k: float(np.mean(v)) for k, v in d.items()} for b, d in robust.items()},
            "rows": rows_e2e,
            "engine_status": dict(adapters.ENGINE_STATUS),
        },
    )
    print(f"[misstype] {n_ok}/{len(scs)} scenarios as intended; wrote {args.out_dir / 'misstype_sensitivity.md'}")
    return 0


def _fmt_counts(c: Counter[str]) -> str:
    return " ".join(f"{k[0]}{c[k]}" for k in ("search", "recognition", "decision") if c.get(k)) or "—"


def _figure(
    sweep: dict[int, dict[str, Counter[str]]],
    dist_tab: dict[float, dict[float, Counter[str]]],
    thr_variants: list[tuple[float, float]],
    out: Any,
    mark: str | None,
) -> str:
    chart_style()
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    cmap = ListedColormap([PALETTE["s1"], PALETTE["s4"], PALETTE["s2"]])  # search, recognition, decision
    code = {"search": 0, "recognition": 1, "decision": 2}

    def majority(c: Counter[str]) -> int:
        return code[c.most_common(1)[0][0]] if c else -1

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), gridspec_kw={"width_ratios": [1.6, 1]})
    cols = [f"rec×{a}\ndec×{b}" for a, b in thr_variants]
    m = np.array([[majority(sweep[d][f"rec×{a} dec×{b}"]) for a, b in thr_variants] for d in DURATIONS], float)
    ax = axes[0]
    ax.imshow(np.ma.masked_less(m, 0), cmap=cmap, vmin=0, vmax=2, aspect="auto")
    ax.grid(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if m[i, j] >= 0:
                ax.text(j, i, "srd"[int(m[i, j])], ha="center", va="center", color="white", fontsize=9)
    ax.set_xticks(range(len(cols)), cols, fontsize=8)
    ax.set_yticks(range(len(DURATIONS)), [str(d) for d in DURATIONS], fontsize=9)
    ax.set_ylabel("scripted dwell on the lesion (ms)")
    ax.set_title("Label vs dwell and thresholds", fontsize=12)
    m2 = np.array([[majority(dist_tab[k][r]) for r in MULTS] for k in DISTANCES], float)
    ax = axes[1]
    ax.imshow(np.ma.masked_less(m2, 0), cmap=cmap, vmin=0, vmax=2, aspect="auto")
    ax.grid(False)
    for i in range(m2.shape[0]):
        for j in range(m2.shape[1]):
            if m2[i, j] >= 0:
                ax.text(j, i, "srd"[int(m2[i, j])], ha="center", va="center", color="white", fontsize=10)
    ax.set_xticks(range(len(MULTS)), [f"ρ×{r}" for r in MULTS])
    ax.set_yticks(range(len(DISTANCES)), [str(k) for k in DISTANCES])
    ax.set_ylabel("2 s dwell at distance from lesion edge (× default ρ)")
    ax.set_title("Near misses vs ρ", fontsize=12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (PALETTE["s1"], PALETTE["s4"], PALETTE["s2"])]
    fig.legend(
        handles,
        ["s = search", "r = recognition", "d = decision"],
        loc="lower center",
        ncol=3,
        bbox_to_anchor=(0.5, -0.01),
    )
    watermark(fig, mark)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    p = out / "misstype_sensitivity.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


if __name__ == "__main__":
    raise SystemExit(main())
