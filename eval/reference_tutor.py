"""FALLBACK ONLY: minimal SPEC §8.1/§8.3/§8.7 tutor pieces so the faithfulness harness runs end to end before
backend.app.tutor lands. eval.adapters prefers the production modules and labels any use of this file in
ENGINE_STATUS; live faithfulness runs refuse to use it (condition G must be the production pipeline).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from eval import checks, render
from eval.adapters import display, repo_for, zone_human
from eval.common import REPO_ROOT
from shared.contracts import (
    AttemptSubmit,
    Case,
    DebriefFacts,
    DebriefOutput,
    FactsCase,
    FactsFinding,
    FactsLearner,
    FactsMark,
    FactsPattern,
    FactsSearch,
    Outcome,
)

MISSED = {"missed_search", "missed_recognition", "missed_decision"}


def spec_system_prompt() -> str:
    """The v1 debrief system prompt quoted in docs/SPEC.md §8.3 (first fenced block after the heading)."""
    spec = (REPO_ROOT / "docs" / "SPEC.md").read_text()
    sec = spec.split("### 8.3", 1)[1]
    m = re.search(r"```\n(.*?)```", sec, re.S)
    return m.group(1).strip() if m else "You write the debrief for Blindspot."


def load_cards() -> dict[str, dict[str, Any]]:
    d = REPO_ROOT / "content" / "teaching_cards"
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(d.glob("*.yaml")) if d.exists() else []:
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if isinstance(c, dict) and c.get("label"):
            out[c["label"]] = c
    return out


def _difficulty(v: float | None) -> str | None:
    if v is None:
        return None
    return "hard" if v > 0.3 else ("easy" if v < -0.3 else "moderate")


def _size(area_frac: float) -> str:
    word = "small" if area_frac < 0.005 else ("medium" if area_frac < 0.03 else "large")
    return f"{word} (about {100 * area_frac:.2g}% of the image)"


def build_facts(
    *,
    case: Case,
    submit: AttemptSubmit,
    outcomes: list[Outcome],
    spatial_relations: list[Any],
    search: FactsSearch,
    mark_zones: dict[str, str | None],
    level: str,
    history: dict[str, Any],
) -> DebriefFacts:
    findings = [
        FactsFinding(
            id=f.short_id,
            label=f.label,
            display=display(f.label),
            kind=f.kind,
            side=f.side,
            primary_zone=f.primary_zone,
            zones=list(f.zones),
            relative_location=f.relative_location,
            size=_size(f.area_frac) if f.kind == "focal" else None,
            difficulty=_difficulty(f.difficulty),
            zones_approximate=case.zones_approximate,
            ctr=case.cardiothoracic_ratio if f.label == "cardiomegaly" else None,
        )
        for f in case.findings
    ]
    t_end = submit.telemetry[-1].t / 1000.0 if submit.telemetry else 0.0
    learner = FactsLearner(
        level=level,
        declared_normal=submit.declared_normal,
        normal_confidence=submit.normal_confidence,
        hints_used=submit.hints_used,
        time_to_submit_s=round(t_end, 1),
        marks=[
            FactsMark(id=m.mark_id, label=m.label, confidence=m.confidence, zone=mark_zones.get(m.mark_id))
            for m in submit.marks
        ],
        pattern_selections=[FactsPattern(label=p.label, confidence=p.confidence) for p in submit.patterns],
    )
    labels = {f.label for f in case.findings} | {m.label for m in submit.marks if m.label != "not_sure"}
    return DebriefFacts(
        case=FactsCase(
            case_id=case.case_id,
            is_normal=case.is_normal,
            projection="frontal; PA vs AP not recorded",
            pixel_spacing_mm=case.pixel_spacing_mm,
            findings=findings,
        ),
        learner=learner,
        outcomes=list(outcomes),
        spatial_relations=list(spatial_relations),
        search=search,
        history=history,
        teaching_cards=sorted(labels),
    )


def verdict_for(facts: DebriefFacts) -> str:
    res = {o.target: o.result for o in facts.outcomes}
    fps = [o for o in facts.outcomes if o.result == "false_positive"]
    if facts.case.is_normal:
        return "correct_normal" if not fps and not facts.learner.marks else "overcall"
    if facts.learner.declared_normal:
        return "missed_normal_call"
    fres = [res.get(f.id) for f in facts.case.findings]
    good = sum(r in ("found", "pattern_found") for r in fres)
    if good == len(fres):
        return "all_found"
    if good == 0 and not any(r == "mislabeled" for r in fres):
        return "missed"
    return "partly_found"


WHY = {
    "found": "You found it and named it correctly.",
    "mislabeled": "You found the right spot but chose a different label.",
    "missed_search": "Your search never paused in this region.",
    "missed_recognition": "Your cursor passed over this region only briefly.",
    "missed_decision": "You looked here at length but judged it normal.",
    "pattern_found": "You reported this global finding.",
    "pattern_missed": "This global finding was not selected.",
}


def template_debrief(facts: DebriefFacts, cards: dict[str, Any] | None = None) -> DebriefOutput:
    cards = cards or {}
    res = {o.target: o for o in facts.outcomes}
    findings = []
    for f in facts.case.findings:
        o = res.get(f.id)
        result = o.result if o else ("pattern_missed" if f.kind == "pattern" else "missed_search")
        card = cards.get(f.label) or {}
        signs = list((card.get("key_signs") if isinstance(card, dict) else getattr(card, "key_signs", [])) or [])
        where = f.relative_location or zone_human(f.primary_zone) if f.kind == "focal" else "the whole chest"
        findings.append(
            {
                "finding_id": f.id,
                "result": result,
                "where_to_look": where,
                "what_it_looks_like": signs[:2] or [f"See the outlined {f.display.lower()}."],
                "why": WHY.get(result, ""),
            }
        )
    overcalls = [
        {
            "mark_id": o.target,
            "explanation": f"Radiologists marked nothing at your mark in the {zone_human(o.zone)}.",
            "possible_mimics": [],
        }
        for o in facts.outcomes
        if o.result == "false_positive"
    ]
    unv = [zone_human(z) for z in facts.search.unvisited_review_areas[:3]]
    out = {
        "headline": {
            "all_found": "Everything found.",
            "correct_normal": "Correct: this film is normal.",
            "overcall": "Nothing was there to mark.",
            "missed": "This one was missed.",
            "partly_found": "Partly found.",
            "missed_normal_call": "This film was not normal.",
        }[verdict_for(facts)],
        "verdict": verdict_for(facts),
        "findings": findings,
        "overcalls": overcalls,
        "search_coaching": ("Areas you did not visit: " + ", ".join(unv) + ".")
        if unv
        else "You visited every review area.",
        "calibration_note": "",
        "next_step": "Try another case.",
        "fact_ids": [f.id for f in facts.case.findings] + [o["mark_id"] for o in overcalls],
    }
    return DebriefOutput.model_validate(out)


def cards_text(cards: dict[str, Any]) -> str:
    if not cards:
        return "TEACHING CARDS: (none available)"
    return "TEACHING CARDS:\n" + json.dumps(
        {k: (v if isinstance(v, dict) else v.model_dump()) for k, v in sorted(cards.items())},
        sort_keys=True,
        ensure_ascii=False,
    )


def g_images(case: Case, data_root: Path, submit: AttemptSubmit, facts: DebriefFacts) -> list[tuple[dict, str]]:
    """SPEC §8.2: full image with outlines + marks; clean crop and outlined crop around the primary miss."""
    repo = repo_for(data_root)
    gray = render.load_gray(data_root, case)
    full = render.draw_marks(render.draw_outlines(render.to_rgb(gray), case, repo), list(submit.marks))
    res = {o.target: o.result for o in facts.outcomes}
    focal = [f for f in case.findings if f.kind == "focal"]
    target = next((f for f in focal if res.get(f.short_id) in MISSED | {"mislabeled"}), focal[0] if focal else None)
    blocks = [render.image_block(full)]
    if target is not None:
        size = max(64, case.width // 2)
        cx, cy = target.centroid
        blocks.append(render.image_block(render.crop(render.to_rgb(gray), cx, cy, size)))
        outl = render.draw_outlines(render.to_rgb(gray), case, repo, [target])
        blocks.append(render.image_block(render.crop(outl, cx, cy, size)))
    return blocks


def generate_debrief(
    facts: DebriefFacts,
    case: Case,
    submit: AttemptSubmit,
    *,
    client: Any,
    data_root: Path,
    model: str,
    cards: dict[str, Any],
) -> dict[str, Any]:
    schema = json.loads(checks.load_schema_path().read_text())
    schema = {k: v for k, v in schema.items() if not k.startswith("$") and k not in ("title", "description")}
    system = [
        {"type": "text", "text": spec_system_prompt()},
        {"type": "text", "text": cards_text(cards), "cache_control": {"type": "ephemeral"}},
    ]
    content: list[dict[str, Any]] = [b for b, _ in g_images(case, data_root, submit, facts)]
    content.append({"type": "text", "text": "FACTS:\n" + facts.model_dump_json(by_alias=True)})
    kwargs = {
        "model": model,
        "max_tokens": 1200,
        "system": system,
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    first_v: dict[str, Any] | None = None
    for attempt in range(2):
        resp = client.messages.create(messages=[{"role": "user", "content": content}], **kwargs)
        text = next((b.text for b in resp.content if b.type == "text"), None)
        try:
            out = DebriefOutput.model_validate(json.loads(text or ""))
        except Exception:  # noqa: BLE001 — a malformed response counts as a validator failure
            out = None
        v = checks.validate(out.model_dump(), facts, cards) if out else {"ok": False, "errors": ["unparseable"]}
        first_v = first_v or v
        if out is not None and v["ok"]:
            return {
                "debrief": out,
                "source": "live",
                "validator": {"first": first_v, "final": v, "regenerated": attempt == 1},
            }
        content = content + [{"type": "text", "text": "Fix these problems: " + "; ".join(v["errors"][:8])}]
    tmpl = template_debrief(facts, cards)
    return {"debrief": tmpl, "source": "template", "validator": {"first": first_v, "final": None, "regenerated": True}}
