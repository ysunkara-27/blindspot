"""Hint ladder (SPEC §8.8) on scripted telemetry. Deterministic; no LLM."""

from backend.app.tests._tutor_helpers import cases, jitter_events, mark, zone_center, zones
from backend.app.tutor import vocab
from backend.app.tutor.cards import load_cards
from backend.app.tutor.hints import (
    H1_ALL_VISITED,
    H2_NORMAL,
    H2_PATTERN,
    H3_NORMAL,
    dwell_ms,
    hint,
    unvisited_review_areas,
)


def test_h1_lists_every_unvisited_review_area_without_telemetry():
    c = cases()["syn_001"]
    text = hint(1, c, [], [], zones(c.case_id))
    assert text.startswith("You haven't looked at: ")
    for z in vocab.review_area_ids():
        if z in zones(c.case_id):
            assert vocab.zone_human(z) in text


def test_h1_drops_areas_the_learner_dwelt_on():
    c = cases()["syn_001"]
    x, y = zone_center(c.case_id, "right_apex")
    events = jitter_events(x, y, 0, 1000)
    un = unvisited_review_areas(events, zones(c.case_id))
    assert "right_apex" not in un and "left_apex" in un
    assert "right apex" not in hint(1, c, [], events, zones(c.case_id))
    brief = jitter_events(x, y, 0, 150)
    assert "right_apex" in unvisited_review_areas(brief, zones(c.case_id))


def test_h1_all_visited_message():
    c = cases()["syn_001"]
    events, t = [], 0.0
    for z in vocab.review_area_ids():
        if z in zones(c.case_id):
            x, y = zone_center(c.case_id, z)
            events += jitter_events(x, y, t, 600)
            t += 700
    assert hint(1, c, [], events, zones(c.case_id)) == H1_ALL_VISITED


def test_h2_h3_point_at_hardest_unmarked_finding():
    c = cases()["syn_005"]  # F1 mass right upper (difficulty -0.5), F2 nodule left lower (difficulty 0.5)
    z = zones(c.case_id)
    assert hint(2, c, [], [], z) == "Look again at the patient's left side, in the left lower zone."
    assert hint(3, c, [], [], z) == f"Look for this sign: {load_cards()['nodule'].key_signs[0]}."
    on_f2 = [mark("M1", 190, 170, "nodule")]
    assert hint(2, c, on_f2, [], z) == "Look again at the patient's right side, in the right upper zone."


def test_hints_on_normal_and_pattern_cases():
    n = cases()["syn_008"]
    assert hint(2, n, [], [], zones(n.case_id)) == H2_NORMAL
    assert hint(3, n, [], [], zones(n.case_id)) == H3_NORMAL
    p = cases()["syn_007"]
    assert hint(2, p, [], [], zones(p.case_id)) == H2_PATTERN
    assert hint(3, p, [], [], zones(p.case_id)).startswith("Look for this sign: Heart width")


def test_hint_level_is_clamped_and_deterministic():
    c = cases()["syn_002"]
    z = zones(c.case_id)
    assert hint(7, c, [], [], z) == hint(3, c, [], [], z) == hint(3, c, [], [], z)
    assert "patient's left" in hint(2, c, [], [], z)


def test_local_dwell_matches_spec_rules():
    c = cases()["syn_001"]
    region = zones(c.case_id)["right_apex"]
    x, y = zone_center(c.case_id, "right_apex")
    cfg = vocab.scoring_cfg()["dwell"]
    moving = jitter_events(x, y, 0, 990)
    assert 900 <= dwell_ms(moving, region, cfg) <= 1000
    from shared.contracts import TelemetryEvent

    idle = [
        TelemetryEvent(t=i * 33.0, kind="move", x=x, y=y, zoom=1.0, vp=(0, 0, 256, 256), loupe=True) for i in range(200)
    ]  # 6.6 s without moving: capped by max_still_ms
    assert dwell_ms(idle, region, cfg) <= cfg["max_still_ms"] + cfg["max_dt_ms"]
