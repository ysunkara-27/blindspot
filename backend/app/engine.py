"""Evaluate one submitted attempt: scoring + search analysis + reveal + facts card.

Composes the small pure engines. Deterministic: same case + submit → same result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from backend.app import config
from backend.app.cases import CaseRepository
from backend.app.config import zone_human
from backend.app.facts_card import build_facts_card
from backend.app.scoring.hit import hits, tolerance_px
from backend.app.scoring.matching import match
from backend.app.scoring.outcomes import focal_outcomes, mark_outcomes, normal_outcome, pattern_outcomes
from backend.app.scoring.scores import case_score, case_success, label_credit_for, parts
from backend.app.search.coverage import (
    MARK_ZONE_PRIORITY,
    lung_coverage_pct,
    nearest_zone,
    review_coverage,
    search_metrics,
    zone_at,
)
from backend.app.search.dwell import dwell_in, dwell_samples, first_time_reaching
from backend.app.search.heatmap import heatmap_png_b64
from backend.app.search.spatial import no_mark_text, relation_label, relation_text
from shared.contracts import (
    Arrow,
    AttemptSubmit,
    Case,
    FactsCard,
    FactsSearch,
    Outcome,
    Reveal,
    RevealFinding,
    RevealMark,
    SearchSummary,
    SpatialRelation,
)

MISSED = ("missed_search", "missed_recognition", "missed_decision")


@dataclass
class Evaluation:
    score: float
    success: bool
    outcomes: list[Outcome]
    reveal: Reveal
    facts_card: FactsCard
    spatial_relations: list[SpatialRelation]
    facts_search: FactsSearch
    mark_zones: dict[str, str | None]
    finding_results: list[tuple[str, float]]  # (label, 1 = localized) for Elo
    search_json: dict[str, Any] = field(default_factory=dict)


def _client_seconds(submit: AttemptSubmit) -> float | None:
    try:
        a = datetime.fromisoformat(submit.client_timing.shown_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(submit.client_timing.submitted_at.replace("Z", "+00:00"))
        s = (b - a).total_seconds()
        return round(s, 2) if s >= 0 else None
    except ValueError:
        return None


def evaluate(case: Case, submit: AttemptSubmit, repo: CaseRepository, hints_used: int | None = None) -> Evaluation:
    if case.volume is not None:  # CT / MR: backend/app/engine_volume.py (the X-ray path below is unchanged)
        from backend.app.engine_volume import evaluate_volume

        return evaluate_volume(case, submit, repo, hints_used=hints_used)
    sc = config.scoring()
    W = case.width
    tau = tolerance_px(W, sc)
    rho = float(sc["roi"]["roi_frac"]) * W
    zones, zmeta = repo.zones(case.case_id)
    marks = [] if submit.declared_normal else list(submit.marks)
    focal = [f for f in case.findings if f.kind == "focal"]
    pats = [f for f in case.findings if f.kind == "pattern"]
    hints_n = max(submit.hints_used, hints_used or 0)

    # ---- hit matrix + matching
    hit = np.zeros((len(marks), len(focal)), dtype=bool)
    for j, f in enumerate(focal):
        dm = repo.dilated_mask(case.case_id, f.finding_id, int(round(tau)))
        for i, mk in enumerate(marks):
            hit[i, j] = hits(mk.x, mk.y, f, tau, dm)
    costs = sc["matching_costs"]
    m = match(
        [mk.mark_id for mk in marks],
        [mk.label for mk in marks],
        [f.short_id for f in focal],
        [f.label for f in focal],
        hit,
        config.related_groups(),
        costs,
    )

    # ---- dwell per finding ROI
    samples = dwell_samples(submit.telemetry, sc["dwell"])
    dwell_by_f: dict[str, float] = {}
    roi_entry: dict[str, float | None] = {}
    for f in focal + pats:
        dm = repo.dilated_mask(case.case_id, f.finding_id, int(round(rho)))
        if dm is None:  # bbox fallback
            dm = np.zeros((case.height, W), bool)
            x0, y0, x1, y1 = f.geometry.bbox
            dm[max(0, int(y0 - rho)) : int(y1 + rho) + 1, max(0, int(x0 - rho)) : int(x1 + rho) + 1] = True
        dwell_by_f[f.short_id] = dwell_in(samples, dm)
        roi_entry[f.short_id] = first_time_reaching(samples, dm, 1e-6)

    # ---- mark zones
    mark_zones = {mk.mark_id: zone_at(mk.x, mk.y, zones, MARK_ZONE_PRIORITY) for mk in marks}

    # ---- outcomes
    outs: list[Outcome] = []
    outs += focal_outcomes(focal, marks, m, dwell_by_f, sc["miss_types"])
    outs += pattern_outcomes(pats, submit.patterns)
    outs += mark_outcomes(marks, m, mark_zones)
    if case.is_normal:
        outs += normal_outcome(submit.declared_normal, marks)

    p = parts(outs, label_credit_for(list(m.pair_cost.values()), costs), hints_n)
    score = case_score(p, case.is_normal, sc)
    success = case_success(p, case.is_normal, sc)

    # ---- search summary
    cov = review_coverage(samples, zones, config.review_area_ids(), sc["dwell"]["visit_ms"], config.zone_ids())
    lungs = zones.get("lungs")
    lung_pct = lung_coverage_pct(samples, lungs, rho)
    met = search_metrics(submit.telemetry, marks, _client_seconds(submit))
    heat = heatmap_png_b64(samples, W, case.height, rho)
    search = SearchSummary(
        lung_coverage_pct=lung_pct,
        unvisited_review_areas=cov.unvisited,
        visited_review_areas=cov.visited,
        first_visits=cov.first_visits,
        heatmap_png_b64=heat,
        **met,
    )
    facts_search = FactsSearch(
        lung_coverage_pct=lung_pct,
        unvisited_review_areas=cov.unvisited,
        first_visits=cov.first_visits[:6],
        zoom_used=met["zoom_used"],
        loupe_used=met["loupe_used"],
    )

    # ---- reveal: findings, marks, arrows, spatial relations
    by_target = {o.target: o for o in outs}
    reveal_findings = [
        RevealFinding(
            finding_id=f.short_id,
            label=f.label,
            display=config.display(f.label),
            kind=f.kind,
            polygon=f.geometry.polygon,
            bbox=f.geometry.bbox,
            centroid=f.centroid,
            side=f.side,
            zones=f.zones,
            primary_zone=f.primary_zone,
            relative_location=f.relative_location,
            result=by_target[f.short_id].result if f.short_id in by_target else None,
            dwell_ms=round(dwell_by_f.get(f.short_id, 0.0), 1),
        )
        for f in case.findings
    ]
    reveal_marks = [
        RevealMark(mark_id=o.target, result=o.result, matched_finding=o.matched, zone=o.zone)  # type: ignore[arg-type]
        for o in outs
        if o.result in ("true_positive", "duplicate", "false_positive")
    ]
    wrong = [mk for mk in marks if by_target.get(mk.mark_id) and by_target[mk.mark_id].result == "false_positive"]
    arrows: list[Arrow] = []
    relations: list[SpatialRelation] = []
    for f in focal:
        o = by_target[f.short_id]
        if o.result not in MISSED:
            continue
        if wrong:
            mk = min(wrong, key=lambda k: (k.x - f.centroid[0]) ** 2 + (k.y - f.centroid[1]) ** 2)
            mz = mark_zones.get(mk.mark_id) or nearest_zone(mk.x, mk.y, zones, MARK_ZONE_PRIORITY)
            text = relation_text(f.label, f.primary_zone, f.side, f.centroid, mz, (mk.x, mk.y), zones)
            label = relation_label(f.primary_zone, f.side, f.centroid, mz, (mk.x, mk.y), zones)
            arrows.append(
                Arrow(
                    from_mark=mk.mark_id,
                    to_finding=f.short_id,
                    text=text,
                    label=label,
                    from_xy=(mk.x, mk.y),
                    to_xy=f.centroid,
                )
            )
            relations.append(SpatialRelation(**{"from": mk.mark_id, "to": f.short_id, "text": text}))
        else:
            text = no_mark_text(f.label, f.relative_location, f.primary_zone)
            arrows.append(
                Arrow(
                    from_mark=None,
                    to_finding=f.short_id,
                    text=text,
                    label=zone_human(f.primary_zone),
                    from_xy=(W / 2, case.height / 2),
                    to_xy=f.centroid,
                )
            )
    # FP marks without a missed finding to point at still get a relation to the nearest finding (for the tutor)
    for mk in wrong:
        if any(r.from_ == mk.mark_id for r in relations) or not focal:
            continue
        f = min(focal, key=lambda g: (mk.x - g.centroid[0]) ** 2 + (mk.y - g.centroid[1]) ** 2)
        mz = mark_zones.get(mk.mark_id) or nearest_zone(mk.x, mk.y, zones, MARK_ZONE_PRIORITY)
        relations.append(
            SpatialRelation(
                **{
                    "from": mk.mark_id,
                    "to": f.short_id,
                    "text": relation_text(f.label, f.primary_zone, f.side, f.centroid, mz, (mk.x, mk.y), zones),
                }
            )
        )

    approx = bool(case.zones_approximate or zmeta.get("approximate", False))
    reveal = Reveal(
        findings=reveal_findings,
        marks=reveal_marks,
        arrows=arrows,
        search=search,
        ctr=case.cardiothoracic_ratio if any(f.label == "cardiomegaly" for f in pats) else None,
        is_normal=case.is_normal,
        zones_approximate=approx,
    )
    card = build_facts_card(case, outs, score, success, facts_search, submit.declared_normal)
    finding_results = [
        (f.label, 1.0 if by_target[f.short_id].result in ("found", "mislabeled") else 0.0) for f in focal
    ]
    finding_results += [(f.label, 1.0 if by_target[f.short_id].result == "pattern_found" else 0.0) for f in pats]
    search_json = {
        **search.model_dump(exclude={"heatmap_png_b64"}),
        "dwell_by_zone": cov.dwell_by_zone,
        "dwell_by_finding": {k: round(v, 1) for k, v in dwell_by_f.items()},
        "time_to_roi_ms": roi_entry,
        "n_events": len(submit.telemetry),
        "rho_px": rho,
        "tau_px": tau,
        "label_credit": p.label_credit,
        "lungs_bbox": _bbox(lungs),
    }
    return Evaluation(
        score, success, outs, reveal, card, relations, facts_search, mark_zones, finding_results, search_json
    )


def _bbox(m: np.ndarray | None) -> list[float] | None:
    if m is None or not m.any():
        return None
    ys, xs = np.nonzero(m)
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
