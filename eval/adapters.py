"""Thin adapter between the eval harness and the production engines. If a production signature changes, fix it here.

- Scoring + search: the real pure functions in backend.app.scoring / backend.app.search, composed exactly as an
  attempt submit does (hit test → Hungarian matching → dwell → miss type → outcomes → score; coverage; relations).
- Tutor: backend.app.tutor.{facts,service,validator,templates,cards} per the TUTOR INTERFACE in docs/PROGRESS.md,
  imported lazily. A missing module falls back to eval.reference_tutor and is recorded in ENGINE_STATUS so every
  report says which implementation produced its numbers. Live faithfulness runs refuse to use fallbacks.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from shared.contracts import (
    AttemptSubmit,
    Case,
    DebriefFacts,
    DebriefOutput,
    FactsSearch,
    Finding,
    Outcome,
    SpatialRelation,
)

ENGINE_STATUS: dict[str, str] = {}


def _try_import(modname: str) -> Any | None:
    try:
        return importlib.import_module(modname)
    except ImportError:
        return None


def _status(component: str, value: str) -> None:
    ENGINE_STATUS[component] = value


def engine_status_lines() -> list[str]:
    return [f"- `{k}`: {v}" for k, v in sorted(ENGINE_STATUS.items())]


def uses_fallback(*components: str) -> list[str]:
    return [c for c in components if ENGINE_STATUS.get(c, "").startswith("eval.reference")]


# ================================================================================================ config + repo
def cfg_scoring() -> dict[str, Any]:
    from backend.app import config

    return config.scoring()


def related_groups() -> tuple[frozenset[str], ...]:
    from backend.app import config

    return config.related_groups()


def review_area_ids() -> list[str]:
    from backend.app import config

    return config.review_area_ids()


def adjacency() -> dict[str, list[str]]:
    from backend.app import config

    return dict(config.review_areas().get("adjacency", {}))


def display(label: str) -> str:
    from backend.app import config

    return config.display(label)


def zone_human(zone: str | None) -> str:
    from backend.app import config

    return config.zone_human(zone)


def repo_for(root: Path) -> Any:
    """backend.app.cases.CaseRepository rooted at a processed dir (fixtures or data/processed)."""
    from backend.app.cases import CaseRepository

    return CaseRepository(Path(root))


def dilate(mask: np.ndarray, radius_px: float) -> np.ndarray:
    from backend.app.cases import dilate as _dilate

    return _dilate(mask, int(round(radius_px)))


# ================================================================================================ search primitives
def dwell_ms(events: list[Any], region: np.ndarray, dwell_cfg: dict[str, Any]) -> float:
    from backend.app.search import dwell

    _status("search.dwell", "backend.app.search.dwell.dwell_ms (production)")
    return float(dwell.dwell_ms(events, region, dwell_cfg))


def miss_type(dwell: float, miss_cfg: dict[str, Any]) -> str:
    from backend.app.search import misstype

    _status("search.misstype", "backend.app.search.misstype.miss_type (production)")
    return str(misstype.miss_type(dwell, miss_cfg))


# ================================================================================================ attempt pipeline
@dataclass
class AttemptResult:
    outcomes: list[Outcome]
    score: float
    success: bool
    dwell_by_finding: dict[str, float]
    mark_zones: dict[str, str | None]
    spatial_relations: list[SpatialRelation]
    search: FactsSearch
    pairs: dict[str, str] = field(default_factory=dict)

    def result_by_target(self) -> dict[str, str]:
        return {o.target: o.result for o in self.outcomes}


def score_attempt(case: Case, submit: AttemptSubmit, repo: Any, cfg: dict[str, Any] | None = None) -> AttemptResult:
    """Run the production scoring + search engines on one attempt (pure functions, composed as on submit)."""
    from backend.app.scoring import hit, matching, outcomes, scores
    from backend.app.search import coverage, dwell, spatial

    _status("scoring", "backend.app.scoring.{hit,matching,outcomes,scores} (production)")
    _status("search", "backend.app.search.{dwell,misstype,coverage,spatial} (production)")
    cfg = cfg or cfg_scoring()
    w = case.width
    tau = hit.tolerance_px(w, cfg)
    rho = float(cfg["roi"]["roi_frac"]) * w
    focal = [f for f in case.findings if f.kind == "focal"]
    patterns = [f for f in case.findings if f.kind == "pattern"]
    marks = list(submit.marks)

    masks = {f.short_id: repo.mask(case.case_id, f.finding_id) for f in focal}
    dil_tau = {k: (dilate(m, tau) if m is not None else None) for k, m in masks.items()}
    hit_m = np.zeros((len(marks), len(focal)), dtype=bool)
    for i, mk in enumerate(marks):
        for j, f in enumerate(focal):
            hit_m[i, j] = hit.hits(mk.x, mk.y, f, tau, dil_tau[f.short_id])
    mres = matching.match(
        [m.mark_id for m in marks],
        [m.label for m in marks],
        [f.short_id for f in focal],
        [f.label for f in focal],
        hit_m,
        related_groups(),
        cfg["matching_costs"],
    )

    samples = dwell.dwell_samples(submit.telemetry, cfg["dwell"])
    dwell_by = {}
    for f in focal:
        m = masks[f.short_id]
        roi = dilate(m, rho) if m is not None else _bbox_mask(f, case, rho)
        dwell_by[f.short_id] = dwell.dwell_in(samples, roi)

    zones, _meta = repo.zones(case.case_id)
    mark_zone = {m.mark_id: coverage.nearest_zone(m.x, m.y, zones, coverage.MARK_ZONE_PRIORITY) for m in marks}
    outs = (
        outcomes.focal_outcomes(focal, marks, mres, dwell_by, cfg["miss_types"])
        + outcomes.pattern_outcomes(patterns, submit.patterns)
        + outcomes.mark_outcomes(marks, mres, mark_zone)
        + outcomes.normal_outcome(submit.declared_normal, marks)
    )
    credit = scores.label_credit_for([mres.pair_cost[m] for m in mres.pairs], cfg["matching_costs"])
    parts = scores.parts(outs, credit, submit.hints_used)
    score = scores.case_score(parts, case.is_normal, cfg)
    success = scores.case_success(parts, case.is_normal, cfg)

    cov = coverage.review_coverage(samples, zones, review_area_ids(), float(cfg["dwell"]["visit_ms"]))
    lung_pct = coverage.lung_coverage_pct(samples, zones.get("lungs"), rho)
    sm = coverage.search_metrics(submit.telemetry, marks, None)
    search = FactsSearch(
        lung_coverage_pct=lung_pct,
        unvisited_review_areas=cov.unvisited,
        first_visits=cov.first_visits,
        zoom_used=bool(sm["zoom_used"]),
        loupe_used=bool(sm["loupe_used"]),
    )

    rels = []
    by_short = {f.short_id: f for f in focal}
    for o in outs:
        if o.result not in ("missed_search", "missed_recognition", "missed_decision", "mislabeled"):
            continue
        f = by_short[o.target]
        mk = _nearest_mark(f, marks, prefer=o.matched)
        if mk is None:
            continue
        text = spatial.relation_text(
            f.label, f.primary_zone, f.side, f.centroid, mark_zone.get(mk.mark_id), (mk.x, mk.y), zones
        )
        rels.append(SpatialRelation.model_validate({"from": mk.mark_id, "to": f.short_id, "text": text}))
    return AttemptResult(
        outs, score, success, {k: round(v, 1) for k, v in dwell_by.items()}, mark_zone, rels, search, dict(mres.pairs)
    )


def _nearest_mark(f: Finding, marks: list[Any], prefer: str | None) -> Any | None:
    if prefer:
        for m in marks:
            if m.mark_id == prefer:
                return m
    if not marks:
        return None
    cx, cy = f.centroid
    return min(marks, key=lambda m: (m.x - cx) ** 2 + (m.y - cy) ** 2)


def _bbox_mask(f: Finding, case: Case, pad: float) -> np.ndarray:
    m = np.zeros((case.height, case.width), dtype=bool)
    x0, y0, x1, y1 = f.geometry.bbox
    m[max(0, int(y0 - pad)) : int(y1 + pad) + 1, max(0, int(x0 - pad)) : int(x1 + pad) + 1] = True
    return m


# ================================================================================================ tutor
def _call_flex(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Call fn with only the keyword arguments it accepts (tolerates optional-kwarg drift)."""
    sig = inspect.signature(fn)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(**kwargs)
    return fn(**{k: v for k, v in kwargs.items() if k in sig.parameters})


def build_facts(
    case: Case, submit: AttemptSubmit, res: AttemptResult, *, level: str = "MS2", history: dict[str, Any] | None = None
) -> DebriefFacts:
    mod = _try_import("backend.app.tutor.facts")
    kw = dict(
        case=case,
        submit=submit,
        outcomes=res.outcomes,
        spatial_relations=res.spatial_relations,
        search=res.search,
        mark_zones=res.mark_zones,
        level=level,
        history=history or {},
    )
    if mod is not None and hasattr(mod, "build_facts"):
        _status("tutor.facts", "backend.app.tutor.facts.build_facts (production)")
        out = _call_flex(mod.build_facts, **kw)
        return out if isinstance(out, DebriefFacts) else DebriefFacts.model_validate(out)
    from eval import reference_tutor

    _status("tutor.facts", "eval.reference_tutor.build_facts (fallback: backend.app.tutor.facts missing)")
    return reference_tutor.build_facts(**kw)


def load_cards() -> dict[str, Any]:
    mod = _try_import("backend.app.tutor.cards")
    if mod is not None and hasattr(mod, "load_cards"):
        _status("tutor.cards", "backend.app.tutor.cards.load_cards (production)")
        return dict(mod.load_cards())
    from eval import reference_tutor

    _status("tutor.cards", "eval.reference_tutor.load_cards (fallback: reads content/teaching_cards/*.yaml)")
    return reference_tutor.load_cards()


def load_zone_mimics() -> dict[str, Any]:
    mod = _try_import("backend.app.tutor.cards")
    if mod is not None and hasattr(mod, "load_zone_mimics"):
        return dict(mod.load_zone_mimics())
    return {}


def cards_block_text() -> str:
    """The exact cached second system block the production debrief uses (cards + zone mimics)."""
    mod = _try_import("backend.app.tutor.cards")
    if mod is not None and hasattr(mod, "all_cards_text"):
        return str(mod.all_cards_text())
    from eval import reference_tutor

    return reference_tutor.cards_text(reference_tutor.load_cards())


def validator_cfg() -> dict[str, Any]:
    mod = _try_import("backend.app.tutor.vocab")
    if mod is not None and hasattr(mod, "validator_cfg"):
        return dict(mod.validator_cfg())
    return dict(cfg_scoring().get("validator", {}))


def normalize_validator(v: Any) -> dict[str, Any]:
    """Map whatever the production validator returns onto {'ok': bool, 'errors': [str], 'raw': ...}."""
    if v is None:
        return {"ok": False, "errors": ["validator returned None"], "raw": None}
    if hasattr(v, "to_dict"):
        v = v.to_dict()
    elif hasattr(v, "model_dump"):
        v = v.model_dump()
    elif hasattr(v, "__dataclass_fields__"):
        v = {k: getattr(v, k) for k in v.__dataclass_fields__}
    if isinstance(v, tuple) and len(v) == 2:
        return {"ok": bool(v[0]), "errors": [str(e) for e in (v[1] or [])], "raw": None}
    if isinstance(v, bool):
        return {"ok": v, "errors": [], "raw": v}
    if isinstance(v, dict):
        ok = next((v[k] for k in ("ok", "passed", "valid", "pass") if k in v), None)
        errs = next((v[k] for k in ("errors", "problems", "failures", "violations") if k in v), [])
        errs = [e if isinstance(e, str) else str(e) for e in (errs or [])]
        return {"ok": bool(ok) if ok is not None else not errs, "errors": errs, "raw": v}
    return {"ok": False, "errors": [f"unrecognised validator result {type(v).__name__}"], "raw": str(v)}


def validate(output: DebriefOutput | dict[str, Any], facts: DebriefFacts, case: Case) -> dict[str, Any]:
    """Production validator: validate(out, facts, cards, cfg, zone_mimics=...) (backend.app.tutor.validator)."""
    out = output if isinstance(output, DebriefOutput) else DebriefOutput.model_validate(output)
    mod = _try_import("backend.app.tutor.validator")
    if mod is not None and hasattr(mod, "validate"):
        _status("tutor.validator", "backend.app.tutor.validator.validate (production)")
        return normalize_validator(
            mod.validate(out, facts, load_cards(), validator_cfg(), zone_mimics=load_zone_mimics())
        )
    from eval import checks

    _status("tutor.validator", "eval.checks.validate (fallback: backend.app.tutor.validator missing)")
    return checks.validate(out.model_dump(), facts)


def template_debrief(facts: DebriefFacts, case: Case) -> DebriefOutput:
    mod = _try_import("backend.app.tutor.templates")
    if mod is not None and hasattr(mod, "template_debrief"):
        _status("tutor.templates", "backend.app.tutor.templates.template_debrief (production)")
        out = mod.template_debrief(facts, load_cards(), load_zone_mimics(), validator_cfg())
        return out if isinstance(out, DebriefOutput) else DebriefOutput.model_validate(out)
    from eval import reference_tutor

    _status("tutor.templates", "eval.reference_tutor.template_debrief (fallback: templates missing)")
    return reference_tutor.template_debrief(facts, cards=load_cards())


def production_debrief_params() -> dict[str, Any]:
    """Effort and max_tokens the production debrief call uses (so condition U can mirror them exactly)."""
    mod = _try_import("backend.app.tutor.client")
    if mod is None:
        return {"effort": "default", "max_tokens": 1200, "source": "SPEC §8.5 defaults (tutor client missing)"}
    c = mod.AnthropicTutorClient(model="probe", sdk_client=object())
    return {
        "effort": c.effort or "default",
        "max_tokens": int(mod.DEBRIEF_MAX_TOKENS),
        "source": "backend.app.tutor.client (AnthropicTutorClient defaults)",
    }


def tutor_client(sdk_like: Any, model: str) -> Any:
    """The production AnthropicTutorClient around an injected SDK-like client, with an eval-owned rate limiter
    (the process-wide 30/min app limiter would silently turn eval calls into template fallbacks)."""
    mod = _try_import("backend.app.tutor.client")
    if mod is None:
        return sdk_like
    return mod.AnthropicTutorClient(model=model, sdk_client=sdk_like, limiter=mod.RateLimiter(1_000_000))


def generate_debrief(
    facts: DebriefFacts, case: Case, submit: AttemptSubmit, *, client: Any, attempt_id: str, data_root: Path, model: str
) -> dict[str, Any]:
    """Condition G: the production pipeline (tutor service) with an injected client; never uses the tutor cache."""
    mod = _try_import("backend.app.tutor.service")
    if mod is not None and hasattr(mod, "generate_debrief"):
        _status("tutor.service", "backend.app.tutor.service.generate_debrief (production)")
        return _call_flex(
            mod.generate_debrief,
            facts=facts,
            case=case,
            attempt_id=attempt_id,
            submit=submit,
            offline=False,
            cache_get=lambda _k: None,
            client=tutor_client(client, model),
            data_root=data_root,
        )
    from eval import reference_tutor

    _status("tutor.service", "eval.reference_tutor.generate_debrief (fallback: backend.app.tutor.service missing)")
    return reference_tutor.generate_debrief(
        facts, case, submit, client=client, data_root=data_root, model=model, cards=load_cards()
    )


def debrief_system_prompt() -> tuple[str, str]:
    """(text, source) of the production debrief system prompt, else SPEC §8.3's v1 text."""
    from eval.common import REPO_ROOT

    p = REPO_ROOT / "backend" / "app" / "prompts" / "debrief_system.md"
    if p.exists():
        return p.read_text(), "backend/app/prompts/debrief_system.md"
    from eval import reference_tutor

    return reference_tutor.spec_system_prompt(), "docs/SPEC.md §8.3 (v1)"
