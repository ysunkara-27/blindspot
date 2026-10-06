"""Split construction tests on synthetic Case lists (no images needed)."""

from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from pipeline import splits as sp
from shared.contracts import Case, Finding, Geometry

KINDS = {"cardiomegaly": "pattern", "emphysema": "pattern", "fibrosis": "pattern", "diffuse_nodule": "pattern"}


def mk(cid: str, src: str, labels: list[str], flags: list[str] | None = None, b0: float = 0.0, area=0.01) -> Case:
    fs = [
        Finding(
            finding_id=f"{cid}#F{i}",
            label=lab,
            source_label=lab,
            kind=KINDS.get(lab, "focal"),
            geometry=Geometry(kind="polygon", bbox=(0, 0, 10, 10), mask_path=f"masks/{cid}_F{i}.png"),
            centroid=(5, 5),
            area_frac=area,
        )
        for i, lab in enumerate(labels, start=1)
    ]
    return Case(
        case_id=cid,
        source="synthetic",
        source_split=src,
        split="practice",
        image_path=f"images/{cid}.png",
        width=256,
        height=256,
        is_normal=not labels,
        findings=fs,
        difficulty_prior=b0,
        license_tag="synthetic",
        attribution="synthetic test fixture",
        qa_flags=flags or [],
    )


def synthetic_cases(seed: int = 0) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    n = 0

    def nid(p):
        nonlocal n
        n += 1
        return f"syn_{p}{n:04d}"

    # test split: 30 normals (3 flagged), single-finding cases per label, some multi, some flagged
    for i in range(30):
        cases.append(mk(nid("t"), "test", [], flags=["x"] if i < 3 else None, b0=rng.uniform(-1, 1)))
    for lab in sp.FORM_LABEL_MIX:
        for _ in range(6):
            cases.append(mk(nid("t"), "test", [lab], b0=rng.uniform(-1, 1), area=rng.uniform(1e-4, 0.1)))
    for _ in range(10):
        cases.append(mk(nid("t"), "test", ["effusion", "consolidation"], b0=rng.uniform(-1, 1)))
        cases.append(mk(nid("t"), "test", ["nodule", "cardiomegaly"], b0=rng.uniform(-1, 1)))
        cases.append(mk(nid("t"), "test", ["pneumothorax"], flags=["mask_from_bbox"]))
    # train split
    labs = list(sp.FORM_LABEL_MIX) + ["fibrosis", "emphysema"]
    for i in range(400):
        cases.append(mk(nid("r"), "train", [] if i % 6 == 0 else [rng.choice(labs)], b0=rng.uniform(-1, 1)))
    return cases


@pytest.fixture(scope="module")
def built():
    cases = synthetic_cases()
    splits, info = sp.build(cases)
    return cases, splits, info


def test_splits_disjoint_and_complete(built):
    cases, splits, _ = built
    all_ids = [i for ids in splits.values() for i in ids]
    assert len(all_ids) == len(set(all_ids)) == len(cases)
    names = list(splits)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert not set(splits[a]) & set(splits[b]), (a, b)
    sp.validate_splits(splits, cases)


def test_forms_shape_mix_and_no_flags(built):
    cases, splits, _ = built
    by = {c.case_id: c for c in cases}
    for form in ("assess_A", "assess_B"):
        cs = [by[i] for i in splits[form]]
        assert len(cs) == 20 and sum(c.is_normal for c in cs) == 8
        assert all(not c.qa_flags and c.source_split == "test" for c in cs)
        assert all(sp.preference_tier(c) == 0 for c in cs if not c.is_normal and c.findings[0].kind == "focal")
    mix = lambda f: Counter(sp.primary_label(by[i]) for i in splits[f])  # noqa: E731
    assert mix("assess_A") == mix("assess_B")


def test_test_cases_never_in_practice_and_holdout_is_5pct(built):
    cases, splits, _ = built
    by = {c.case_id: c for c in cases}
    assert all(by[i].source_split == "train" for i in splits["practice"] + splits["holdout"])
    assert all(by[i].source_split == "test" for i in splits["bench"] + splits["assess_A"] + splits["assess_B"])
    n_train = sum(c.source_split == "train" for c in cases)
    assert len(splits["holdout"]) == round(0.05 * n_train)


def test_build_is_deterministic():
    cases = synthetic_cases()
    s1, _ = sp.build(cases)
    s2, _ = sp.build(list(reversed(cases)))
    assert s1 == s2


def test_validate_catches_overlap_and_leak(built):
    cases, splits, _ = built
    bad = {k: v[:] for k, v in splits.items()}
    bad["practice"].append(bad["assess_A"][0])
    with pytest.raises(AssertionError):
        sp.validate_splits(bad, cases)
    bad = {k: v[:] for k, v in splits.items()}
    moved = bad["bench"].pop()
    bad["practice"].append(moved)  # a test case leaking into practice
    with pytest.raises(AssertionError):
        sp.validate_splits(bad, cases)


def test_rebalance_on_b0_within_tolerance(built):
    cases, splits, _ = built
    by = {c.case_id: c for c in cases}
    # make the current forms deliberately unbalanced on b0
    skew = [
        c.model_copy(update={"difficulty_prior": 2.0 if c.case_id in splits["assess_A"] else c.difficulty_prior})
        for c in cases
    ]
    new, info = sp.rebalance(skew, splits)
    sp.validate_splits(new, skew)
    by = {c.case_id: c for c in skew}
    mean = lambda ids: sum(by[i].difficulty_prior for i in ids) / len(ids)  # noqa: E731
    assert abs(mean(new["assess_A"]) - mean(new["assess_B"])) <= sp.B0_TOLERANCE
    assert new["practice"] == splits["practice"] and new["holdout"] == splits["holdout"]


def test_rebalance_requires_b0(built):
    cases, splits, _ = built
    zero = [c.model_copy(update={"difficulty_prior": 0.0}) for c in cases]
    with pytest.raises(SystemExit):
        sp.rebalance(zero, splits)


def test_run_rewrites_split_field_in_place(tmp_path):
    cases = synthetic_cases()
    (tmp_path / "cases.jsonl").write_text("".join(c.model_dump_json() + "\n" for c in cases))
    doc = sp.run(False, out_dir=tmp_path)
    out = [Case.model_validate_json(x) for x in (tmp_path / "cases.jsonl").read_text().splitlines()]
    where = {cid: name for name, ids in doc["splits"].items() for cid in ids}
    assert all(c.split == where[c.case_id] for c in out)
    # every other field untouched
    assert [c.model_copy(update={"split": "practice"}) for c in out] == cases
    saved = json.loads((tmp_path / "splits.json").read_text())
    assert saved["counts"]["assess_A"] == saved["counts"]["assess_B"] == 20


def test_preference_tier_and_salient_primary_label():
    assert sp.preference_tier(mk("a", "test", ["nodule"])) == 0
    assert sp.preference_tier(mk("b", "test", ["nodule", "cardiomegaly"])) == 1
    assert sp.preference_tier(mk("c", "test", ["fracture", "fracture", "fracture"])) == 2
    assert sp.preference_tier(mk("d", "test", ["cardiomegaly"])) == 3
    assert sp.preference_tier(mk("e", "test", ["effusion", "pneumothorax"])) == 4
    assert sp.preference_tier(mk("f", "test", ["effusion", "pneumothorax", "nodule"])) == 5
    assert sp.primary_label(mk("e", "test", ["effusion", "pneumothorax"])) == "pneumothorax"
    assert sp.primary_label(mk("g", "test", ["consolidation", "cardiomegaly"])) == "consolidation"
    assert sp.primary_label(mk("h", "test", [])) is None


def test_busy_cases_never_enter_forms():
    cases = synthetic_cases() + [mk(f"syn_busy{i}", "test", ["pneumothorax", "effusion", "nodule"]) for i in range(20)]
    splits, _ = sp.build(cases)
    assert not any(i.startswith("syn_busy") for f in ("assess_A", "assess_B") for i in splits[f])
