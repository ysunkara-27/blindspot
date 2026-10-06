"""Build the radiologist review queue: REAL debriefs from the production tutor on BENCH cases.

    uv run python -m backend.app.tutor.review_queue --max-cost 1.50            # dry run (templates, no network)
    uv run python -m backend.app.tutor.review_queue --max-cost 1.50 --live     # after the human checkpoint only

What it does
- Picks bench-split cases with no QA flag (bench cases are evaluation-only and never served to learners).
- Scripts 2 learner reads per behaviour (all correct, missed-search, missed-recognition, missed-decision, mislabeled,
  overcall on a normal) with eval.scenarios (synthetic telemetry: a test input, not learner data), scores each read
  with the PRODUCTION engine (backend.app.engine.evaluate) and keeps it only if the engine classifies it as intended.
- Builds FACTS with the production facts builder and generates the debrief with the production tutor service
  (backend.app.tutor.service.generate_debrief: validator, one regeneration, template fallback).
- Writes eval/samples/review_queue.jsonl in the shape backend/app/routes/review.py reads (one item per line).

Resumable: an item already in the live queue is reused (no API call) when it came from the same prompt version, was
generated live, and still passes the CURRENT validator against freshly built FACTS; pass --fresh to regenerate all.

Cost control: a worst-case estimate is printed first and the run refuses to start if it exceeds --max-cost; the actual
spend is tracked from every response's usage block and the run stops before a debrief whose worst case would cross
the cap. The API key is read by the SDK wrapper from settings and is never printed. Dry runs never touch the live
queue file (they write logs/review_queue.dryrun.jsonl).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.settings import REPO_ROOT, get_settings
from backend.app.tutor.client import AnthropicTutorClient, LLMResponse, MockClient, RateLimiter, debrief_max_tokens
from backend.app.tutor.facts import build_facts
from backend.app.tutor.service import generate_debrief, prompt_version
from backend.app.tutor.templates import template_debrief
from backend.app.tutor.validator import validate
from shared.contracts import Case, DebriefFacts

BEHAVIOURS = (
    "all_correct",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "mislabeled",
    "overcall_normal",
)
LIVE_OUT = REPO_ROOT / "eval" / "samples" / "review_queue.jsonl"
DRY_OUT = REPO_ROOT / "logs" / "review_queue.dryrun.jsonl"
# Worst-case input per call (measured 2026-10-05: ~7.4k cached prompt+cards prefix, ~3k images+FACTS; v3 prompt and
# the regeneration turn add ~1.5k). Used only for the pre-run estimate and the per-item stop check.
EST_INPUT_TOKENS = 13_000
CACHE_WRITE_MULT, CACHE_READ_MULT = 1.25, 0.1


class MeteredClient:
    """Wraps a tutor client and records every response's usage (for the actual cost)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", None)
        self.usage: list[LLMResponse] = []

    def complete(self, **kw: Any) -> LLMResponse:
        r = self.inner.complete(**kw)
        self.usage.append(r)
        return r


def call_cost(r: LLMResponse, price_in: float, price_out: float) -> float:
    return (
        (r.input_tokens or 0) * price_in
        + (r.cache_read_input_tokens or 0) * CACHE_READ_MULT * price_in
        + (r.cache_creation_input_tokens or 0) * CACHE_WRITE_MULT * price_in
        + (r.output_tokens or 0) * price_out
    ) / 1e6


def worst_case_item_cost(n_findings: int, price_in: float, price_out: float) -> float:
    """Two calls (first try + one regeneration), every input token billed as a cache write, output at max_tokens."""
    per_call = EST_INPUT_TOKENS * CACHE_WRITE_MULT * price_in + debrief_max_tokens(n_findings) * price_out
    return 2 * per_call / 1e6


def prices_for(model: str, override: str | None) -> tuple[float, float]:
    """(input, output) USD per million tokens: --price IN,OUT, else the eval harness list-price table. Refuses to
    guess for an unknown model."""
    if override:
        a, _, b = override.partition(",")
        return float(a), float(b)
    from eval.common import DEFAULT_PRICES

    if model not in DEFAULT_PRICES:
        raise SystemExit(f"no list price known for model {model!r}; pass --price IN,OUT (USD per million tokens)")
    return DEFAULT_PRICES[model]


def pick(repo: Any, per_behaviour: int, seed: int, max_findings: int) -> list[dict[str, Any]]:
    """[{case, behaviour, scenario, ev}] — bench only, no QA flags, distinct cases, engine-verified behaviours, and
    different target labels within a behaviour (least-used labels first across the queue)."""
    from backend.app import config
    from backend.app.engine import evaluate
    from eval import scenarios

    cfg = config.scoring()
    pool = [c for c in sorted(repo.by_split("bench"), key=lambda c: c.case_id) if not c.qa_flags]
    random.Random(seed).shuffle(pool)
    order = {c.case_id: i for i, c in enumerate(pool)}
    normals = [c for c in pool if c.is_normal]
    abnormal = [c for c in pool if any(f.kind == "focal" for f in c.findings) and len(c.findings) <= max_findings]
    used: set[str] = set()
    label_use: Counter[str] = Counter()
    out: list[dict[str, Any]] = []

    def target_label(c: Case) -> str:
        return next(f.label for f in c.findings if f.kind == "focal")

    for b in BEHAVIOURS:
        got: list[str] = []
        cands = normals if b == "overcall_normal" else abnormal
        while len(got) < per_behaviour:
            rest = [c for c in cands if c.case_id not in used]
            if b != "overcall_normal":
                rest = [c for c in rest if target_label(c) not in got]
                rest.sort(key=lambda c: (label_use[target_label(c)], order[c.case_id]))
            chosen = None
            for c in rest:
                sc = scenarios.build_scenario(c, repo, cfg, b)
                if not isinstance(sc, scenarios.Scenario):
                    continue
                ev = evaluate(c, sc.submit, repo)
                actual = {o.target: o.result for o in ev.outcomes}
                if all(ok for _, _, ok in scenarios.compare(sc.intended, actual).values()):
                    chosen = {"case": c, "behaviour": b, "scenario": sc, "ev": ev}
                    break
            if chosen is None:
                break
            c = chosen["case"]
            used.add(c.case_id)
            lab = "normal" if b == "overcall_normal" else target_label(c)
            got.append(lab if b != "overcall_normal" else f"normal{len(got)}")
            label_use[lab] += 1
            out.append(chosen)
    return out


def reusable(prev: dict[str, Any] | None, facts: DebriefFacts) -> bool:
    """A previous LIVE item for the same scenario, prompt version and FACTS that still passes today's validator."""
    if not prev or prev.get("source") != "live" or prev.get("dry_run") or prev.get("debrief") is None:
        return False
    if prev.get("prompt_version") != prompt_version():
        return False
    if prev.get("facts") != json.loads(facts.model_dump_json(by_alias=True)):
        return False
    return validate(prev["debrief"], facts).ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-behaviour", type=int, default=2)
    ap.add_argument("--max-cost", type=float, required=True, help="USD hard cap (estimate and actual spend)")
    ap.add_argument("--live", action="store_true", help="call the API (only after the human checkpoint)")
    ap.add_argument("--price", default=None, metavar="IN,OUT", help="USD per million tokens; default: list price")
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--max-findings", type=int, default=3, help="skip films with more findings than this")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--fresh", action="store_true", help="regenerate every item (default: reuse still-valid ones)")
    a = ap.parse_args(argv)
    out_path = a.out or (LIVE_OUT if a.live else DRY_OUT)
    if not a.live and out_path.resolve() == LIVE_OUT.resolve():
        print("refusing: a dry run must not overwrite the live review queue", file=sys.stderr)
        return 2

    settings = get_settings()
    model = settings.blindspot_model_debrief
    price_in, price_out = prices_for(model, a.price)
    from backend.app.cases import get_repo

    repo = get_repo()
    picked = pick(repo, a.per_behaviour, a.seed, a.max_findings)
    want = a.per_behaviour * len(BEHAVIOURS)
    if len(picked) < want:
        have = Counter(p["behaviour"] for p in picked)
        print(f"only {len(picked)}/{want} scenarios could be built from the bench split: {dict(have)}", file=sys.stderr)
        return 1
    est = sum(worst_case_item_cost(len(p["case"].findings), price_in, price_out) for p in picked)
    print(
        f"model {model} at ${price_in:g}/${price_out:g} per MTok (in/out); prompt {prompt_version()}; "
        f"{len(picked)} debriefs; worst-case estimate ${est:.2f}; max-cost ${a.max_cost:.2f}"
    )
    if est > a.max_cost:
        print("refusing: the worst-case estimate exceeds --max-cost", file=sys.stderr)
        return 2
    if a.live and not settings.anthropic_api_key:
        print("refusing: --live without an API key in the environment", file=sys.stderr)
        return 2

    previous: dict[str, dict[str, Any]] = {}
    if a.live and not a.fresh and out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                previous[row.get("item_id", "")] = row
    items: list[dict[str, Any]] = []
    spent = 0.0
    tok = Counter()
    for i, p in enumerate(picked, start=1):
        case, sc, ev, behaviour = p["case"], p["scenario"], p["ev"], p["behaviour"]
        worst = worst_case_item_cost(len(case.findings), price_in, price_out)
        facts = build_facts(
            case=case,
            submit=sc.submit,
            outcomes=ev.outcomes,
            spatial_relations=ev.spatial_relations,
            search=ev.facts_search,
            mark_zones=ev.mark_zones,
            level="other",  # what the UI sends since round 3 (no level picker)
            history={},
        )
        prev = previous.get(f"review:{sc.scenario_id}")
        if reusable(prev, facts):
            items.append(prev)
            print(f"{i:2d} {case.case_id:10s} {behaviour:18s} kept (live, {prev['prompt_version']}, still valid) $0")
            continue
        if a.live and spent + worst > a.max_cost:
            print(f"stopping before item {i}: ${spent:.2f} spent, next worst case ${worst:.2f} would cross the cap")
            break
        if a.live:
            inner: Any = AnthropicTutorClient(model=model, limiter=RateLimiter(10_000))
        else:
            inner = MockClient([template_debrief(facts).model_dump()], model="dry-run")
        client = MeteredClient(inner)
        r = generate_debrief(
            facts,
            case,
            attempt_id=f"review-{sc.scenario_id}",
            submit=sc.submit,
            offline=False,
            cache_get=None,
            client=client,
            data_root=repo.root,
        )
        cost = sum(call_cost(u, price_in, price_out) for u in client.usage) if a.live else 0.0
        spent += cost
        for u in client.usage:
            tok["input"] += u.input_tokens or 0
            tok["cache_read"] += u.cache_read_input_tokens or 0
            tok["cache_write"] += u.cache_creation_input_tokens or 0
            tok["output"] += u.output_tokens or 0
        v = r["validator"] or {}
        d = r["debrief"]
        items.append(
            {
                "item_id": f"review:{sc.scenario_id}",
                "item_type": "debrief",
                "case_id": case.case_id,
                "image_path": case.image_path,
                "behaviour": behaviour,
                "target": sc.target,
                "learner": {
                    "marks": [m.model_dump() for m in sc.submit.marks],
                    "patterns": [x.model_dump() for x in sc.submit.patterns],
                    "declared_normal": sc.submit.declared_normal,
                },
                "facts": json.loads(facts.model_dump_json(by_alias=True)),
                "debrief": d.model_dump() if d is not None else None,
                "source": r["source"],
                "provenance": r["provenance"],
                "validator": v,
                "validator_ok": bool(v.get("ok")),
                "model": r["model"],
                "prompt_version": r["prompt_version"],
                "latency_ms": r["latency_ms"],
                "score": ev.score,
                "dry_run": not a.live,
                "synthetic_learner": True,  # scripted read (eval.scenarios); the film and its annotations are real
                "split": case.split,
                "generated_by": "backend/app/tutor/review_queue.py",
            }
        )
        att = v.get("attempts") or []
        for k, x in enumerate(att):  # diagnostics for a failed try: the validator errors and the rejected headline
            if not x.get("ok") and k < len(client.usage):
                try:
                    head = json.loads(client.usage[k].text).get("headline")
                except (ValueError, AttributeError):
                    head = None
                print(f"   try {k + 1} rejected: {x.get('errors')} | headline: {head!r}")
        print(
            f"{i:2d} {case.case_id:10s} {behaviour:18s} target={sc.target or '-':3s} "
            f"labels={','.join(f.label for f in case.findings) or 'normal':40s} {r['source']:8s} "
            f"{r['latency_ms']:7.0f} ms calls={len(att)} first_try_ok={v.get('first_try_ok')} "
            f"words={[x.get('words') for x in att]} ok={v.get('ok')} cost=${cost:.4f}"
        )
    bad = [it for it in items if it["debrief"] is None or not it["validator_ok"]]
    not_live = [it for it in items if a.live and it["source"] != "live"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    complete = len(items) == want and not bad and not not_live
    if a.live and not complete:
        out_path = out_path.with_suffix(".partial.jsonl")  # never leave a short or mixed queue in the live path
    with out_path.open("w") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "mode": "live" if a.live else "dry-run",
                "items": len(items),
                "by_behaviour": dict(Counter(it["behaviour"] for it in items)),
                "sources": dict(Counter(it["source"] for it in items)),
                "first_try_ok": sum(bool(it["validator"].get("first_try_ok")) for it in items),
                "regenerated": sum(bool(it["validator"].get("regenerated")) for it in items),
                "validator_failures": len(bad),
                "tokens": dict(tok),
                "actual_cost_usd": round(spent, 4),
                "max_cost_usd": a.max_cost,
                "prices_usd_per_mtok": {"input": price_in, "output": price_out},
                "out": str(out_path),
                "complete": complete,
            },
            indent=1,
        )
    )
    return 0 if complete or not a.live else 1


if __name__ == "__main__":
    raise SystemExit(main())
