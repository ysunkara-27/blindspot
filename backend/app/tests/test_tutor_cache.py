"""Cache keys (SPEC §8.7): stable under reordering, sensitive to every keyed field."""

from backend.app.tests._tutor_helpers import facts_for
from backend.app.tutor.cache import MemoryStore, SqliteStore, cache_key, cache_key_for_facts
from shared.contracts import Outcome

OUTS = [
    Outcome(target="F2", result="missed_search"),
    Outcome(target="F1", result="found"),
    Outcome(target="M1", result="false_positive", zone="left_mid_zone"),
]


def key(**kw):
    args = dict(
        case_id="cxd_1",
        model="m",
        prompt_version="v1+abc",
        level="MS2",
        outcomes=OUTS,
        fp_zones=["left_mid_zone"],
        unvisited=["retrocardiac", "left_apex"],
    )
    args.update(kw)
    return cache_key(**args)


def test_key_is_stable_under_reordering_and_id_forms():
    k = key()
    assert len(k) == 64 and k == key()
    assert k == key(outcomes=list(reversed(OUTS)), unvisited=["left_apex", "retrocardiac"])
    full = [Outcome(target=f"cxd_1#{o.target}", result=o.result) if o.target.startswith("F") else o for o in OUTS]
    assert k == key(outcomes=full)
    assert k == key(outcomes=[(o.target, o.result) for o in OUTS])
    assert k == key(outcomes=[{"target": o.target, "result": o.result} for o in OUTS])


def test_key_changes_with_each_field():
    k = key()
    variants = [
        key(case_id="cxd_2"),
        key(model="other"),
        key(prompt_version="v2+abc"),
        key(level="MS3"),
        key(outcomes=[Outcome(target="F2", result="missed_decision"), *OUTS[1:]]),
        key(fp_zones=["left_lower_zone"]),
        key(unvisited=["retrocardiac"]),
    ]
    assert len({k, *variants}) == len(variants) + 1


def test_key_for_facts_ignores_unkeyed_fields():
    f, _, _ = facts_for("missed_search")
    k = cache_key_for_facts(f, "m", "v1")
    f.learner.hints_used = 2
    f.learner.time_to_submit_s = 99.0
    assert cache_key_for_facts(f, "m", "v1") == k
    f.search.unvisited_review_areas = []
    assert cache_key_for_facts(f, "m", "v1") != k


def test_stores_roundtrip(tmp_path):
    for store in (MemoryStore(), SqliteStore(tmp_path / "c.sqlite")):
        assert store.get("k") is None
        store.set("k", {"output_json": {"a": 1}, "source": "live"})
        assert store.get("k") == {"output_json": {"a": 1}, "source": "live"}
    assert SqliteStore(tmp_path / "c.sqlite").get("k") is not None  # persisted
