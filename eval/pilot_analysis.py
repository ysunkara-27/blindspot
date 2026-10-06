"""SPEC §12.4 — pilot analysis (usability testing, not a research study).

Reads the SQLite DB (§13.1; path from settings or --db). Per participant: assessment A or B (pre) → practice → the
other assessment (post), counterbalanced by participant-code parity (odd → A first, even → B first). Reports
per-participant and median paired changes in case-level sensitivity, specificity, lesion localization fraction,
false positives per image and miss-type mix, with bootstrap CIs, plus the SUS score and expert-review ratings.
Metric definitions are the production ones (backend.app.analytics.learner.case_level_stats) so the numbers match the
app's assessment summary. No p-values, by design.

  uv run python -m eval.pilot_analysis [--db data/blindspot.sqlite]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.common import (
    PALETTE,
    REPORTS_DIR,
    bootstrap_ci,
    chart_style,
    fmt_num,
    md_table,
    provenance_lines,
    write_json,
)

LOCALIZED = ("found", "mislabeled")
FOCAL_RESULTS = ("found", "mislabeled", "missed_search", "missed_recognition", "missed_decision")
PATTERN_RESULTS = ("pattern_found", "pattern_missed")
BUCKET = {
    "missed_search": "search",
    "missed_recognition": "recognition",
    "missed_decision": "decision",
    "mislabeled": "interpretation",
    "false_positive": "overcall",
}
BUCKETS = ("search", "recognition", "decision", "interpretation", "overcall")
METRICS = (
    ("sensitivity", "Sensitivity (case level)"),
    ("specificity", "Specificity (case level)"),
    ("localization_fraction", "Lesion localization fraction"),
    ("false_positives_per_image", "False positives per image"),
    ("search_share", "Search errors / all misses"),
)


def label(n: int) -> str:
    return f"pilot, n = {n}, not powered; usability testing, not a research study"


# ------------------------------------------------------------------------------------------------ metrics
def case_level_stats(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Production definitions when importable (backend.app.analytics.learner), else the identical local copy."""
    try:
        from backend.app.analytics.learner import case_level_stats as prod

        return dict(prod(records))
    except ImportError:
        pass
    abn = [r for r in records if not r["is_normal"]]
    nor = [r for r in records if r["is_normal"]]
    det = [any(o["result"] in (*LOCALIZED, "pattern_found") for o in r["outcomes"]) for r in abn]
    clean = [not any(o["result"] in ("false_positive", "pattern_false") for o in r["outcomes"]) for r in nor]
    focal = [o["result"] for r in records for o in r["outcomes"] if o["result"] in FOCAL_RESULTS]
    fp = sum(o["result"] == "false_positive" for r in records for o in r["outcomes"])
    mix = Counter(BUCKET[o["result"]] for r in records for o in r["outcomes"] if o["result"] in BUCKET)
    return {
        "n": len(records),
        "n_abnormal": len(abn),
        "n_normal": len(nor),
        "sensitivity": sum(det) / len(abn) if abn else None,
        "specificity": sum(clean) / len(nor) if nor else None,
        "localization_fraction": sum(x in LOCALIZED for x in focal) / len(focal) if focal else None,
        "false_positives_per_image": fp / len(records) if records else 0.0,
        "miss_type_mix": {b: int(mix.get(b, 0)) for b in BUCKETS},
    }


def record_from_row(row: dict[str, Any], truth: dict[str, bool]) -> dict[str, Any] | None:
    """Attempt row → the record shape case_level_stats expects. Findings are recovered from the outcomes (the
    scorer emits one outcome per ground-truth finding); case normality from cases.jsonl when available."""
    if row.get("submitted_at") is None or not row.get("outcomes_json"):
        return None
    outs = json.loads(row["outcomes_json"])
    findings = [
        {"id": o["target"], "kind": "focal" if o["result"] in FOCAL_RESULTS else "pattern", "label": ""}
        for o in outs
        if o["result"] in FOCAL_RESULTS + PATTERN_RESULTS
    ]
    inferred_normal = not findings
    is_normal = truth.get(row["case_id"], inferred_normal)
    return {
        "case_id": row["case_id"],
        "is_normal": is_normal,
        "outcomes": outs,
        "findings": findings,
        "score": float(row.get("score") or 0.0),
        "success": bool(row.get("success")),
    }


def session_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    st = case_level_stats(records)
    mix = st.get("miss_type_mix", {})
    misses = sum(mix.get(b, 0) for b in ("search", "recognition", "decision"))
    st["search_share"] = mix.get("search", 0) / misses if misses else None
    return st


def code_parity(code: str | None) -> int | None:
    m = re.search(r"(\d+)", code or "")
    return int(m.group(1)) % 2 if m else None


def sus_from_answers(answers: list[int]) -> float:
    """Standard SUS (same formula as backend.app.routes.pilot.sus_score)."""
    return sum((a - 1) if i % 2 == 0 else (5 - a) for i, a in enumerate(answers)) * 2.5


# ------------------------------------------------------------------------------------------------ loading
def load(db: Path) -> dict[str, list[dict[str, Any]]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = {}
    for t in ("learners", "sessions", "attempts", "sus", "reviews"):
        try:
            out[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t}")]
        except sqlite3.OperationalError:
            out[t] = []
    con.close()
    return out


def case_truth() -> dict[str, bool]:
    try:
        from eval.common import load_cases, resolve_source

        src = resolve_source("data")
        return {c.case_id: c.is_normal for c in load_cases(src)}
    except SystemExit:
        return {}


def analyse(
    tables: dict[str, list[dict[str, Any]]], truth: dict[str, bool], min_cases: int, n_boot: int, seed: int
) -> dict[str, Any]:
    learners = {r["id"]: r for r in tables["learners"] if r.get("participant_code")}
    sessions = [s for s in tables["sessions"] if s["mode"] in ("assess_A", "assess_B") and s["learner_id"] in learners]
    attempts_by_session: dict[str, list[dict[str, Any]]] = {}
    for a in tables["attempts"]:
        attempts_by_session.setdefault(a["session_id"], []).append(a)
    sus_by: dict[str, dict[str, Any]] = {}
    for s in sorted(tables["sus"], key=lambda r: r.get("created_at") or ""):
        sus_by[s["learner_id"]] = s  # latest per learner

    participants = []
    for lid, lr in sorted(learners.items(), key=lambda kv: kv[1]["participant_code"]):
        ss = sorted([s for s in sessions if s["learner_id"] == lid], key=lambda s: s["started_at"])
        p: dict[str, Any] = {"code": lr["participant_code"], "level": lr.get("level"), "sessions": len(ss)}
        forms = {}
        for s in ss:
            recs = [r for r in (record_from_row(a, truth) for a in attempts_by_session.get(s["id"], [])) if r]
            forms.setdefault(s["mode"], (s, recs))
        order = [s["mode"] for s in ss]
        p["order"] = order
        parity = code_parity(lr["participant_code"])
        expected = None if parity is None else (["assess_A", "assess_B"] if parity == 1 else ["assess_B", "assess_A"])
        p["order_as_protocol"] = expected is not None and order[:2] == expected
        complete = len(forms) == 2 and all(len(v[1]) >= min_cases for v in forms.values())
        p["complete"] = complete
        if len(order) >= 1:
            pre_mode = order[0]
            post_mode = next((m for m in order[1:] if m != pre_mode), None)
            p["pre_form"], p["post_form"] = pre_mode, post_mode
            p["pre"] = session_metrics(forms[pre_mode][1]) if pre_mode in forms else None
            p["post"] = session_metrics(forms[post_mode][1]) if post_mode in forms else None
        s = sus_by.get(lid)
        if s:
            ans = json.loads(s["answers_json"])
            p["sus"] = float(s["score"]) if s.get("score") is not None else sus_from_answers(ans)
            p["sus_recomputed"] = sus_from_answers(ans) if len(ans) == 10 else None
        participants.append(p)

    paired = [p for p in participants if p["complete"] and p.get("pre") and p.get("post")]
    changes: dict[str, Any] = {}
    for k, _ in METRICS:
        pre = [p["pre"].get(k) for p in paired]
        post = [p["post"].get(k) for p in paired]
        diffs = [b - a for a, b in zip(pre, post) if a is not None and b is not None]
        changes[k] = {
            "pre_median": bootstrap_ci(pre, "median", n_boot, seed),
            "post_median": bootstrap_ci(post, "median", n_boot, seed),
            "change_median": bootstrap_ci(diffs, "median", n_boot, seed),
            "change_mean": bootstrap_ci(diffs, "mean", n_boot, seed),
            "n_improved": sum(d > 0 for d in diffs),
            "n_worse": sum(d < 0 for d in diffs),
            "n": len(diffs),
        }
    pooled = {w: Counter() for w in ("pre", "post")}
    for p in paired:
        for w in ("pre", "post"):
            pooled[w].update(p[w].get("miss_type_mix", {}))
    by_form: dict[str, dict[str, Any]] = {}
    for form in ("assess_A", "assess_B"):
        vals = {k: [] for k, _ in METRICS}
        for p in paired:
            for w in ("pre", "post"):
                if p[f"{w}_form"] == form:
                    for k in vals:
                        vals[k].append(p[w].get(k))
        by_form[form] = {k: bootstrap_ci(v, "mean", n_boot, seed) for k, v in vals.items()}
    sus_vals = [p["sus"] for p in participants if p.get("sus") is not None]
    reviews = review_summary(tables["reviews"], n_boot, seed)
    return {
        "participants": participants,
        "n_participants": len(participants),
        "n_paired": len(paired),
        "changes": changes,
        "pooled_mix": {k: dict(v) for k, v in pooled.items()},
        "by_form": by_form,
        "sus_mean": bootstrap_ci(sus_vals, "mean", n_boot, seed),
        "sus_median": bootstrap_ci(sus_vals, "median", n_boot, seed),
        "reviews": reviews,
    }


def review_summary(rows: list[dict[str, Any]], n_boot: int, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in ("debrief", "card"):
        rr = [r for r in rows if r.get("item_type") == t]
        out[t] = {
            "n_ratings": len(rr),
            "n_items": len({r["item_id"] for r in rr}),
            "n_reviewers": len({r.get("reviewer") for r in rr}),
            "roles": dict(Counter(r.get("role") or "unspecified" for r in rr)),
            "accuracy": bootstrap_ci([r.get("accuracy") for r in rr], "mean", n_boot, seed),
            "teaching": bootstrap_ci([r.get("teaching") for r in rr], "mean", n_boot, seed),
            "safety_flags": sum(bool(r.get("safety_flag")) for r in rr),
            "comments": [(r["item_id"], r["comment"]) for r in rr if r.get("comment")][:20],
        }
    return out


# ------------------------------------------------------------------------------------------------ report
def _p(v: float | None, pct: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{100 * v:.0f}%" if pct else f"{v:.2f}"


def figure(res: dict[str, Any], out: Path) -> str | None:
    paired = [p for p in res["participants"] if p["complete"] and p.get("pre") and p.get("post")]
    if not paired:
        return None
    chart_style()
    import matplotlib.pyplot as plt

    keys = [
        ("sensitivity", True),
        ("specificity", True),
        ("localization_fraction", True),
        ("false_positives_per_image", False),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(13, 4.2))
    for ax, (k, pct) in zip(axes, keys):
        for p in paired:
            a, b = p["pre"].get(k), p["post"].get(k)
            if a is None or b is None:
                continue
            ax.plot([0, 1], [a, b], color=PALETTE["s1"], alpha=0.55, lw=2, marker="o", ms=6)
        med = res["changes"][k]
        if med["pre_median"].n:
            ax.plot(
                [0, 1],
                [med["pre_median"].point, med["post_median"].point],
                color=PALETTE["ink"],
                lw=3,
                marker="s",
                ms=8,
                label="median",
            )
        ax.set_xticks([0, 1], ["pre", "post"])
        ax.set_xlim(-0.3, 1.3)
        if pct:
            ax.set_ylim(-0.05, 1.05)
        ax.set_title(dict(METRICS)[k], fontsize=11)
    axes[0].legend(loc="lower right", fontsize=9)
    fig.suptitle(f"Paired pre/post per participant — {label(len(paired))}", fontsize=11)
    fig.tight_layout()
    p = out / "pilot_paired.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def write_report(res: dict[str, Any], db: Path, out: Path, min_cases: int, n_boot: int, seed: int) -> Path:
    n = res["n_paired"]
    title = f"Pilot analysis — {label(n)}"
    md = [
        f"# {title}",
        "",
        f"> Usability testing, not a research study: n = {n} participants with both assessments complete "
        f"({res['n_participants']} with a participant code). Not powered; no p-values. Pre/post differences "
        "conflate practice, test familiarity and form difficulty (A vs B forms are different cases; "
        "counterbalancing by code parity only partly offsets this).",
        "",
    ]
    if n == 0:
        md += [
            "**No complete pilot data yet.** The tables below fill in once participants have finished both "
            f"assessments (≥ {min_cases} submitted cases each).",
            "",
        ]
    md += ["## Paired changes (post − pre; median [95% bootstrap CI], unit = participant)", ""]
    tab = []
    for k, name in METRICS:
        c = res["changes"][k]
        pct = k != "false_positives_per_image"
        sc = 100 if pct else 1
        unit = " pp" if pct else ""

        def f(ci: Any, sc: float = sc, unit: str = unit) -> str:
            if ci.n == 0:
                return "n/a"
            return f"{sc * ci.point:.1f}{unit} [{sc * ci.lo:.1f}, {sc * ci.hi:.1f}]"

        tab.append(
            [
                name,
                f(c["pre_median"]).replace(" pp", "%"),
                f(c["post_median"]).replace(" pp", "%"),
                f(c["change_median"]),
                f"{c['n_improved']} / {c['n_worse']} / {c['n']}",
            ]
        )
    md += [md_table(["metric", "pre (median)", "post (median)", "change (median)", "improved / worse / n"], tab), ""]
    md += [
        "## Miss-type mix (pooled counts over paired participants)",
        "",
        md_table(
            ["when"] + list(BUCKETS), [[w] + [res["pooled_mix"][w].get(b, 0) for b in BUCKETS] for w in ("pre", "post")]
        ),
        "",
    ]
    md += [
        "## Form check (mean over all complete sessions on that form, regardless of order)",
        "",
        md_table(
            ["form"] + [name for _, name in METRICS],
            [[f] + [fmt_num(res["by_form"][f][k], 2) for k, _ in METRICS] for f in res["by_form"]],
        ),
        "",
    ]
    md += ["## Per participant (anonymous codes)", ""]
    rows = []
    for p in res["participants"]:
        pre, post = p.get("pre") or {}, p.get("post") or {}
        rows.append(
            [
                p["code"],
                p.get("level") or "",
                " → ".join(x.replace("assess_", "") for x in p["order"]),
                "yes" if p["order_as_protocol"] else "NO",
                "yes" if p["complete"] else "no",
                f"{_p(pre.get('sensitivity'))} → {_p(post.get('sensitivity'))}",
                f"{_p(pre.get('specificity'))} → {_p(post.get('specificity'))}",
                f"{_p(pre.get('localization_fraction'))} → {_p(post.get('localization_fraction'))}",
                f"{_p(pre.get('false_positives_per_image'), False)} → "
                f"{_p(post.get('false_positives_per_image'), False)}",
                "" if p.get("sus") is None else f"{p['sus']:.1f}",
            ]
        )
    md += [
        md_table(
            [
                "code",
                "level",
                "order",
                "order per protocol",
                "complete",
                "sensitivity",
                "specificity",
                "localization",
                "FP / image",
                "SUS",
            ],
            rows,
        )
        if rows
        else "(none)",
        "",
    ]
    md += [
        "## SUS",
        "",
        f"- Mean {fmt_num(res['sus_mean'], 1)}; median {fmt_num(res['sus_median'], 1)} (0–100; 68 is the "
        "commonly cited average).",
        "",
    ]
    rv = res["reviews"]
    md += ["## Expert review ratings (/review)", ""]
    for t in ("debrief", "card"):
        r = rv[t]
        md += [
            f"- **{t}s:** {r['n_ratings']} ratings of {r['n_items']} items by {r['n_reviewers']} reviewer(s) "
            f"(roles {r['roles'] or '—'}); accuracy {fmt_num(r['accuracy'], 2)} / 5; teaching value "
            f"{fmt_num(r['teaching'], 2)} / 5; safety concerns flagged: {r['safety_flags']}."
        ]
    comments = rv["debrief"]["comments"] + rv["card"]["comments"]
    if comments:
        md += ["", "Reviewer corrections (verbatim, first 20):", ""] + [f"- `{i}`: {c}" for i, c in comments]
    md += [
        "",
        "## Method",
        "",
        "- Participants = learners with a participant code. Pre = their first assessment session, post = the "
        "other form. Protocol: odd codes take A first, even codes B first; deviations are listed above.",
        f"- Complete = both forms with ≥ {min_cases} submitted cases. Incomplete participants are listed but "
        "excluded from paired statistics.",
        "- Metrics are the app's own (backend.app.analytics.learner.case_level_stats): sensitivity = abnormal "
        "cases with any finding localized or pattern reported; specificity = normal cases with no false-positive "
        "mark or pattern; localization fraction = focal findings localized (found or mislabeled); false positives "
        "per image over all cases; search share = search errors / (search + recognition + decision).",
        f"- CIs: percentile bootstrap over participants ({n_boot} resamples, seed {seed}). With n this small the "
        "intervals are wide and unstable; read them as descriptive.",
        "",
    ]
    md += ["## Provenance", ""] + provenance_lines(db=str(db), participants=res["n_participants"], paired=n)
    p = out / "pilot_analysis.md"
    fig = figure(res, out)
    if fig:
        md += ["", "## Figure", "", f"![{fig}]({fig})"]
    p.write_text("\n".join(md) + "\n")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    ap.add_argument("--min-cases", type=int, default=10)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="accepted for a uniform CLI; this script never calls APIs")
    ap.add_argument("--max-cost", type=float, default=0.0, help="accepted for a uniform CLI; cost is always $0")
    args = ap.parse_args(argv)
    from backend.app.settings import get_settings

    db = args.db or get_settings().db_path
    args.out_dir.mkdir(parents=True, exist_ok=True)
    tables = load(db) if Path(db).exists() else {t: [] for t in ("learners", "sessions", "attempts", "sus", "reviews")}
    res = analyse(tables, case_truth() if Path(db).exists() else {}, args.min_cases, args.n_boot, args.seed)
    path = write_report(res, Path(db), args.out_dir, args.min_cases, args.n_boot, args.seed)
    write_json(
        args.out_dir / "pilot_analysis.json",
        {"title": f"Pilot analysis — {label(res['n_paired'])}", "label": label(res["n_paired"]), "db": str(db), **res},
    )
    print(f"[pilot] {label(res['n_paired'])}; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
