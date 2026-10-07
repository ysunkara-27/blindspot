"""Evaluate one submitted attempt on a CT / MR volume: scoring + slice-dwell search analysis + reveal + facts card.

Composes backend/app/scoring/volume.py and backend/app/search/volume.py with the shared Hungarian matching, outcome
builders and score weights of the X-ray engine (unchanged). Deterministic: same case + submit → same result.
The X-ray engine (backend/app/engine.py) dispatches here when `case.volume` is set.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.app import config
from backend.app.cases import SLAB_THIRDS, CaseRepository, anatomy_zone_values
from backend.app.config import zone_human
from backend.app.facts_card import build_facts_card
from backend.app.scoring.matching import match
from backend.app.scoring.outcomes import normal_outcome, pattern_outcomes
from backend.app.scoring.outline import (
    normalize_mark,
    outline_cfg,
    outline_hits,
    outline_verdict_for,
    overlap_stats,
    rasterize,
)
from backend.app.scoring.scores import case_score, case_success, label_credit_for, parts
from backend.app.scoring.volume import (
    hits_volume,
    mark_voxel,
    size_verdicts,
    structure_at,
    tolerance_voxels,
)
from backend.app.search.coverage import search_metrics
from backend.app.search.volume import (
    box_of,
    coverage,
    finding_axial_slices_seen,
    finding_slice_ms,
    inplane_direction_words,
    miss_type_volume,
    near_ms,
    slice_direction_words,
    slice_dwell_list,
    slice_trace,
    slices_viewed_pct,
    zone_of_voxel,
)
from backend.app.signs import signs_for_case
from backend.app.volumes import provenance_badge
from shared.contracts import (
    Arrow,
    AttemptSubmit,
    Case,
    FactsSearch,
    Outcome,
    Reveal,
    RevealFinding,
    RevealMark,
    SearchSummary,
    SpatialRelation,
)

MISSED = ("missed_search", "missed_recognition", "missed_decision")
SLAB_ORDER = ("superior_slab", "mid_slab", "inferior_slab")


def _client_seconds(submit: AttemptSubmit) -> float | None:
    from backend.app.engine import _client_seconds as f

    return f(submit)


def mark_zone_priority(zones: dict[str, np.ndarray]) -> list[str]:
    """Organs (and hemispheres) first, then slab thirds."""
    organs = [z for z in zones if z not in SLAB_THIRDS and z not in ("right_half", "left_half", "midline_volume")]
    return organs + list(SLAB_ORDER)


def _side_of_x(x: float, nx: int) -> str:
    return "right" if x < nx / 2 else "left"  # patient right = low x (image left)


def relation_text_volume(
    f_label: str,
    f_zone: str | None,
    f_c3: tuple[float, float, float],
    f_range: tuple[int, int],
    m_zone: str | None,
    m_v: tuple[float, float, float],
    shape: tuple[int, int, int],
) -> tuple[str, str]:
    """(sentence, short arrow label): slices above/below + patient-side in-plane direction. Never mm. Slice numbers
    in text are 1-based (index + 1); the contract fields (slice_range, Mark.slice) stay 0-based."""
    name = config.display(f_label).lower()
    z0, z1 = f_range
    slices = f"slices {z0 + 1}–{z1 + 1}" if z1 != z0 else f"slice {z0 + 1}"  # 1-based for people
    sw = slice_direction_words(m_v[2], f_c3[2])
    dirs = inplane_direction_words((m_v[0], m_v[1]), (f_c3[0], f_c3[1]), shape)
    where = zone_human(f_zone) if f_zone else None
    bits = [b for b in [sw, *dirs] if b]
    label = ", ".join(bits) if bits else (where or slices)
    mz = zone_human(m_zone) if m_zone else "an unlabelled area"
    if bits:
        text = f"Your mark was in the {mz} on slice {int(round(m_v[2])) + 1}; the {name} is {', '.join(bits)}"
        text += f", on {slices}" + (f" in the {where}." if where else ".")
    else:
        text = f"Your mark was on the {name}'s slices, in the {mz}; the {name} is on {slices}" + (
            f" in the {where}." if where else "."
        )
    return text, label


def evaluate_volume(case: Case, submit: AttemptSubmit, repo: CaseRepository, hints_used: int | None = None) -> Any:
    from backend.app.engine import Evaluation

    assert case.volume is not None
    sc = config.scoring()
    vc = sc["volumetric"]
    shape = tuple(int(n) for n in case.volume.shape)
    spacing = tuple(float(s) for s in case.volume.spacing)
    nz, ny, nx = shape
    mv = repo.maskvol(case.case_id)
    if mv is None:
        mv = np.zeros(shape, np.uint8)
    zones = repo.volume_zones(case.case_id)
    priority = mark_zone_priority(zones)
    marks = [] if submit.declared_normal else [normalize_mark(mk) for mk in submit.marks]
    focal = [f for f in case.findings if f.kind == "focal"]
    pats = [f for f in case.findings if f.kind == "pattern"]
    hints_n = max(submit.hints_used, hints_used or 0)
    slice_window, tau_y, tau_x = tolerance_voxels(shape, spacing, vc)
    rescue = bool(vc["hit"].get("cross_label_rescue", False))
    ocfg = outline_cfg(sc)

    # ---- hit matrix + matching (same Hungarian + label costs as X-ray). A drawn outline (axial slice only) also
    # hits by IoU / area fraction against the finding's mask on the mark's slice.
    voxels = {mk.mark_id: mark_voxel(mk) for mk in marks}
    fmasks = {f.short_id: repo.finding_volmask(case.case_id, f.finding_id) for f in focal}
    hit = np.zeros((len(marks), len(focal)), dtype=bool)
    rasters: dict[str, tuple[int, np.ndarray]] = {}
    for mk in marks:
        if mk.polygon and (mk.plane or "axial") == "axial" and mk.slice is not None and 0 <= int(mk.slice) < nz:
            rasters[mk.mark_id] = (int(mk.slice), rasterize(mk.polygon, ny, nx))
    stats: dict[tuple[str, str], dict[str, float]] = {}
    for j, f in enumerate(focal):
        fm = fmasks[f.short_id]
        if fm is None:
            continue
        for i, mk in enumerate(marks):
            v = voxels[mk.mark_id]
            hit[i, j] = v is not None and hits_volume(v, fm, mv, slice_window, tau_y, tau_x, rescue)
            if mk.mark_id in rasters:
                z, pm = rasters[mk.mark_id]
                st = overlap_stats(pm, fm[z])
                stats[(mk.mark_id, f.short_id)] = st
                hit[i, j] = hit[i, j] or outline_hits(st, ocfg)
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

    # ---- slice dwell per finding
    tr = slice_trace(submit.telemetry, sc["dwell"])
    boxes = {f.short_id: box_of(f, shape) for f in focal + pats}
    visit_ms = float(vc["dwell"]["visit_ms"])
    slice_ms = {fid: finding_slice_ms(tr, b) for fid, b in boxes.items()}
    near = {fid: near_ms(tr, b, spacing, float(vc["dwell"]["near_mm"])) for fid, b in boxes.items()}
    seen_n = {fid: finding_axial_slices_seen(tr, b, visit_ms) for fid, b in boxes.items()}
    slices_viewed = {fid: seen_n[fid] > 0 for fid in boxes}

    # ---- mark zones + structures
    anatomy = anatomy_zone_values(case)
    value_zone = {v: z for z, vals in anatomy.items() for v in vals}
    mark_zones: dict[str, str | None] = {}
    for mk in marks:
        v = voxels[mk.mark_id]
        z = value_zone.get(structure_at(mv, v)) if v is not None else None
        mark_zones[mk.mark_id] = z or zone_of_voxel(v, zones, priority)

    # ---- outcomes
    verdicts = size_verdicts(m.pairs, {f.short_id: f for f in focal}, submit.measurements, vc)
    by_mark = {mk.mark_id: mk for mk in marks}
    outs: list[Outcome] = []
    for f in focal:
        fid = f.short_id
        dwell = round(slice_ms.get(fid, 0.0), 1)
        mid = m.mark_for(fid)
        if mid is None:
            outs.append(
                Outcome(
                    target=fid,
                    result=miss_type_volume(dwell, near.get(fid, 0.0), vc["dwell"]),
                    dwell_ms=dwell,
                    zone=f.primary_zone,
                    slices_viewed=slices_viewed[fid],
                )
            )
            continue
        mk = by_mark[mid]
        res = "found" if mk.label == f.label else "mislabeled"
        sv = verdicts.get(fid)
        outs.append(
            Outcome(
                target=fid,
                result=res,
                dwell_ms=dwell,
                zone=f.primary_zone,
                matched=mid,
                learner_label=None if res == "found" else mk.label,
                size_verdict=sv.model_dump() if sv else None,
                slices_viewed=slices_viewed[fid],
            )
        )
    outs += pattern_outcomes(pats, submit.patterns)
    for mk in marks:  # marks that hit nothing are `unmatched` (never false_positive on a volume)
        z = mark_zones.get(mk.mark_id)
        if mk.mark_id in m.pairs:
            outs.append(
                Outcome(
                    target=mk.mark_id,
                    result="true_positive",
                    matched=m.pairs[mk.mark_id],
                    zone=z,
                    learner_label=mk.label,
                )
            )
        elif mk.mark_id in m.duplicates:
            outs.append(
                Outcome(
                    target=mk.mark_id,
                    result="duplicate",
                    matched=m.duplicates[mk.mark_id],
                    zone=z,
                    learner_label=mk.label,
                )
            )
        else:
            outs.append(Outcome(target=mk.mark_id, result="unmatched", zone=z, learner_label=mk.label))
    if case.is_normal:
        outs += normal_outcome(submit.declared_normal, marks)

    p = parts(outs, label_credit_for(list(m.pair_cost.values()), costs), hints_n)
    score = case_score(p, case.is_normal, sc)
    success = case_success(p, case.is_normal, sc)

    # ---- search summary
    areas = list(
        (config.review_areas().get("volumetric", {}).get("review_areas") or {}).get(case.body_region or "", [])
    )
    cov = coverage(tr, zones, shape, areas, visit_ms)
    pct = slices_viewed_pct(tr, nz, visit_ms)
    met = search_metrics(submit.telemetry, marks, _client_seconds(submit))
    sd = slice_dwell_list(tr, {fid: boxes[fid] for fid in boxes})
    search = SearchSummary(
        lung_coverage_pct=pct,  # volume analogue: % of axial slices seen ≥ visit_ms (no lungs on a volume)
        unvisited_review_areas=cov.unvisited,
        visited_review_areas=cov.visited,
        first_visits=cov.first_visits,
        heatmap_png_b64=None,
        slice_dwell=sd,
        slices_viewed_pct=pct,
        finding_slices_viewed=slices_viewed,
        **met,
    )
    facts_search = FactsSearch(
        lung_coverage_pct=pct,
        unvisited_review_areas=cov.unvisited,
        first_visits=cov.first_visits[:6],
        zoom_used=met["zoom_used"],
        loupe_used=met["loupe_used"],
        slices_viewed_pct=pct,
        finding_slices_viewed=slices_viewed,
    )

    # ---- reveal
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
            dwell_ms=round(slice_ms.get(f.short_id, 0.0), 1),
            slice_range=list(f.slice_range) if f.slice_range else None,
            centroid3=list(f.centroid3) if f.centroid3 else None,
            label_values=list(f.label_values) if f.label_values else ([f.label_value] if f.label_value else None),
            components=f.components,
            measure=f.measure,
            size_verdict=verdicts.get(f.short_id),
        )
        for f in case.findings
    ]
    reveal_marks = []
    for o in outs:
        if o.result not in ("true_positive", "duplicate", "unmatched"):
            continue
        mk = by_mark[o.target]
        v = voxels[mk.mark_id]
        verdict = None
        if mk.mark_id in rasters:
            i = next(k for k, m_ in enumerate(marks) if m_.mark_id == o.target)
            row = {f.short_id: bool(hit[i, j]) for j, f in enumerate(focal)}
            verdict = outline_verdict_for(o.target, o.matched, stats, row, ocfg)
        elif mk.polygon:
            verdict = "off"  # an outline on a non-axial plane is scored by its centroid only
        reveal_marks.append(
            RevealMark(
                mark_id=o.target,
                result=o.result,  # type: ignore[arg-type]
                matched_finding=o.matched,
                zone=o.zone,
                voxel=[round(c, 2) for c in v] if v else None,
                plane=mk.plane or ("axial" if v else None),
                slice=mk.slice if mk.slice is not None else (int(round(v[2])) if v else None),
                polygon=mk.polygon,
                outline_verdict=verdict,  # type: ignore[arg-type]
            )
        )
    wrong = [mk for mk in marks if by_target[mk.mark_id].result == "unmatched" and voxels[mk.mark_id] is not None]
    arrows: list[Arrow] = []
    relations: list[SpatialRelation] = []
    for f in focal:
        o = by_target[f.short_id]
        if o.result not in MISSED:
            continue
        c3 = f.centroid3 or (f.centroid[0], f.centroid[1], float(f.measure.slice if f.measure else nz // 2))
        rng_ = f.slice_range or (int(round(c3[2])), int(round(c3[2])))
        to_xy = (c3[0], c3[1])
        if wrong:
            mk = min(wrong, key=lambda k: _dist2(voxels[k.mark_id], c3, spacing))
            mv_ = voxels[mk.mark_id]
            text, label = relation_text_volume(
                f.label, f.primary_zone, c3, rng_, mark_zones.get(mk.mark_id), mv_, shape
            )
            arrows.append(
                Arrow(
                    from_mark=mk.mark_id,
                    to_finding=f.short_id,
                    text=text,
                    label=label,
                    from_xy=(mv_[0], mv_[1]),
                    to_xy=to_xy,
                )
            )
            relations.append(SpatialRelation(**{"from": mk.mark_id, "to": f.short_id, "text": text}))
        else:
            where = f.relative_location or zone_human(f.primary_zone)
            z0, z1 = rng_
            text = f"The {config.display(f.label).lower()} is in the {where}, on slices {z0 + 1}–{z1 + 1} of {nz}."
            arrows.append(
                Arrow(
                    from_mark=None,
                    to_finding=f.short_id,
                    text=text,
                    label=zone_human(f.primary_zone),
                    from_xy=(nx / 2, ny / 2),
                    to_xy=to_xy,
                )
            )
    for mk in wrong:  # unmatched marks still get a relation to the nearest finding (for the tutor)
        if any(r.from_ == mk.mark_id for r in relations) or not focal:
            continue
        f = min(focal, key=lambda g: _dist2(voxels[mk.mark_id], g.centroid3 or (*g.centroid, 0.0), spacing))
        c3 = f.centroid3 or (f.centroid[0], f.centroid[1], 0.0)
        text, _ = relation_text_volume(
            f.label,
            f.primary_zone,
            c3,
            f.slice_range or (0, nz - 1),
            mark_zones.get(mk.mark_id),
            voxels[mk.mark_id],
            shape,
        )
        relations.append(SpatialRelation(**{"from": mk.mark_id, "to": f.short_id, "text": text}))

    signs = signs_for_case(case, repo)  # after submit only
    for rf in reveal_findings:
        rf.signs = signs.get(rf.finding_id) or None
    reveal = Reveal(
        findings=reveal_findings,
        marks=reveal_marks,
        arrows=arrows,
        search=search,
        ctr=None,
        is_normal=case.is_normal,
        zones_approximate=False,
        maskvol_url=None,  # filled by services.submit (needs the attempt id)
        modality=case.modality,
        provenance=provenance_badge(case),
    )
    card = build_facts_card(
        case, outs, score, success, facts_search, submit.declared_normal, seen_slices=seen_n, near_ms=near, signs=signs
    )
    finding_results = [
        (f.label, 1.0 if by_target[f.short_id].result in ("found", "mislabeled") else 0.0) for f in focal
    ]
    finding_results += [(f.label, 1.0 if by_target[f.short_id].result == "pattern_found" else 0.0) for f in pats]
    search_json = {
        **search.model_dump(exclude={"heatmap_png_b64"}),
        "dwell_by_zone": cov.dwell_by_zone,
        "dwell_by_finding": {k: round(v, 1) for k, v in slice_ms.items()},
        "near_ms_by_finding": {k: round(v, 1) for k, v in near.items()},
        "n_events": len(submit.telemetry),
        "tau_voxels": [slice_window, round(tau_y, 3), round(tau_x, 3)],
        "label_credit": p.label_credit,
        "size_verdicts": {k: v.model_dump() for k, v in verdicts.items()},
    }
    return Evaluation(
        score, success, outs, reveal, card, relations, facts_search, mark_zones, finding_results, search_json, signs
    )


def _dist2(a: tuple[float, float, float] | None, b: tuple[float, float, float], spacing: tuple[float, ...]) -> float:
    if a is None:
        return float("inf")
    sz, sy, sx = spacing
    return ((a[0] - b[0]) * sx) ** 2 + ((a[1] - b[1]) * sy) ** 2 + ((a[2] - b[2]) * sz) ** 2
