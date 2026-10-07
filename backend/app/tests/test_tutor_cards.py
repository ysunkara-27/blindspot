"""Teaching cards + zone mimics: schema-valid, complete, safe (no management language, no lobes, no cm)."""

import json
import re

import jsonschema
import pytest
import yaml

from backend.app.tutor import vocab
from backend.app.tutor.cards import (
    all_cards_text,
    cards_block_text,
    content_hash,
    load_cards,
    load_zone_mimics,
    lowest_provenance,
)
from backend.app.tutor.validator import banned_hits, label_mentions

SCHEMA = json.loads((vocab.SCHEMAS_DIR / "teaching_card.json").read_text())
CARD_FILES = sorted(p for p in vocab.CARDS_DIR.glob("*.yaml") if not p.name.startswith("_"))


def _card_texts(c):
    return [c.one_liner, c.search_tip, *c.key_signs, *c.mimics]


def test_one_card_per_label():
    cards = load_cards()
    assert len(CARD_FILES) == len(vocab.labels()) == 18  # 13 X-ray + 5 CT / MR
    assert set(cards) == set(vocab.labels())


@pytest.mark.parametrize("path", CARD_FILES, ids=lambda p: p.stem)
def test_card_matches_json_schema(path):
    jsonschema.validate(yaml.safe_load(path.read_text()), SCHEMA)


@pytest.mark.parametrize("label", sorted(vocab.labels()))
def test_card_content_rules(label):
    c = load_cards()[label]
    assert c.kind == vocab.kind(label)
    assert c.display_name == vocab.display(label)
    assert 3 <= len(c.key_signs) <= 5
    assert c.review.status == "ai_draft"
    modality = vocab.modality_of_label(label)
    zone_ids = set(vocab.volumetric_zone_ids()) if modality != "cxr" else set(vocab.zone_ids())
    assert set(c.where_it_hides) <= zone_ids, "where_it_hides must use config zone ids of the card's modality"
    assert c.where_it_hides
    assert c.mimics
    if modality == "cxr":
        assert set(c.commonly_confused_with) <= vocab.related({label}) - {label}, "only related-group labels"
    else:  # CT / MR: only labels the learner can choose on that modality (no related groups in config yet)
        assert set(c.commonly_confused_with) <= set(vocab.learner_options(modality)) - {label}
        assert re.search(r"\bscroll\w*\b", c.search_tip, re.I) and re.search(r"\bwindow|sequence\b", c.search_tip, re.I)
    assert len(re.findall(r"[.!?](\s|$)", c.search_tip.strip())) == 1, "search_tip is one sentence"
    assert c.radiopaedia_url is None or c.radiopaedia_url.startswith("https://radiopaedia.org/articles/")
    cfg = vocab.validator_cfg()
    for t in _card_texts(c):
        assert not banned_hits(t, cfg), f"banned content in card {label}: {t}"
        assert not re.search(r"\blobes?\b|\blingula", t, re.I), f"cards never name lobes: {t}"
        assert not re.search(r"\b(left|right)\b", c.search_tip, re.I), "search tips are side-neutral"


def test_zone_mimics_cover_every_zone_without_label_words():
    zm = load_zone_mimics()
    assert zm["status"] == "ai_draft"
    assert set(zm["entries"]) == set(vocab.zone_ids())
    cfg = vocab.validator_cfg()
    for z, items in zm["entries"].items():
        assert 2 <= len(items) <= 4, z
        for t in items:
            assert not label_mentions(t), f"zone mimic for {z} names a finding: {t}"
            assert not banned_hits(t, cfg)


def test_lowest_provenance():
    cards = load_cards()
    assert lowest_provenance(["nodule", "cardiomegaly"], cards) == "ai_draft"
    reviewed = {
        k: v.model_copy(update={"review": v.review.model_copy(update={"status": "radiologist_reviewed"})})
        for k, v in cards.items()
    }
    reviewed["nodule"] = reviewed["nodule"].model_copy(
        update={"review": reviewed["nodule"].review.model_copy(update={"status": "student_reviewed"})}
    )
    assert lowest_provenance(["nodule", "mass"], reviewed) == "student_reviewed"
    assert lowest_provenance(["mass"], reviewed) == "radiologist_reviewed"
    assert lowest_provenance([], reviewed) == "ai_draft"


def test_cards_block_is_deterministic_and_complete():
    t = all_cards_text()
    assert t == cards_block_text()
    for label in vocab.labels():
        assert f"## {label} (" in t
    assert "ZONE MIMICS" in t and "OUTPUT FIELD GUIDE" in t
    assert "radiopaedia" not in t.lower() and "ai_draft" not in t, "review metadata stays out of the cached block"
    assert len(t.split()) > 600, "large enough to be worth caching"
    assert content_hash() == content_hash()
