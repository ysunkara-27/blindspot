"""Hint ladder (SPEC §8.8) on scripted telemetry. Deterministic; no LLM.

Wording must not reveal whether a film is normal (QA gate W1 issue 8): same template per level for all films."""

import re

from backend.app.tests._tutor_helpers import cases, jitter_events, mark, zone_center, zones
from backend.app.tutor import vocab
from backend.app.tutor.cards import load_cards, load_zone_mimics
from backend.app.tutor.hints import (
    COMPARE_MIDLINE,
    COMPARE_SIDES,
    H1_ALL_VISITED,
    dwell_ms,
    h2_text,
    hint,
    hint_zones,
    unvisited_review_areas,
    zone_dwell,
)
from backend.app.tutor.validator import label_mentions


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


# One template per level, for every film (normal or abnormal).
H1_RE = re.compile(
    r"^(?:You haven't looked at: [a-z ,()]+\.|Compare each region with the same region on the other side\.)$"
)
H2_RE = re.compile(r"^Look again at the (?:patient's (?:right|left) side, in the )?[a-z ()]+\.$")
H3_RE = re.compile(
    r"^In the [a-z ()]+, check for this sign: [^A-Z].+\. [A-Z].+ can look similar; "
    rf"(?:{COMPARE_SIDES}|{COMPARE_MIDLINE})\.$"
)
SHAPE = {1: H1_RE, 2: H2_RE, 3: H3_RE}


def _first_words(text: str, n: int = 3) -> list[str]:
    return text.split()[:n]


def _scan_events(case_id: str, skip: tuple[str, ...] = (), ms: float = 600) -> list:
    events, t = [], 0.0
    for z in vocab.zone_ids():
        if z in zones(case_id) and z not in skip:
            x, y = zone_center(case_id, z)
            events += jitter_events(x, y, t, ms)
            t += ms + 100
    return events


def test_h1_h2_h3_have_the_same_shape_for_normal_and_abnormal_films():
    """QA W1 issue 8: the wording alone must not reveal normal vs abnormal."""
    abnormal = ["syn_001", "syn_002", "syn_005", "syn_006", "syn_007"]
    normal = ["syn_008", "syn_009", "syn_010"]
    for telemetry_case in (None, "scan"):
        texts: dict[int, dict[str, list[str]]] = {1: {"n": [], "a": []}, 2: {"n": [], "a": []}, 3: {"n": [], "a": []}}
        for group, ids in (("n", normal), ("a", abnormal)):
            for cid in ids:
                c = cases()[cid]
                ev = [] if telemetry_case is None else _scan_events(cid, skip=("left_apex", "retrocardiac"))
                for level in (1, 2, 3):
                    t = hint(level, c, [], ev, zones(cid))
                    assert SHAPE[level].match(t), (cid, level, t)
                    texts[level][group].append(t)
        for level in (1, 2, 3):
            n_open = {tuple(_first_words(t)) for t in texts[level]["n"]}
            a_open = {tuple(_first_words(t)) for t in texts[level]["a"]}
            assert n_open & a_open, (level, n_open, a_open)  # same opening words exist in both groups
            if level == 3:
                assert {t.split(",")[0].split()[0] for t in texts[3]["n"] + texts[3]["a"]} == {"In"}
    # the strings that used to give the class away are gone
    for cid in normal:
        for level in (2, 3):
            t = hint(level, cases()[cid], [], [], zones(cid))
            assert "normal is a valid call" not in t and "Asymmetry is the clue" not in t


def test_h2_h3_point_at_hardest_unmarked_finding():
    c = cases()["syn_005"]  # F1 mass right upper (difficulty -0.5), F2 nodule left lower (difficulty 0.5)
    z = zones(c.case_id)
    assert hint(2, c, [], [], z) == "Look again at the patient's left side, in the left lower zone."
    mimic = load_zone_mimics()["entries"]["left_lower_zone"][0]
    assert hint(3, c, [], [], z) == (
        "In the left lower zone, check for this sign: a round or oval white spot surrounded by normal lung. "
        f"{mimic} can look similar; compare with the same area on the other side."
    )
    assert load_cards()["nodule"].key_signs[0].lower().startswith("a round or oval white spot")
    on_f2 = [mark("M1", 190, 170, "nodule")]
    assert hint(2, c, on_f2, [], z) == "Look again at the patient's right side, in the right upper zone."


def test_normal_film_h2_is_a_search_cue_least_dwelt_zone():
    n = cases()["syn_008"]
    z = zones(n.case_id)
    ev = _scan_events(n.case_id)
    h2 = hint(2, n, [], ev, z)
    dwell = zone_dwell(ev, z)
    cands = [h for h in hint_zones(load_cards()) if h in z]
    named = next(h for h in cands if h2 == h2_text(h))
    assert dwell.get(named, 0.0) == min(dwell.get(h, 0.0) for h in cands)
    # after the learner dwells there, H2 moves on: driven by the search, not by the answer
    x, y = zone_center(n.case_id, named)
    ev2 = ev + jitter_events(x, y, ev[-1].t + 50, 4000)
    assert hint(2, n, [], ev2, z) != h2
    # ties (no telemetry) are broken per case, so normal films do not all name the same area
    names = {hint(2, cases()[cid], [], [], zones(cid)) for cid in ("syn_008", "syn_009", "syn_010")}
    assert len(names) > 1


def test_h3_stays_in_the_zone_h2_named_when_previous_hints_are_passed():
    n = cases()["syn_008"]
    z = zones(n.case_id)
    ev = _scan_events(n.case_id)
    h1, h2 = hint(1, n, [], ev, z), hint(2, n, [], ev, z)
    zone = next(h for h in vocab.zone_ids() if h2_text(h) == h2)
    x, y = zone_center(n.case_id, zone)
    ev2 = ev + jitter_events(x, y, ev[-1].t + 50, 4000)  # the learner obeys H2
    want = f"In the {vocab.zone_human(zone)}, check for this sign: "
    assert hint(3, n, [], ev2, z, previous=[h1, h2]).startswith(want)
    log = [{"level": 1, "at": "t1", "text": h1}, {"level": 2, "at": "t2", "text": h2}]  # backend hint-log rows
    assert hint(3, n, [], ev2, z, previous=log).startswith(want)


def test_all_marked_abnormal_film_gets_the_same_search_cue_as_a_normal_film():
    c = cases()["syn_005"]
    z = zones(c.case_id)
    both = [mark("M1", 190, 170, "nodule"), mark("M2", 80, 95, "mass")]
    for level in (2, 3):
        t = hint(level, c, both, [], z)
        assert SHAPE[level].match(t), t
        assert "Your marks" not in t and "every focal finding" not in t


def test_pattern_case_points_at_the_pattern_zone_in_the_same_shape():
    p = cases()["syn_007"]
    z = zones(p.case_id)
    assert hint(2, p, [], [], z) == "Look again at the cardiac silhouette."
    h3 = hint(3, p, [], [], z)
    assert SHAPE[3].match(h3) and "check for this sign: heart width" in h3 and h3.endswith(COMPARE_MIDLINE + ".")


def test_hints_never_name_a_label_or_finding_id():
    for cid, c in cases().items():
        for level in (1, 2, 3):
            t = hint(level, c, [], [], zones(cid))
            assert not re.search(r"\bF\d+\b|#F", t), (cid, t)
            if level < 3 or c.is_normal:
                assert label_mentions(t) == [], (cid, level, t)


def test_hint_level_is_clamped_and_deterministic():
    c = cases()["syn_002"]
    z = zones(c.case_id)
    assert hint(7, c, [], [], z) == hint(3, c, [], [], z) == hint(3, c, [], [], z)
    assert "patient's left" in hint(2, c, [], [], z)
    n = cases()["syn_009"]
    assert hint(2, n, [], [], zones(n.case_id)) == hint(2, n, [], [], zones(n.case_id))


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
