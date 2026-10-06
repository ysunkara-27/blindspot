"""M5 live smoke test: N debriefs on bench cases → eval/samples/debriefs_smoke.jsonl (+ latency/validator stats).

DRY-RUN BY DEFAULT (MockClient fed with template outputs; no network). A live run needs the human checkpoint
(CLAUDE.md), an explicit --live, an API key, and an estimated worst-case cost under --max-cost:

    uv run python -m backend.app.tutor.smoke --n 10 --max-cost 1.00            # dry run
    uv run python -m backend.app.tutor.smoke --n 10 --max-cost 1.00 --live     # after the checkpoint only

Learner behaviours are scripted per case (all correct, missed search / recognition / decision, mislabeled, wrong-side
mark, overcall on a normal) so every result type is exercised. Outcomes are scripted, not scored, because this
measures the tutor (latency, validator pass rates), not the scoring engine.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from backend.app.settings import REPO_ROOT, get_settings
from backend.app.tutor.client import AnthropicTutorClient, MockClient, RateLimiter
from backend.app.tutor.facts import build_facts
from backend.app.tutor.service import generate_debrief
from backend.app.tutor.templates import template_debrief
from shared.contracts import AttemptSubmit, Case, ClientTiming, Mark, Outcome, PatternSelection

BEHAVIOURS = (
    "all_correct",
    "missed_search",
    "missed_recognition",
    "missed_decision",
    "mislabeled",
    "wrong_side",
    "overcall_normal",
)
DWELL = {"missed_search": 120.0, "missed_recognition": 520.0, "missed_decision": 2100.0, "wrong_side": 80.0}
OTHER_LABEL = {
    "nodule": "mass",
    "mass": "nodule",
    "consolidation": "atelectasis",
    "atelectasis": "consolidation",
    "effusion": "pleural_thickening",
    "pleural_thickening": "effusion",
    "calcification": "nodule",
}
# Worst case per debrief: two attempts (regeneration) of ~7k input / ~700 output tokens.
EST_INPUT_TOKENS = 7000  # measured: ~2.1k image + ~3.3k cards + ~1k prompt/FACTS
EST_OUTPUT_TOKENS = 700


def _repo() -> Any:
    from backend.app.cases import get_repo

    return get_repo()


def _mark_zone(repo: Any, case: Case, x: float, y: float) -> str | None:
    try:
        from backend.app.search.coverage import MARK_ZONE_PRIORITY, zone_at

        zones, _ = repo.zones(case.case_id)
        return zone_at(x, y, zones, MARK_ZONE_PRIORITY)
    except Exception:  # noqa: BLE001
        return None


def _submit(marks: list[Mark], patterns: list[PatternSelection], declared_normal: bool = False) -> AttemptSubmit:
    return AttemptSubmit(
        marks=marks,
        patterns=patterns,
        declared_normal=declared_normal,
        normal_confidence=4 if declared_normal else None,
        telemetry=[],
        hints_used=0,
        client_timing=ClientTiming(shown_at="2026-10-06T12:00:00Z", submitted_at="2026-10-06T12:00:38Z"),
    )


def scenario(case: Case, behaviour: str, repo: Any) -> tuple[AttemptSubmit, list[Outcome], list[dict], dict]:
    focal = [f for f in case.findings if f.kind == "focal"]
    pats = [f for f in case.findings if f.kind == "pattern"]
    marks: list[Mark] = []
    outs: list[Outcome] = []
    rels: list[dict] = []
    target = focal[0] if focal else None
    for i, f in enumerate(focal, start=1):
        mid = f"M{len(marks) + 1}"
        if f is target and behaviour in ("missed_search", "missed_recognition", "missed_decision", "wrong_side"):
            outs.append(
                Outcome(
                    target=f.short_id,
                    result=behaviour if behaviour != "wrong_side" else "missed_search",
                    dwell_ms=DWELL[behaviour],
                    zone=f.primary_zone,
                )
            )
            if behaviour == "wrong_side":
                x, y = case.width - f.centroid[0], f.centroid[1]
                marks.append(Mark(mark_id=mid, x=x, y=y, label=f.label, confidence=4))  # type: ignore[arg-type]
                z = _mark_zone(repo, case, x, y)
                outs.append(Outcome(target=mid, result="false_positive", zone=z, learner_label=f.label))
                try:
                    from backend.app.search.spatial import relation_text

                    zones, _ = repo.zones(case.case_id)
                    rels.append(
                        {
                            "from": mid,
                            "to": f.short_id,
                            "text": relation_text(f.label, f.primary_zone, f.side, f.centroid, z, (x, y), zones),
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            continue
        label = f.label
        if f is target and behaviour == "mislabeled":
            label = OTHER_LABEL.get(f.label, "not_sure")
        marks.append(Mark(mark_id=mid, x=f.centroid[0], y=f.centroid[1], label=label, confidence=3))  # type: ignore
        res = "found" if label == f.label else "mislabeled"
        outs.append(
            Outcome(
                target=f.short_id,
                result=res,
                dwell_ms=1500.0,
                zone=f.primary_zone,
                matched=mid,
                learner_label=None if res == "found" else label,
            )
        )
        outs.append(
            Outcome(target=mid, result="true_positive", matched=f.short_id, zone=f.primary_zone, learner_label=label)
        )
    selections = [PatternSelection(label=p.label, confidence=3) for p in pats]  # type: ignore[arg-type]
    outs += [Outcome(target=p.short_id, result="pattern_found") for p in pats]
    if behaviour == "overcall_normal":
        x, y = 0.3 * case.width, 0.5 * case.height
        marks = [Mark(mark_id="M1", x=x, y=y, label="nodule", confidence=4)]
        outs = [
            Outcome(target="M1", result="false_positive", zone=_mark_zone(repo, case, x, y), learner_label="nodule")
        ]
        selections = []
    search = {
        "lung_coverage_pct": 52.0,
        "unvisited_review_areas": ["retrocardiac", "left_apex"],
        "first_visits": ["right_hilum", "left_hilum"],
        "zoom_used": True,
        "loupe_used": True,
    }
    return _submit(marks, selections), outs, rels, search


def pick_cases(repo: Any, n: int, split: str) -> list[tuple[Case, str]]:
    pool = sorted(repo.by_split(split), key=lambda c: c.case_id)
    abnormal = [c for c in pool if any(f.kind == "focal" for f in c.findings) and len(c.findings) <= 4]
    normals = [c for c in pool if c.is_normal]
    out: list[tuple[Case, str]] = []
    ai = ni = 0
    for i in range(n):
        b = BEHAVIOURS[i % len(BEHAVIOURS)]
        if b == "overcall_normal" and normals:
            out.append((normals[ni % len(normals)], b))
            ni += 1
        elif abnormal:
            out.append((abnormal[ai % len(abnormal)], b if b != "overcall_normal" else "all_correct"))
            ai += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--split", default="bench")
    ap.add_argument("--max-cost", type=float, required=True, help="USD ceiling for the worst-case estimate")
    ap.add_argument("--live", action="store_true", help="call the API (only after the human checkpoint)")
    ap.add_argument("--price-in", type=float, default=2.0, help="USD per million input tokens (verify pricing page)")
    ap.add_argument("--price-out", type=float, default=10.0, help="USD per million output tokens")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="default: eval/samples/debriefs_smoke.jsonl (live), logs/debriefs_smoke_dryrun.jsonl (dry run)",
    )
    a = ap.parse_args(argv)
    if a.out is None:
        a.out = REPO_ROOT / ("eval/samples/debriefs_smoke.jsonl" if a.live else "logs/debriefs_smoke_dryrun.jsonl")

    est = a.n * 2 * (EST_INPUT_TOKENS * a.price_in + EST_OUTPUT_TOKENS * a.price_out) / 1e6
    print(f"worst-case estimate: ${est:.2f} for {a.n} debriefs (max-cost ${a.max_cost:.2f})")
    if est > a.max_cost:
        print("refusing: estimate exceeds --max-cost", file=sys.stderr)
        return 2
    settings = get_settings()
    if a.live and not settings.anthropic_api_key:
        print("refusing: --live without ANTHROPIC_API_KEY", file=sys.stderr)
        return 2

    repo = _repo()
    picked = pick_cases(repo, a.n, a.split)
    if not picked:
        print(f"no cases in split {a.split!r} under {repo.root}", file=sys.stderr)
        return 1
    rows = []
    for i, (case, behaviour) in enumerate(picked):
        sub, outs, rels, search = scenario(case, behaviour, repo)
        mark_zones = {o.target: o.zone for o in outs if o.target.startswith("M")}
        facts = build_facts(
            case=case,
            submit=sub,
            outcomes=outs,
            spatial_relations=rels,
            search=search,
            mark_zones=mark_zones,
            level="MS2",
            history={},
        )
        if a.live:
            client: Any = AnthropicTutorClient(limiter=RateLimiter(10_000))
        else:
            client = MockClient([template_debrief(facts).model_dump()], model="dry-run")
        t0 = time.perf_counter()
        r = generate_debrief(
            facts,
            case,
            attempt_id=f"smoke-{i}",
            submit=sub,
            offline=False,
            cache_get=None,
            client=client,
            data_root=repo.root,
        )
        wall = (time.perf_counter() - t0) * 1000.0
        rows.append(
            {
                "case_id": case.case_id,
                "behaviour": behaviour,
                "live": a.live,
                "source": r["source"],
                "latency_ms": r["latency_ms"],
                "wall_ms": round(wall, 1),
                "model": r["model"],
                "prompt_version": r["prompt_version"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "validator": r["validator"],
                "provenance": r["provenance"],
                "debrief": r["debrief"].model_dump() if r["debrief"] is not None else None,
                "facts": json.loads(facts.model_dump_json(by_alias=True)),
            }
        )
        v = r["validator"]
        att = v.get("attempts") or []
        print(
            f"{i + 1:2d} {case.case_id:12s} {behaviour:19s} {r['source']:8s} {r['latency_ms']:8.0f} ms "
            f"first_try_ok={v.get('first_try_ok')} trimmed={v.get('trimmed')} calls={len(att)} "
            f"words={[x.get('words') for x in att]} final_ok={v.get('ok')}"
        )
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    live_rows = [r for r in rows if r["source"] == "live"]
    lat = [r["latency_ms"] for r in rows]
    tin = sum(r["input_tokens"] or 0 for r in rows)
    tout = sum(r["output_tokens"] or 0 for r in rows)
    print(
        json.dumps(
            {
                "n": len(rows),
                "mode": "live" if a.live else "dry-run",
                "p50_latency_ms": round(statistics.median(lat), 1),
                "p90_latency_ms": round(sorted(lat)[max(0, int(0.9 * len(lat)) - 1)], 1),
                "first_try_pass": sum(bool(r["validator"].get("first_try_ok")) for r in rows),
                "trimmed_no_regen": sum(
                    bool(r["validator"].get("trimmed")) and not r["validator"].get("regenerated") for r in rows
                ),
                "single_call": sum(len(r["validator"].get("attempts") or []) == 1 for r in live_rows),
                "regenerated": sum(bool(r["validator"].get("regenerated")) for r in rows),
                "first_try_words": [((r["validator"].get("attempts") or [{}])[0]).get("words") for r in rows],
                "live_final": len(live_rows),
                "template_fallbacks": sum(r["source"] == "template" for r in rows),
                "final_validator_failures": sum(not r["validator"].get("ok") for r in rows),
                "tokens_in": tin,
                "tokens_out": tout,
                "est_cost_usd": round((tin * a.price_in + tout * a.price_out) / 1e6, 4),
                "out": str(a.out),
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
