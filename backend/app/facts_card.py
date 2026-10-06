"""Deterministic facts card (instant, before the Claude debrief). Built only from computed outcomes and
annotation-derived locations. Never centimetres; zone names are the patient's side.

Copy rules (UX audit, round 3):
- findings are listed in id order (F1, F2, F3, ...) whatever their kind, then the learner's extra marks (M1, M2, ...);
- time is said in words ("no time spent there", "about 0.4 s there"), never as "dwell 0 ms";
- an extra mark is "a mark where radiologists marked nothing" (the word "overcall" is not used);
- the score printed here is exactly SubmitResult.score (scores.score_text: one half-up integer everywhere).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from backend.app.config import display, zone_human
from backend.app.scoring.scores import score_text
from backend.app.search.misstype import MISS_COPY
from shared.contracts import Case, FactsCard, FactsSearch, Finding, Outcome

NO_TIME_MS = 100.0  # below this the card says "no time spent there"
FP_LINE = "radiologists marked nothing here"


def _where(f: Finding) -> str:
    return f.relative_location or zone_human(f.primary_zone)


def _id_order(target: str) -> tuple[int, str]:
    m = re.search(r"(\d+)$", target)
    return (int(m.group(1)) if m else 10**9, target)


def _half_up(x: float, decimals: int = 0) -> float:
    q = 10**decimals
    return math.floor(float(x) * q + 0.5) / q


def dwell_text(ms: float | None) -> str:
    """How long the cursor/loupe stayed on a missed finding, in words."""
    ms = float(ms or 0.0)
    if ms < NO_TIME_MS:
        return "no time spent there"
    secs = ms / 1000.0
    if secs < 9.95:
        return f"about {_half_up(secs, 1):.1f} s there"
    return f"about {int(_half_up(secs))} s there"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _label_list(labels: Sequence[str]) -> str:
    """'Nodule, Mass' — or with counts when a label repeats: 'Nodule (5), Pleural effusion (2)'. First-seen order."""
    counts: dict[str, int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    if all(n == 1 for n in counts.values()):
        return ", ".join(display(lab) for lab in counts)
    return ", ".join(f"{display(lab)} ({n})" for lab, n in counts.items())


def extras_text(n_marks: int, n_patterns: int) -> str:
    """'1 mark where radiologists marked nothing' / '2 ticked findings radiologists did not report' / both."""
    parts = []
    if n_marks:
        parts.append(f"{_plural(n_marks, 'mark')} where radiologists marked nothing")
    if n_patterns:
        parts.append(f"{_plural(n_patterns, 'ticked finding')} radiologists did not report")
    return " and ".join(parts)


def build_facts_card(
    case: Case,
    outcomes: Sequence[Outcome],
    score: float,
    success: bool,
    search: FactsSearch,
    declared_normal: bool,
) -> FactsCard:
    by_f = {f.short_id: f for f in case.findings}
    finding_outs = sorted((o for o in outcomes if o.target in by_f), key=lambda o: _id_order(o.target))
    fps = sorted((o for o in outcomes if o.result == "false_positive"), key=lambda o: _id_order(o.target))
    pfalse = [o for o in outcomes if o.result == "pattern_false"]
    extras = extras_text(len(fps), len(pfalse))
    lines: list[str] = []

    if case.is_normal:
        if not extras:
            headline = "Correct: this film is normal" if declared_normal else "Nothing marked on a normal film"
        else:
            headline = f"This film is normal — {extras}"
    else:
        found = sum(o.result in ("found", "mislabeled", "pattern_found") for o in finding_outs)
        total = len(finding_outs)
        if found == total:
            headline = "You found every finding" if total > 1 else "You found it"
        elif found == 0:
            headline = "Missed: " + _label_list([by_f[o.target].label for o in finding_outs])
        else:
            headline = f"You found {found} of {total} findings"
        if declared_normal:
            headline = "This film is not normal — " + headline[0].lower() + headline[1:]
        elif extras:
            headline += f" — plus {extras}"

    for o in finding_outs:
        f = by_f[o.target]
        if f.kind == "pattern":
            extra = ""
            if f.label == "cardiomegaly" and case.cardiothoracic_ratio is not None:
                extra = f" (cardiothoracic ratio {case.cardiothoracic_ratio:.2f}, measured automatically)"
            verb = "Found it" if o.result == "pattern_found" else "Not selected"
            lines.append(f"{o.target} {display(f.label)}{extra}: {verb}.")
            continue
        chip = MISS_COPY.get(o.result, o.result)
        if o.result == "mislabeled":
            chip += f" (you called it {display(o.learner_label or 'not_sure').lower()})"
        elif o.result.startswith("missed_"):
            chip += f" ({dwell_text(o.dwell_ms)})"
        lines.append(f"{o.target} {display(f.label)} — {_where(f)}: {chip}.")
    for o in fps:
        lines.append(f"{o.target} ({zone_human(o.zone) if o.zone else 'outside the lungs'}): {FP_LINE}.")
    for o in pfalse:
        lines.append(f"{display(o.target)}: selected, but radiologists did not report it.")
    if search.unvisited_review_areas:
        lines.append(
            "Review areas you did not visit: " + ", ".join(zone_human(z) for z in search.unvisited_review_areas) + "."
        )
    else:
        lines.append("You visited every review area.")
    lines.append(f"Lung coverage {int(_half_up(search.lung_coverage_pct))}%. Score {score_text(score)}.")
    return FactsCard(headline=headline, lines=lines)
