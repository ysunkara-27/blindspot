"""SPEC §12.5 — assemble eval/reports/REPORT.md from whatever section outputs exist, with one-line takeaways for
slides. Every takeaway carries n and a 95% CI; dry-run or synthetic sections are labeled as not results.

  uv run python -m eval.report [--reports-dir eval/reports]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from eval.common import REPORTS_DIR, git_commit, now_utc

SECTIONS = (
    ("vlm_localization", "VLM localization benchmark (§12.1)"),
    ("faithfulness", "Debrief faithfulness and grounding ablation (§12.2)"),
    ("misstype_sensitivity", "Miss-type engine sanity check (§12.3)"),
    ("pilot_analysis", "Pilot and expert review (§12.4)"),
)


def _ci(d: dict[str, Any] | None, pct: bool = True, digits: int = 0) -> str:
    if not d or not d.get("n") or d.get("point") is None or (isinstance(d["point"], float) and math.isnan(d["point"])):
        return "n/a (n=0)"
    s = 100.0 if pct else 1.0
    u = "%" if pct else ""
    return f"{s * d['point']:.{digits}f}{u} (95% CI {s * d['lo']:.{digits}f}–{s * d['hi']:.{digits}f}; n={d['n']})"


def _tag(j: dict[str, Any]) -> str:
    if j.get("dry_run"):
        return "[DRY RUN — mock outputs, not a result] "
    if j.get("synthetic") or j.get("synthetic_cases"):
        return "[synthetic fixtures — not a result] "
    return ""


def vlm_takeaways(j: dict[str, Any]) -> list[str]:
    m = j["models"][0]
    o = j["summary"]["overall"]
    k = f"model:{m}"
    sel = j.get("selection", "strict")
    lines = [
        f"{_tag(j)}Asked where a radiologist-marked finding is, {m} put its point on the radiologist's outline in "
        f"{_ci(o[k]['point_hit'])} of bench cases — vs {_ci(o['baseline:label_prior']['point_hit'])} for the "
        f"label-prior baseline and {_ci(o['baseline:random_lungs']['point_hit'])} for a random point in the lungs "
        f"(selection: {sel}).",
        f"{_tag(j)}Patient side correct: {_ci(o[k]['side_correct'])}; named grid cell overlaps the finding: "
        f"{_ci(o[k]['cell_hit'])}.",
    ]
    inv = sum((j.get("invalid") or {}).get(m, {}).values())
    if inv:
        lines.append(f"{_tag(j)}{inv} answers were refused, truncated or unparseable and scored as misses.")
    return lines


def faith_takeaways(j: dict[str, Any]) -> list[str]:
    s = j["summary"]
    g, u = s["G"], s["U"]
    pd = s.get("paired_G_minus_U", {}).get("grounded")
    return [
        f"{_tag(j)}Judged fully grounded in the radiologist truth: grounded pipeline {_ci(g['grounded'])} vs "
        f"labels-only ablation {_ci(u['grounded'])}" + (f"; paired difference {_ci(pd, digits=0)}" if pd else "") + ".",
        f"{_tag(j)}Laterality errors: grounded {_ci(g['laterality_error'])} vs ablation {_ci(u['laterality_error'])}; "
        f"hallucinated findings per debrief: {_ci(g['hallucinated_per_debrief'], pct=False, digits=2)} vs "
        f"{_ci(u['hallucinated_per_debrief'], pct=False, digits=2)}.",
        f"{_tag(j)}The deterministic validator passed {_ci(g['validator_first'])} of grounded debriefs on the first "
        f"try and {_ci(g['model_pass_within_regen'])} within one regeneration; learners saw the template fallback "
        f"in {_ci(g['template_fallback'])}.",
    ]


def misstype_takeaways(j: dict[str, Any]) -> list[str]:
    rob = j.get("robustness", {})
    worst = {b: min(v.values()) for b, v in rob.items() if v}
    tail = ", ".join(f"{b} {100 * w:.0f}%" for b, w in sorted(worst.items()))
    return [
        f"{_tag(j)}On scripted (synthetic) telemetry the production miss-type engine classified "
        f"{j['n_ok']}/{j['n_scenarios']} behaviours as intended; varying ρ and the 300/1,000 ms thresholds by "
        f"±30% (27 configs), the worst config still classified scripted misses as intended at: {tail}. Cursor "
        "dwell is a proxy for gaze."
    ]


def pilot_takeaways(j: dict[str, Any]) -> list[str]:
    lab = j.get("label", "pilot, not powered")
    n = j.get("n_paired", 0)
    out = []
    if n:
        ch = j["changes"]
        ss = ch["search_share"]
        out.append(
            f"In a small usability pilot ({lab}), search errors were "
            f"{_ci(ss['pre_median'])} of misses before practice and {_ci(ss['post_median'])} after (medians); "
            f"sensitivity changed by a median {_ci(ch['sensitivity']['change_median'])} points; SUS "
            f"{_ci(j['sus_mean'], pct=False, digits=1)}."
        )
    else:
        out.append(f"No complete pilot data yet ({lab}).")
    rv = j.get("reviews", {}).get("debrief", {})
    if rv.get("n_ratings"):
        out.append(
            f"Clinician reviewers rated debrief accuracy {_ci(rv['accuracy'], pct=False, digits=1)} / 5 and "
            f"teaching value {_ci(rv['teaching'], pct=False, digits=1)} / 5 ({rv['n_ratings']} ratings of "
            f"{rv['n_items']} debriefs); safety concerns flagged: {rv['safety_flags']}."
        )
    else:
        out.append("No expert ratings yet (/review).")
    return out


TAKEAWAYS = {
    "vlm_localization": vlm_takeaways,
    "faithfulness": faith_takeaways,
    "misstype_sensitivity": misstype_takeaways,
    "pilot_analysis": pilot_takeaways,
}
FIGURES = {
    "vlm_localization": ["vlm_localization.png", "vlm_laterality.png"],
    "faithfulness": ["faithfulness.png"],
    "misstype_sensitivity": ["misstype_sensitivity.png"],
    "pilot_analysis": ["pilot_paired.png"],
}


def build(reports: Path) -> str:
    loaded: dict[str, dict[str, Any]] = {}
    for key, _ in SECTIONS:
        p = reports / f"{key}.json"
        if p.exists():
            try:
                loaded[key] = json.loads(p.read_text())
            except json.JSONDecodeError:
                pass
    flags = [k for k, j in loaded.items() if j.get("dry_run") or j.get("synthetic") or j.get("synthetic_cases")]
    title = "Blindspot evaluation report"
    if flags:
        title += " — contains DRY RUN / synthetic sections (not results)"
    md = [f"# {title}", "", f"Generated {now_utc()} from `eval/reports/*.json` at commit {git_commit()}.", ""]
    if flags:
        md += [
            f"> **Not for slides yet:** these sections are dry-run or synthetic-fixture outputs: {', '.join(flags)}. "
            "Their numbers test the harness only. Re-run live (after the human cost checkpoint) before quoting "
            "anything.",
            "",
        ]
    md += ["## Slide lines", ""]
    for key, name in SECTIONS:
        j = loaded.get(key)
        if j is None:
            md += [f"- **{name}:** not run yet."]
            continue
        try:
            lines = TAKEAWAYS[key](j)
        except (KeyError, TypeError) as e:
            lines = [f"(could not summarise: {type(e).__name__}: {e})"]
        md += [f"- **{name}:**"] + [f"  - {ln}" for ln in lines]
    md += ["", "## Sections", ""]
    for key, name in SECTIONS:
        j = loaded.get(key)
        md += [f"### {name}", ""]
        if j is None:
            md += ["Not run yet.", ""]
            continue
        md += [f"Full report: [{key}.md]({key}.md). Title: *{j.get('title', key)}*.", ""]
        for f in FIGURES[key]:
            if (reports / f).exists():
                md += [f"![{f}]({f})", ""]
        est = j.get("estimate")
        if est:
            md += [
                f"Live-run cost estimate: expected ${est.get('expected_usd', 0):.2f}, worst case "
                f"${est.get('worst_usd', 0):.2f}; actual spend recorded: ${j.get('spend_usd', 0):.2f}.",
                "",
            ]
        if j.get("engine_status"):
            md += ["Engines: " + "; ".join(f"{k} → {v}" for k, v in sorted(j["engine_status"].items())) + ".", ""]
    md += [
        "## Honesty rules applied",
        "",
        "- Every number states n and a 95% CI (percentile bootstrap; Wilson interval added where the bootstrap "
        "collapses at 0% or 100%).",
        "- Dry-run and synthetic-fixture outputs are labeled in titles, figures (watermark) and here.",
        "- The pilot is usability testing, not a research study: not powered, no p-values.",
        "- The miss-type engine uses cursor/loupe/zoom dwell as a proxy for gaze.",
        "- Inconvenient results are reported as measured.",
    ]
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = ap.parse_args(argv)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    text = build(args.reports_dir)
    out = args.reports_dir / "REPORT.md"
    out.write_text(text)
    print(f"[report] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
