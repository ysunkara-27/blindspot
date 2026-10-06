"""SPEC §12.2 — debrief faithfulness and the grounding ablation.

Scenarios = bench cases × scripted learner behaviours {all correct; wrong-side mark; mislabeled; missed with
telemetry that never enters the ROI (search) / passes ~500 ms (recognition) / lingers ~2,000 ms (decision);
overcall on a normal}. Each scenario runs the PRODUCTION scoring + search engines to get outcomes and FACTS, then:

  G  = production tutor pipeline (backend.app.tutor.service.generate_debrief) with an injected caching client:
       FACTS + teaching cards + annotated images; validator; one regeneration; template fallback.
  U  = ablation: the same radiograph with the learner's marks (expert outlines and finding-centred crops are
       withheld because they encode location), the learner's marks, and ONLY the ground-truth label names — no
       locations, no outcomes, no search data. Same rules, cards, output schema and model; one call.

Metrics: schema validity; validator pass (first try; G also within one regeneration); judge-rated groundedness,
hallucinated findings, laterality, pedagogy (1–5), management advice (judge = BLINDSPOT_MODEL_JUDGE, structured
output, blind to condition); plus the eval's own deterministic checks (eval/checks.py). Also exports a stratified
20-debrief review queue for /review.

  uv run python -m eval.faithfulness --dry-run      # mock debrief client + mock judge, no API calls
  uv run python -m eval.faithfulness                # live: prints the estimate; needs --yes to spend
"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from eval import adapters, checks, render, scenarios
from eval.common import (
    CORE_FOCAL,
    EVAL_DIR,
    PALETTE,
    PRICES_SOURCE,
    SAMPLES_DIR,
    BudgetExceeded,
    CallPlan,
    CaseSource,
    ResponseCache,
    SpendTracker,
    add_common_args,
    bootstrap_ci,
    bootstrap_paired_diff,
    cases_for_split,
    chart_style,
    check_budget,
    estimate_cost,
    fmt_num,
    fmt_pct,
    live_preflight,
    load_cases,
    md_table,
    parse_price_overrides,
    provenance_lines,
    resolve_source,
    run_title,
    watermark,
    write_json,
)
from eval.llm import CachingAnthropic, StructuredCaller, make_client
from shared.contracts import AttemptSubmit, Case, DebriefFacts, DebriefOutput

EXCLUDE_FLAGS = {"orientation_suspect", "negative_flag_mismatch"}
JUDGE_PROMPT_PATH = EVAL_DIR / "judge_prompt.md"
ABLATION_PROMPT_PATH = EVAL_DIR / "ablation_prompt.md"
EXPECTED_OUT = {"G": 800, "U": 800, "judge": 1000}  # assumption incl. thinking; calibrated from cache when possible
MAX_OUT = {"judge": 4096}  # G and U use the production debrief max_tokens (adapters.production_debrief_params)
INFRA_ERRORS = ("transient", "APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError")
PRODUCTION_TUTOR = ("backend.app.tutor.service", "backend.app.tutor.facts", "backend.app.tutor.validator")

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "grounded",
        "violations",
        "laterality_correct",
        "hallucinated_findings",
        "pedagogy",
        "management_advice",
    ],
    "properties": {
        "grounded": {"type": "boolean"},
        "violations": {"type": "array", "items": {"type": "string"}},
        "laterality_correct": {"type": "boolean"},
        "hallucinated_findings": {"type": "array", "items": {"type": "string"}},
        "pedagogy": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "management_advice": {"type": "boolean"},
    },
}


def debrief_schema() -> dict[str, Any]:
    s = json.loads(checks.load_schema_path().read_text())
    return {k: v for k, v in s.items() if not k.startswith("$") and k not in ("title", "description")}


# ------------------------------------------------------------------------------------------------ selection
def focal(c: Case) -> list[Any]:
    return [f for f in c.findings if f.kind == "focal"]


def select_cases(
    cases: list[Case], src: CaseSource, n_abn: int, n_norm: int, seed: int, max_focal: int = 3
) -> list[Case]:
    """Abnormal bench cases with 1..max_focal focal findings whose first focal label is core (stratified by that
    label, round-robin), plus normal bench cases. Fixtures: every case (pattern-only allowed)."""
    bench = [c for c in cases_for_split(cases, "bench", src) if not set(c.qa_flags) & EXCLUDE_FLAGS]
    rng = random.Random(seed)
    by_label: dict[str, list[Case]] = defaultdict(list)
    normals = []
    for c in sorted(bench, key=lambda c: c.case_id):
        if c.is_normal:
            normals.append(c)
            continue
        f = focal(c)
        if src.synthetic and not f and c.findings:
            by_label["pattern_only"].append(c)
        elif 1 <= len(f) <= max_focal and f[0].label in CORE_FOCAL:
            by_label[f[0].label].append(c)
    for v in by_label.values():
        rng.shuffle(v)
    rng.shuffle(normals)
    abn: list[Case] = []
    while len(abn) < n_abn and any(by_label.values()):
        for lab in sorted(by_label):
            if by_label[lab] and len(abn) < n_abn:
                abn.append(by_label[lab].pop(0))
    return abn + normals[:n_norm]


# ------------------------------------------------------------------------------------------------ condition U
def u_case_info(facts: DebriefFacts, submit: AttemptSubmit, case: Case) -> dict[str, Any]:
    """Everything U may know: label names (no locations/outcomes/search) + the learner's own marks."""
    return {
        "image_size_px": [case.width, case.height],
        "findings": [{"id": f.id, "label": f.label, "display": f.display, "kind": f.kind} for f in facts.case.findings],
        "learner": {
            "level": facts.learner.level,
            "declared_normal": submit.declared_normal,
            "marks": [
                {"id": m.mark_id, "x": m.x, "y": m.y, "label": m.label, "confidence": m.confidence}
                for m in submit.marks
            ],
            "pattern_selections": [{"label": p.label, "confidence": p.confidence} for p in submit.patterns],
        },
    }


def u_request(
    facts: DebriefFacts, submit: AttemptSubmit, case: Case, root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """System = ablation prompt + the production cards block (identical text, so only case facts differ)."""
    system = [
        {"type": "text", "text": ABLATION_PROMPT_PATH.read_text()},
        {"type": "text", "text": adapters.cards_block_text(), "cache_control": {"type": "ephemeral"}},
    ]
    img = render.draw_marks(render.to_rgb(render.load_gray(root, case)), list(submit.marks))
    block, _ = render.image_block(img)
    info = json.dumps(u_case_info(facts, submit, case), ensure_ascii=False)
    return system, [block, {"type": "text", "text": "CASE INFO:\n" + info}]


# ------------------------------------------------------------------------------------------------ mocks (dry run)
def mock_g(_req: dict[str, Any], ctx: tuple[DebriefFacts, Case]) -> dict[str, Any]:
    facts, case = ctx
    return adapters.template_debrief(facts, case).model_dump()


def mock_u(_req: dict[str, Any], ctx: tuple[DebriefFacts, Case]) -> dict[str, Any]:
    """Naive deterministic stand-in using only what U is told: label match → found, else missed_search."""
    facts, _case = ctx
    mark_labels = {m.label for m in facts.learner.marks}
    pats = {p.label for p in facts.learner.pattern_selections}
    used = set()
    findings = []
    for f in facts.case.findings:
        if f.kind == "pattern":
            res = "pattern_found" if f.label in pats else "pattern_missed"
        elif f.label in mark_labels:
            res = "found"
            used.add(f.label)
        else:
            res = "missed_search"
        findings.append(
            {
                "finding_id": f.id,
                "result": res,
                "where_to_look": "Compare both lungs zone by zone.",
                "what_it_looks_like": [f"Look for the typical appearance of {f.display.lower()}."],
                "why": "Work through every zone before deciding.",
            }
        )
    over = [
        {"mark_id": m.id, "explanation": "No annotated finding matches this mark's label.", "possible_mimics": []}
        for m in facts.learner.marks
        if m.label not in {f.label for f in facts.case.findings}
    ]
    return {
        "headline": "Review the annotated findings.",
        "verdict": "partly_found",
        "findings": findings,
        "overcalls": over,
        "search_coaching": "Use a systematic search.",
        "calibration_note": "",
        "next_step": "Try another case.",
        "fact_ids": [f["finding_id"] for f in findings],
    }


def mock_judge(_req: dict[str, Any], ctx: tuple[DebriefFacts, dict[str, Any]]) -> dict[str, Any]:
    """Deterministic stand-in judge built from eval/checks.py (dry run only)."""
    facts, out = ctx
    r = checks.check_debrief(out, facts)
    grounded = r.results_ok and r.overcalls_ok and not r.laterality_errors and not r.out_of_scope_labels
    return {
        "grounded": grounded,
        "violations": r.errors[:5],
        "laterality_correct": not r.laterality_errors,
        "hallucinated_findings": r.out_of_scope_labels,
        "pedagogy": 4 if grounded else 2,
        "management_advice": r.management,
    }


# ------------------------------------------------------------------------------------------------ one scenario
def parse_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


def as_dict(d: Any) -> dict[str, Any] | None:
    if d is None:
        return None
    if isinstance(d, DebriefOutput):
        return d.model_dump()
    return dict(d)


def safe_validate(out: dict[str, Any] | None, facts: DebriefFacts, case: Case) -> dict[str, Any]:
    if out is None:
        return {"ok": False, "errors": ["no parseable output"]}
    try:
        DebriefOutput.model_validate(out)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errors": [f"schema: {str(e).splitlines()[0]}"]}
    v = adapters.validate(out, facts, case)
    return {"ok": v["ok"], "errors": v["errors"]}


class Runner:
    def __init__(
        self,
        args: argparse.Namespace,
        src: CaseSource,
        cases: dict[str, Case],
        *,
        dry_run: bool,
        cache_dir: Path,
        tracker: SpendTracker | None,
        debrief_model: str,
        judge_model: str,
    ):
        self.args, self.src, self.cases, self.dry_run = args, src, cases, dry_run
        self.repo = adapters.repo_for(src.root)
        self.cfg = adapters.cfg_scoring()
        self.cards = adapters.load_cards()
        mode = "mock" if dry_run else "live"
        self.gcache = ResponseCache(cache_dir, f"faith/G/{mode}")
        self.tracker = tracker
        self.debrief_model = debrief_model
        self.real_client = None if dry_run else make_client()  # one SDK client shared by every scenario
        self.prod = adapters.production_debrief_params()
        u_effort = self.prod["effort"] if args.effort == "default" else args.effort
        self.u = StructuredCaller(
            model=debrief_model,
            cache=ResponseCache(cache_dir, f"faith/U/{mode}"),
            dry_run=dry_run,
            mock_fn=mock_u,
            tracker=tracker,
            max_tokens=self.prod["max_tokens"],
            effort=u_effort,
        )
        self.judge = StructuredCaller(
            model=judge_model,
            cache=ResponseCache(cache_dir, f"faith/judge/{mode}"),
            dry_run=dry_run,
            mock_fn=mock_judge,
            tracker=tracker,
            max_tokens=MAX_OUT["judge"],
            effort=args.judge_effort,
        )
        self.judge_system = JUDGE_PROMPT_PATH.read_text()
        self.debrief_schema = debrief_schema()

    def judge_one(self, facts: DebriefFacts, out: dict[str, Any] | None) -> dict[str, Any] | None:
        if out is None or self.args.no_judge:
            return None
        text = (
            "FACTS:\n"
            + facts.model_dump_json(by_alias=True)
            + "\n\nDEBRIEF:\n"
            + json.dumps(out, ensure_ascii=False, sort_keys=True)
        )
        r = self.judge.call(
            system=self.judge_system,
            content=[{"type": "text", "text": text}],
            schema=JUDGE_SCHEMA,
            mock_ctx=(facts, out),
        )
        if not r.ok:
            return {"error": r.error}
        return {**(r.parsed or {}), "usage": r.usage, "mock": r.mock}

    def run(self, sc: scenarios.Scenario) -> dict[str, Any]:
        case = self.cases[sc.case_id]
        res = adapters.score_attempt(case, sc.submit, self.repo, self.cfg)
        actual = res.result_by_target()
        cmp = scenarios.compare(sc.intended, actual)
        facts = adapters.build_facts(case, sc.submit, res)
        row: dict[str, Any] = {
            "scenario_id": sc.scenario_id,
            "case_id": sc.case_id,
            "behaviour": sc.behaviour,
            "target": sc.target,
            "intended": sc.intended,
            "actual": actual,
            "engine_ok": all(v[2] for v in cmp.values()),
            "facts": json.loads(facts.model_dump_json(by_alias=True)),
            "image_path": case.image_path,
            "learner": {
                "marks": [m.model_dump() for m in sc.submit.marks],
                "patterns": [p.model_dump() for p in sc.submit.patterns],
                "declared_normal": sc.submit.declared_normal,
            },
        }
        conds: dict[str, Any] = {}
        # ---------------- G: production pipeline with the injected caching client
        client = CachingAnthropic(
            cache=self.gcache, dry_run=self.dry_run, mock_fn=mock_g, tracker=self.tracker, real_client=self.real_client
        )
        client.reset(ctx=(facts, case))
        g = adapters.generate_debrief(
            facts,
            case,
            sc.submit,
            client=client,
            attempt_id=sc.scenario_id,
            data_root=self.src.root,
            model=self.debrief_model,
        )
        calls = client.calls
        first = parse_json(calls[0].text) if calls else None
        second = parse_json(calls[1].text) if len(calls) > 1 else None
        shown = as_dict(g.get("debrief"))
        v1 = safe_validate(first, facts, case)
        v2 = safe_validate(second, facts, case) if len(calls) > 1 else None
        vdict = g.get("validator") or {}
        conds["G"] = {
            "output": first,
            "n_calls": len(calls),
            "source": g.get("source"),
            "stop_reasons": [c.stop_reason for c in calls],
            "fallback_reason": vdict.get("fallback_reason"),
            "excluded": (not calls) and not self.dry_run,
            "schema_ok": checks.check_debrief(first, facts).schema_ok if first is not None else False,
            "validator_first": v1,
            "validator_second": v2,
            "model_pass_within_regen": bool(v1["ok"] or (v2 and v2["ok"])),
            "usage": [c.usage for c in calls],
            "mock": any(c.mock for c in calls),
            "error": None if calls else "no model call made (service fell back before calling)",
        }
        conds["G_shown"] = {"output": shown, "source": g.get("source"), "validator": safe_validate(shown, facts, case)}
        # ---------------- U: ablation, one call
        system, content = u_request(facts, sc.submit, case, self.src.root)
        ur = self.u.call(system=system, content=content, schema=self.debrief_schema, mock_ctx=(facts, case))
        uout = ur.parsed if ur.ok else None
        conds["U"] = {
            "output": uout,
            "n_calls": 1,
            "source": "live" if not ur.mock else "mock",
            "schema_ok": checks.check_debrief(uout, facts).schema_ok if uout is not None else False,
            "validator_first": safe_validate(uout, facts, case),
            "usage": [ur.usage],
            "mock": ur.mock,
            "error": ur.error,
            "stop_reasons": [ur.stop_reason],
            "excluded": bool(ur.error) and any(k in ur.error for k in INFRA_ERRORS),
        }
        conds["G_shown"]["excluded"] = conds["G"]["excluded"]
        # ---------------- deterministic checks + judge
        for k in ("G", "U", "G_shown"):
            out = conds[k]["output"]
            conds[k]["det"] = checks.check_debrief(out, facts, cards=self.cards).as_dict() if out else None
        conds["G"]["judge"] = self.judge_one(facts, first)
        conds["U"]["judge"] = self.judge_one(facts, uout)
        conds["G_shown"]["judge"] = conds["G"]["judge"] if shown == first else self.judge_one(facts, shown)
        row["conds"] = conds
        return row


# ------------------------------------------------------------------------------------------------ metrics
def _judge(r: dict[str, Any], cond: str) -> dict[str, Any] | None:
    j = r["conds"][cond].get("judge")
    return None if (j is None or "error" in j) else j


def unit_values(rows: list[dict[str, Any]], cond: str) -> dict[str, list[float | None]]:
    """Per-scenario values (None = not applicable / judge failed). A missing output counts as a failure."""
    v: dict[str, list[float | None]] = defaultdict(list)
    for r in rows:
        c = r["conds"][cond]
        if c.get("excluded"):  # infrastructure failure (no model output to judge): excluded, counted separately
            continue
        out = c["output"]
        j = _judge(r, cond)
        d = c.get("det")
        if cond != "G_shown":
            v["schema_ok"].append(float(c["schema_ok"]))
            v["validator_first"].append(float(c["validator_first"]["ok"]))
        if cond in ("G", "U"):
            v["truncated_or_refused"].append(float(any(x in ("max_tokens", "refusal") for x in c["stop_reasons"])))
        if cond == "G":
            v["model_pass_within_regen"].append(float(c["model_pass_within_regen"]))
            v["template_fallback"].append(float(c["source"] == "template"))
        if cond == "G_shown":
            v["validator_shown"].append(float(c["validator"]["ok"]))
        missing = out is None
        v["grounded"].append(0.0 if missing else (float(bool(j["grounded"])) if j else None))
        v["laterality_error"].append(1.0 if missing else (float(not j["laterality_correct"]) if j else None))
        v["hallucinated_per_debrief"].append(
            None if missing else (float(len(j["hallucinated_findings"])) if j else None)
        )
        v["any_hallucination"].append(None if missing else (float(bool(j["hallucinated_findings"])) if j else None))
        v["pedagogy"].append(None if missing or not j else float(j["pedagogy"]))
        v["management_advice"].append(None if missing or not j else float(bool(j["management_advice"])))
        v["det_results_ok"].append(0.0 if not d else float(d["results_ok"]))
        v["det_laterality_error"].append(None if not d else float(bool(d["laterality_errors"])))
        v["det_out_of_scope"].append(None if not d else float(bool(d["out_of_scope_labels"])))
        v["det_management"].append(None if not d else float(bool(d["management"])))
        v["det_length_ok"].append(None if not d else float(d["length_ok"]))
    return v


METRIC_ROWS: list[tuple[str, str, str]] = [  # key, label, kind (pct|num)
    ("schema_ok", "Schema-valid output (first try)", "pct"),
    ("validator_first", "Production validator pass, first try", "pct"),
    ("model_pass_within_regen", "Model-written debrief passes within one regeneration", "pct"),
    ("template_fallback", "Template fallback shown to learner", "pct"),
    ("truncated_or_refused", "A model call hit max_tokens or refused", "pct"),
    ("validator_shown", "Shown debrief passes the validator", "pct"),
    ("grounded", "Judge: fully grounded in FACTS", "pct"),
    ("laterality_error", "Judge: laterality error", "pct"),
    ("any_hallucination", "Judge: ≥1 hallucinated finding", "pct"),
    ("hallucinated_per_debrief", "Judge: hallucinated findings per debrief", "num"),
    ("pedagogy", "Judge: pedagogy (1–5)", "num"),
    ("management_advice", "Judge: management advice", "pct"),
    ("det_results_ok", "Deterministic: every result matches FACTS", "pct"),
    ("det_laterality_error", "Deterministic: laterality error in where_to_look", "pct"),
    ("det_out_of_scope", "Deterministic: out-of-scope label mentioned", "pct"),
    ("det_management", "Deterministic: banned management term", "pct"),
    ("det_length_ok", "Deterministic: within length limits", "pct"),
]


def summarize(rows: list[dict[str, Any]], n_boot: int, seed: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    vals = {c: unit_values(rows, c) for c in ("G", "U", "G_shown")}
    for c, v in vals.items():
        out[c] = {k: bootstrap_ci(x, n_boot=n_boot, seed=seed) for k, x in v.items()}
    out["paired_G_minus_U"] = {
        k: bootstrap_paired_diff(vals["G"][k], vals["U"][k], n_boot=n_boot, seed=seed)
        for k in ("grounded", "laterality_error", "hallucinated_per_debrief", "pedagogy", "det_results_ok")
    }
    by_b: dict[str, dict[str, str]] = {}
    for b in scenarios.BEHAVIOURS:
        sub = [r for r in rows if r["behaviour"] == b]
        if not sub:
            continue
        d = {}
        for c in ("G", "U"):
            g = [x for x in unit_values(sub, c)["grounded"] if x is not None]
            d[c] = f"{int(sum(g))}/{len(g)}"
        by_b[b] = d
    out["by_behaviour_grounded"] = by_b
    out["judge_failures"] = {
        c: sum(1 for r in rows if (r["conds"][c].get("judge") or {}).get("error")) for c in ("G", "U", "G_shown")
    }
    out["excluded_infra"] = {c: sum(1 for r in rows if r["conds"][c].get("excluded")) for c in ("G", "U")}
    out["fallback_reasons"] = dict(
        Counter(r["conds"]["G"].get("fallback_reason") for r in rows if r["conds"]["G"].get("fallback_reason"))
    )
    return out


def fmt(ci: Any, kind: str) -> str:
    return fmt_pct(ci) if kind == "pct" else fmt_num(ci, 2)


def headline_chart(s: dict[str, Any], out: Path, mark: str | None, names: dict[str, str]) -> str:
    chart_style()
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    for ax, key, title in (
        (axes[0], "grounded", "Fully grounded in FACTS (judge)"),
        (axes[1], "laterality_error", "Laterality error (judge)"),
    ):
        for i, (c, color) in enumerate((("U", PALETTE["s2"]), ("G", PALETTE["s1"]))):
            ci = s[c][key]
            if ci.n == 0 or np.isnan(ci.point):
                ax.text(i, 2, "n/a", ha="center")
                continue
            ax.bar(
                i,
                100 * ci.point,
                0.6,
                color=color,
                yerr=[[100 * (ci.point - ci.lo)], [100 * (ci.hi - ci.point)]],
                capsize=4,
                error_kw={"elinewidth": 1, "ecolor": PALETTE["ink2"]},
            )
            ax.text(i, 100 * ci.hi + 2, f"{100 * ci.point:.0f}%", ha="center", color=PALETTE["ink"], fontsize=12)
        ax.set_xticks([0, 1], [f"U: labels only\nn={s['U'][key].n}", f"G: grounded in FACTS\nn={s['G'][key].n}"])
        ax.set_ylim(0, 110)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_title(title, fontsize=12)
    axes[0].set_ylabel("% of debriefs (95% bootstrap CI)")
    if "MOCK" in names["G"]:
        fig.suptitle("Grounding ablation — MOCK outputs (dry run)", fontsize=12, color="#d03b3b")
    watermark(fig, mark)
    fig.tight_layout()
    p = out / "faithfulness.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def review_queue(rows: list[dict[str, Any]], k: int, seed: int, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Stratified by behaviour (≈ result type), round-robin, condition G as shown to the learner."""
    rng = random.Random(seed)
    by_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["conds"]["G_shown"]["output"] is not None:
            by_b[r["behaviour"]].append(r)
    for v in by_b.values():
        rng.shuffle(v)
    picked: list[dict[str, Any]] = []
    while len(picked) < k and any(by_b.values()):
        for b in scenarios.BEHAVIOURS:
            if by_b.get(b) and len(picked) < k:
                picked.append(by_b[b].pop(0))
    items = []
    for r in picked:
        g = r["conds"]["G_shown"]
        items.append(
            {
                "item_id": "faith:" + r["scenario_id"],
                "item_type": "debrief",
                "case_id": r["case_id"],
                "image_path": r["image_path"],
                "behaviour": r["behaviour"],
                "learner": r["learner"],
                "facts": r["facts"],
                "debrief": g["output"],
                "source": g["source"],
                "validator": g["validator"],
                **meta,
            }
        )
    return items


# ------------------------------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--abnormal-cases", type=int, default=16)
    ap.add_argument("--normal-cases", type=int, default=8)
    ap.add_argument("--model", default=None, help="debrief model for G and U (default BLINDSPOT_MODEL_DEBRIEF)")
    ap.add_argument("--judge-model", default=None, help="default BLINDSPOT_MODEL_JUDGE")
    ap.add_argument("--judge-effort", choices=["default", "low", "medium", "high"], default="default")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--review-n", type=int, default=20)
    ap.add_argument("--assume-regen", type=float, default=0.3, help="regeneration rate assumed in the estimate")
    ap.add_argument(
        "--allow-reference-tutor",
        action="store_true",
        help="live only: permit eval.reference_tutor when backend.app.tutor is missing (not recommended)",
    )
    ap.add_argument("--samples-dir", type=Path, default=SAMPLES_DIR)
    args = ap.parse_args(argv)

    from backend.app.settings import get_settings

    st = get_settings()
    debrief_model = args.model or st.blindspot_model_debrief
    judge_model = args.judge_model or st.blindspot_model_judge
    prices = parse_price_overrides(args.price)
    src = resolve_source(args.source)
    all_cases = load_cases(src)
    sel = select_cases(all_cases, src, args.abnormal_cases, args.normal_cases, args.seed)
    cases = {c.case_id: c for c in sel}
    repo = adapters.repo_for(src.root)
    cfg = adapters.cfg_scoring()
    scs, skips = scenarios.generate(sel, repo, cfg)
    if args.limit:
        scs = scs[: args.limit]
    print(
        f"[faith] source={src.name} ({src.description}); {len(sel)} cases → {len(scs)} scenarios "
        f"({dict(Counter(s.behaviour for s in scs))}); {len(skips)} skipped"
    )
    if not scs:
        raise SystemExit("no scenarios")

    missing = [m for m in PRODUCTION_TUTOR if adapters._try_import(m) is None]
    if missing and not args.dry_run and not args.allow_reference_tutor:
        raise SystemExit(f"REFUSING live run: condition G must be the production pipeline; missing {missing}.")

    # ---- cost estimate: probe one scenario with mocks (no API) to measure request sizes
    with tempfile.TemporaryDirectory() as td:
        probe = Runner(
            args,
            src,
            cases,
            dry_run=True,
            cache_dir=Path(td),
            tracker=None,
            debrief_model=debrief_model,
            judge_model=judge_model,
        )
        pr = probe.run(scs[0])
        g_in = max([u.get("input_tokens", 0) for u in pr["conds"]["G"]["usage"]] or [6000])
        u_in = pr["conds"]["U"]["usage"][0].get("input_tokens", 5000)
        j_in = (pr["conds"]["G"]["judge"] or {}).get("usage", {}).get("input_tokens", 2500)
    n = len(scs)
    observed = {
        k: ResponseCache(args.cache_dir, f"faith/{ns}/live").observed_output_tokens(m)
        for k, ns, m in (("U", "U", debrief_model), ("judge", "judge", judge_model))
    }
    prod = adapters.production_debrief_params()
    print(f"[faith] production debrief params (mirrored by U): {prod}")
    plans = [
        CallPlan(
            "G debrief (+regen)",
            debrief_model,
            int(round(n * (1 + args.assume_regen))),
            g_in,
            int(observed["U"] or EXPECTED_OUT["G"]),
            prod["max_tokens"],
        ),
        CallPlan(
            "U ablation debrief", debrief_model, n, u_in, int(observed["U"] or EXPECTED_OUT["U"]), prod["max_tokens"]
        ),
        CallPlan(
            "judge",
            judge_model,
            0 if args.no_judge else int(round(n * (2 + args.assume_regen))),
            j_in,
            int(observed["judge"] or EXPECTED_OUT["judge"]),
            MAX_OUT["judge"],
        ),
    ]
    est = estimate_cost(plans, prices)
    print(
        "[faith] (estimate counts every scenario as uncached; cached responses are free on resume; teaching-card "
        "prompt caching would lower the G/U input cost further)"
    )
    check_budget(est, args.max_cost, dry_run=args.dry_run)
    live = live_preflight(args)
    if not args.dry_run and not live:
        return 0

    tracker = SpendTracker(args.max_cost, prices)
    runner = Runner(
        args,
        src,
        cases,
        dry_run=args.dry_run,
        cache_dir=args.cache_dir,
        tracker=tracker,
        debrief_model=debrief_model,
        judge_model=judge_model,
    )
    rows: list[dict[str, Any]] = []
    stopped = None

    def safe_run(sc: scenarios.Scenario) -> dict[str, Any] | None:
        if tracker.spent >= args.max_cost:
            return None
        try:
            return runner.run(sc)
        except BudgetExceeded as e:
            return {"_stopped": str(e)}

    if args.dry_run:
        results = [safe_run(s) for s in scs]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            results = list(ex.map(safe_run, scs))
    for r in results:
        if r is None or "_stopped" in r:
            stopped = stopped or (r or {}).get("_stopped") or "budget reached"
            continue
        rows.append(r)
    if tracker.spent >= args.max_cost:
        stopped = stopped or f"actual spend ${tracker.spent:.2f} reached --max-cost"

    s = summarize(rows, args.n_boot, args.seed)
    names = {
        "G": "G: grounded (FACTS)" + (" — MOCK" if args.dry_run else ""),
        "U": "U: labels only" + (" — MOCK" if args.dry_run else ""),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    mark = "DRY RUN — MOCK OUTPUTS" if args.dry_run else ("SYNTHETIC FIXTURES" if src.synthetic else None)
    fig = headline_chart(s, args.out_dir, mark, names)

    # ---- samples + review queue (no images; case ids + paths only)
    tag = ".dryrun" if args.dry_run else ""
    args.samples_dir.mkdir(parents=True, exist_ok=True)
    with (args.samples_dir / f"faithfulness_debriefs{tag}.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    meta = {
        "dry_run": args.dry_run,
        "synthetic": src.synthetic,
        "model": debrief_model,
        "generated_by": "eval/faithfulness.py",
        "condition": "G",
    }
    queue = review_queue(rows, args.review_n, args.seed, meta)
    qpath = args.samples_dir / f"review_queue{tag}.jsonl"
    with qpath.open("w") as fh:
        for it in queue:
            fh.write(json.dumps(it, ensure_ascii=False, default=str) + "\n")

    engine_ok = sum(r["engine_ok"] for r in rows)
    title = run_title("Debrief faithfulness and grounding ablation", dry_run=args.dry_run, src=src)
    G, U = s["G"], s["U"]
    md = [f"# {title}", ""]
    if args.dry_run:
        md += [
            "> **DRY RUN.** G debriefs come from a mock client that returns the template debrief, U debriefs from "
            "a naive deterministic mock, and the judge is a deterministic stand-in built from eval/checks.py. "
            "These numbers test the harness only and must not be quoted.",
            "",
        ]
    if stopped:
        md += [f"> **Run stopped early:** {stopped}. Results cover {len(rows)} of {len(scs)} scenarios.", ""]
    pd = s["paired_G_minus_U"]
    md += [
        "## Headline",
        "",
        f"- Fully grounded (judge): G {fmt_pct(G['grounded'])} vs U {fmt_pct(U['grounded'])}; paired difference "
        f"G − U {fmt_num(pd['grounded'], 2)}.",
        f"- Laterality error (judge): G {fmt_pct(G['laterality_error'])} vs U {fmt_pct(U['laterality_error'])}.",
        f"- Hallucinated findings per debrief (judge): G {fmt_num(G['hallucinated_per_debrief'])} vs U "
        f"{fmt_num(U['hallucinated_per_debrief'])}.",
        f"- Production validator, first try: G {fmt_pct(G['validator_first'])}; within one regeneration "
        f"{fmt_pct(G['model_pass_within_regen'])}; template fallback shown {fmt_pct(G['template_fallback'])}.",
        f"- Scripted behaviours classified as intended by the production engines: {engine_ok}/{len(rows)}.",
        "",
    ]
    md += ["## All metrics (unit = scenario; % or mean [95% CI])", ""]
    tab = []
    for k, label, kind in METRIC_ROWS:
        tab.append([label] + [fmt(s[c][k], kind) if k in s[c] else "—" for c in ("U", "G", "G_shown")])
    md += [
        md_table(
            ["metric", "U (labels only, 1 call)", "G (first try)", "G as shown (after validator/regen/fallback)"], tab
        ),
        "",
    ]
    md += [
        "Paired differences G − U (same scenarios): " + "; ".join(f"{k} {fmt_num(v, 2)}" for k, v in pd.items()) + ".",
        "",
        f"Judge failures (excluded from judge metrics): {s['judge_failures']}. Infrastructure failures (timeouts / "
        f"API errors; excluded from every metric): {s['excluded_infra']}. G template-fallback reasons: "
        f"{s['fallback_reasons'] or 'none'}.",
        "",
    ]
    md += [
        "## Groundedness by behaviour (judge; grounded/judged)",
        "",
        md_table(["behaviour", "U", "G"], [[b, d["U"], d["G"]] for b, d in s["by_behaviour_grounded"].items()]),
        "",
    ]
    md += [
        "## Scenarios",
        "",
        md_table(
            ["behaviour", "scenarios", "engine classified as intended"],
            [
                [b, sum(r["behaviour"] == b for r in rows), sum(r["engine_ok"] for r in rows if r["behaviour"] == b)]
                for b in scenarios.BEHAVIOURS
            ],
        ),
        "",
        f"Skipped: {dict(Counter(k.reason for k in skips)) or 'none'}.",
        "",
    ]
    md += [
        "## Method",
        "",
        "- Cases: bench split; abnormal cases with 1–3 focal findings whose first focal label is core (stratified "
        f"by that label), plus normal cases; {args.abnormal_cases} abnormal + {args.normal_cases} normal requested."
        " The target of each behaviour is the case's first focal finding; every other focal finding is visited and "
        "marked correctly, and global findings are selected, so each scenario isolates one behaviour.",
        "- Telemetry is scripted (synthetic input by design): 33 ms samples, zoom 1×; search = never within "
        "1.3ρ of the target; recognition = a sweep with ≈500 ms inside the ROI; decision = ≈2,000 ms lingering.",
        "- G: production tutor service with an injected caching client (the tutor's own debrief cache is bypassed). "
        "The first model call is the 'first try'; 'as shown' is what the learner would see.",
        "- U: same model and output schema, ablation prompt (eval/ablation_prompt.md) with the same rules and "
        "teaching cards; the image shows only the learner's marks (expert outlines and finding-centred crops "
        "encode location, so they are withheld); CASE INFO gives label names, the learner's marks and "
        "selections — no locations, outcomes or search data. One call (a validator-guided regeneration would leak "
        "the ground truth). U therefore cannot know miss subtypes; 'every result matches FACTS' is reported for "
        "completeness, the headline is groundedness and laterality.",
        f"- Judge: {judge_model} with eval/judge_prompt.md and a structured-output schema; it sees FACTS and the "
        "debrief JSON only (no image), and is not told the condition.",
        "- Deterministic checks: eval/checks.py, an independent re-implementation of SPEC §8.6 rules (not the "
        "production validator).",
        f"- CIs: percentile bootstrap over scenarios ({args.n_boot} resamples, seed {args.seed}); paired "
        "differences bootstrap the per-scenario difference. Scenarios from the same case are not independent, "
        "so the CIs are somewhat optimistic.",
        f"- Review queue: {len(queue)} G debriefs stratified by behaviour → {qpath}.",
        "",
    ]
    md += ["## Figure", "", f"![{fig}]({fig})", ""]
    md += (
        ["## Provenance", ""]
        + provenance_lines(
            debrief_model=debrief_model,
            judge_model=judge_model,
            debrief_params=f"{runner.prod} (G via production client; U mirrors)",
            judge_effort=args.judge_effort,
            source=f"{src.name} — {src.description}",
            n_scenarios=len(rows),
            prices=PRICES_SOURCE,
            spend=(
                f"${tracker.spent:.2f} actual over {tracker.calls} live calls"
                if not args.dry_run
                else "$0.00 (dry run)"
            ),
        )
        + adapters.engine_status_lines()
    )
    (args.out_dir / "faithfulness.md").write_text("\n".join(md) + "\n")
    write_json(
        args.out_dir / "faithfulness.json",
        {
            "title": title,
            "dry_run": args.dry_run,
            "synthetic": src.synthetic,
            "n": len(rows),
            "debrief_model": debrief_model,
            "judge_model": judge_model,
            "summary": s,
            "engine_ok": engine_ok,
            "estimate": est.__dict__,
            "spend_usd": tracker.spent,
            "stopped": stopped,
            "engine_status": dict(adapters.ENGINE_STATUS),
            "review_queue": str(qpath),
        },
    )
    print(f"[faith] wrote {args.out_dir / 'faithfulness.md'}, {fig}, {qpath} ({len(queue)} items)")
    print(
        f"[faith] grounded: G {fmt_pct(G['grounded'])} vs U {fmt_pct(U['grounded'])}; laterality error: "
        f"G {fmt_pct(G['laterality_error'])} vs U {fmt_pct(U['laterality_error'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
