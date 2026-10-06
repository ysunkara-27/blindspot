"""Expert review (SPEC §11): queue of debriefs and teaching cards, ratings, CSV export, card write-back."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.app import config, tutor_bridge
from backend.app.db import jload, new_id, now_iso, rows, tx
from backend.app.settings import REPO_ROOT
from shared.contracts import ReviewRating, TeachingCard

router = APIRouter(tags=["review"])
CARD_EDITABLE = {
    "display_name",
    "one_liner",
    "key_signs",
    "where_it_hides",
    "mimics",
    "commonly_confused_with",
    "search_tip",
    "radiopaedia_url",
}
STATUSES = ("ai_draft", "student_reviewed", "radiologist_reviewed")
QUEUE_FILES = (REPO_ROOT / "eval" / "samples" / "review_queue.jsonl", REPO_ROOT / "data" / "review_queue.jsonl")


def _debrief_items(limit: int) -> list[dict[str, Any]]:
    with tx() as con:
        ds = rows(
            con,
            "SELECT d.id, d.attempt_id, d.facts_json, d.output_json, d.source, d.provenance, d.validator_json, "
            "d.created_at, a.case_id, a.marks_json, a.patterns_json, a.declared_normal, "
            "(SELECT COUNT(*) FROM flags f WHERE f.attempt_id = d.attempt_id) AS n_flags, "
            "(SELECT GROUP_CONCAT(comment, ' | ') FROM flags f WHERE f.attempt_id = d.attempt_id) AS flag_comments "
            "FROM debriefs d JOIN attempts a ON a.id = d.attempt_id WHERE d.status='ready' "
            "ORDER BY n_flags DESC, d.created_at DESC LIMIT ?",
            limit,
        )
    items = []
    for f in QUEUE_FILES:  # curated queue written by eval/faithfulness.py (optional)
        if f.exists():
            for line in f.read_text().splitlines():
                if line.strip():
                    d = json.loads(line)
                    items.append({"item_type": "debrief", "origin": "curated", **d})
    for d in ds:
        items.append(
            {
                "item_type": "debrief",
                "origin": "live",
                "item_id": d["id"],
                "attempt_id": d["attempt_id"],
                "case_id": d["case_id"],
                "image_url": f"/api/cases/{d['case_id']}/image",
                "learner": {
                    "marks": jload(d["marks_json"], []),
                    "patterns": jload(d["patterns_json"], []),
                    "declared_normal": bool(d["declared_normal"]),
                },
                "facts": jload(d["facts_json"]),
                "debrief": jload(d["output_json"]),
                "source": d["source"],
                "provenance": d["provenance"],
                "validator": jload(d["validator_json"]),
                "flags": d["n_flags"],
                "flag_comments": d["flag_comments"],
                "created_at": d["created_at"],
            }
        )
    return items[:limit]


@router.get("/review/items")
def items(type: Literal["debrief", "card"] = Query(default="debrief"), limit: int = 50) -> dict:
    if type == "card":
        cards = tutor_bridge.load_cards()
        out = [{"item_type": "card", "item_id": lab, "card": c.model_dump()} for lab, c in sorted(cards.items())]
        return {"type": "card", "n": len(out), "items": out}
    out = _debrief_items(limit)
    return {"type": "debrief", "n": len(out), "items": out}


def _write_card(label: str, rating: ReviewRating) -> None:
    p = config.cards_dir() / f"{label}.yaml"
    if not p.exists():
        raise HTTPException(status_code=404, detail="card not found")
    doc = yaml.safe_load(p.read_text())
    edits = dict(rating.card_edits or {})
    status = edits.pop("status", None)
    bad = set(edits) - CARD_EDITABLE
    if bad:
        raise HTTPException(status_code=422, detail=f"fields not editable: {sorted(bad)}")
    doc.update(edits)
    if status is not None:
        if status not in STATUSES:
            raise HTTPException(status_code=422, detail="invalid review status")
        doc["review"] = {
            "status": status,
            "reviewer": f"{rating.reviewer} ({rating.role})",
            "date": date.today().isoformat(),
            "notes": rating.comment,
        }
    TeachingCard.model_validate(doc)  # never write an invalid card
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


@router.post("/review/ratings")
def ratings(body: ReviewRating) -> dict:
    if body.item_type == "card" and body.card_edits:
        _write_card(body.item_id, body)
    with tx() as con:
        con.execute(
            "INSERT INTO reviews(id, reviewer, role, item_type, item_id, accuracy, teaching, safety_flag, comment, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                new_id(),
                body.reviewer,
                body.role,
                body.item_type,
                body.item_id,
                body.accuracy,
                body.teaching,
                int(body.safety_flag),
                body.comment,
                now_iso(),
            ),
        )
    return {"ok": True}


@router.get("/review/export.csv")
def export_csv() -> Response:
    with tx() as con:
        rs = rows(
            con,
            "SELECT id, reviewer, role, item_type, item_id, accuracy, teaching, safety_flag, comment, "
            "created_at FROM reviews ORDER BY created_at",
        )
    buf = io.StringIO()
    cols = [
        "id",
        "reviewer",
        "role",
        "item_type",
        "item_id",
        "accuracy",
        "teaching",
        "safety_flag",
        "comment",
        "created_at",
    ]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rs:
        w.writerow(r)
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=blindspot_reviews.csv"},
    )
