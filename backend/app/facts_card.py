"""Deterministic facts card (instant, before the Claude debrief). Built only from computed outcomes and
annotation-derived locations. Never centimetres; zone names are the patient's side."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.config import display, zone_human
from backend.app.search.misstype import MISS_COPY
from shared.contracts import Case, FactsCard, FactsSearch, Outcome


def _where(case: Case, fid: str) -> str:
    f = next((x for x in case.findings if x.short_id == fid), None)
    if f is None:
        return ""
    return f.relative_location or zone_human(f.primary_zone)


def build_facts_card(
    case: Case,
    outcomes: Sequence[Outcome],
    score: float,
    success: bool,
    search: FactsSearch,
    declared_normal: bool,
) -> FactsCard:
    by_f = {f.short_id: f for f in case.findings}
    focal = [o for o in outcomes if o.target in by_f and by_f[o.target].kind == "focal"]
    pats = [o for o in outcomes if o.result in ("pattern_found", "pattern_missed")]
    fps = [o for o in outcomes if o.result == "false_positive"]
    pfalse = [o for o in outcomes if o.result == "pattern_false"]
    lines: list[str] = []

    if case.is_normal:
        if not fps and not pfalse:
            headline = "Correct: this film is normal" if declared_normal else "No false alarms on a normal film"
        else:
            n = len(fps) + len(pfalse)
            headline = f"This film is normal — {n} false alarm{'s' if n != 1 else ''}"
    else:
        found = sum(o.result in ("found", "mislabeled") for o in focal) + sum(o.result == "pattern_found" for o in pats)
        total = len(focal) + len(pats)
        if found == total:
            headline = "You found every finding" if total > 1 else "You found it"
        elif found == 0:
            headline = "Missed: " + ", ".join(display(by_f[o.target].label) for o in focal + pats)
        else:
            headline = f"You found {found} of {total} findings"
        if declared_normal:
            headline = "This film is not normal — " + headline[0].lower() + headline[1:]

    for o in focal:
        f = by_f[o.target]
        where = _where(case, o.target)
        chip = MISS_COPY.get(o.result, o.result)
        if o.result == "mislabeled":
            chip += f" (you called it {display(o.learner_label or 'not_sure').lower()})"
        dwell = f"; dwell {int(round(o.dwell_ms or 0))} ms" if o.result.startswith("missed_") else ""
        lines.append(f"{o.target} {display(f.label)} — {where}: {chip}{dwell}.")
    for o in pats:
        f = by_f[o.target]
        extra = ""
        if f.label == "cardiomegaly" and case.cardiothoracic_ratio is not None:
            extra = f" (cardiothoracic ratio {case.cardiothoracic_ratio:.2f}, measured automatically)"
        verb = "Found it" if o.result == "pattern_found" else "Not selected"
        lines.append(f"{o.target} {display(f.label)}{extra}: {verb}.")
    for o in fps:
        lines.append(
            f"{o.target} ({zone_human(o.zone) if o.zone else 'outside the lungs'}): {MISS_COPY['false_positive']}."
        )
    for o in pfalse:
        lines.append(f"{display(o.target)}: selected, but radiologists did not report it.")
    if search.unvisited_review_areas:
        lines.append(
            "Review areas you did not visit: " + ", ".join(zone_human(z) for z in search.unvisited_review_areas) + "."
        )
    else:
        lines.append("You visited every review area.")
    lines.append(f"Lung coverage {search.lung_coverage_pct:.0f}%. Score {score:.0f}.")
    return FactsCard(headline=headline, lines=lines)
