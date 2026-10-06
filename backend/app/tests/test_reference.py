"""Reference bank (round 3, item 4): bench-only selection, runtime refusals, endpoint shape.

Synthetic fixtures only. Bench cases are evaluation-only and never served to learners, which is why their outlines
may be shown; these tests pin that no practice/assessment/holdout case can reach the reference endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.app.settings import REPO_ROOT
from backend.app.tests.conftest import FIXTURES
from pipeline import reference_bank as rb
from shared.contracts import Case

LABEL_KEYS = {
    "label",
    "display",
    "kind",
    "one_liner",
    "key_signs",
    "mimics",
    "commonly_confused_with",
    "search_tip",
    "radiopaedia_url",
    "review_status",
    "examples",
}
EXAMPLE_KEYS = {"case_id", "image_url", "width", "height", "finding"}
FINDING_KEYS = {"finding_id", "polygon", "bbox", "relative_location", "side"}
NORMAL_KEYS = {"case_id", "image_url", "width", "height"}
REAL_CARDS = REPO_ROOT / "content" / "teaching_cards"
REAL_CASES = REPO_ROOT / "data" / "processed" / "cases.jsonl"
COMMITTED_BANK = REPO_ROOT / "config" / "reference_bank.yaml"
NON_BENCH = {"practice", "assess_A", "assess_B", "holdout"}


def rewrite(root: Path, **changes: dict) -> None:
    """Edit fixture cases in place: rewrite(root, syn_001={"split": "bench", "qa_flags": []})."""
    p = root / "cases.jsonl"
    out = []
    for line in p.read_text().splitlines():
        c = json.loads(line)
        c.update(changes.get(c["case_id"], {}))
        out.append(json.dumps(c))
    p.write_text("\n".join(out) + "\n")


def fixture_cases(**changes: dict) -> list[Case]:
    cases = []
    for line in (FIXTURES / "cases.jsonl").read_text().splitlines():
        c = json.loads(line)
        c.update(changes.get(c["case_id"], {}))
        cases.append(Case.model_validate(c))
    return cases


BENCH = {"split": "bench", "qa_flags": []}
LABELS = [("nodule", "focal"), ("effusion", "focal"), ("mass", "focal"), ("cardiomegaly", "pattern")]


# ------------------------------------------------------------------ selection (pure)
def test_selection_uses_only_unflagged_bench_cases():
    cases = fixture_cases(
        syn_001=BENCH,  # nodule, single finding
        syn_005=BENCH,  # mass + nodule
        syn_003={"split": "bench"},  # effusion, bench but still qa-flagged ("synthetic") -> never chosen
        syn_006={"split": "assess_A", "qa_flags": []},  # effusion, not bench -> never chosen
        syn_007={"split": "holdout", "qa_flags": []},  # cardiomegaly, not bench -> never chosen
        syn_008=BENCH,
        syn_009={"split": "bench", "qa_flags": ["orientation_suspect"]},
    )
    bank = rb.select_bank(cases, LABELS)
    by_id = {c.case_id: c for c in cases}
    picked = [e["case_id"] for es in bank["labels"].values() for e in es] + [e["case_id"] for e in bank["normal"]]
    assert picked, "expected some picks"
    for cid in picked:
        assert by_id[cid].split == "bench" and by_id[cid].qa_flags == [], cid
    assert bank["labels"]["effusion"] == [] and bank["labels"]["cardiomegaly"] == []
    assert bank["labels"]["mass"] == [{"case_id": "syn_005", "finding_id": "syn_005#F1"}]
    # single-finding case preferred; syn_005 is already used for mass so it is only a fallback for nodule
    assert bank["labels"]["nodule"][0] == {"case_id": "syn_001", "finding_id": "syn_001#F1"}
    assert bank["normal"] == [{"case_id": "syn_008"}]
    assert list(bank["labels"]) == [lab for lab, _ in LABELS]  # taxonomy order kept


def test_selection_ranks_single_finding_then_area_then_contrast():
    base = fixture_cases(syn_001=BENCH, syn_005=BENCH)
    one = next(c for c in base if c.case_id == "syn_001")
    two = next(c for c in base if c.case_id == "syn_005")

    def clone(case: Case, cid: str, area: float, contrast: float | None) -> Case:
        fs = [
            f.model_copy(
                update={"finding_id": f.finding_id.replace(case.case_id, cid), "area_frac": area, "contrast": contrast}
            )
            for f in case.findings
        ]
        return case.model_copy(update={"case_id": cid, "findings": fs})

    cases = [
        clone(two, "multi_big", 0.5, 0.9),  # largest, but shares the film with another finding
        clone(one, "single_small", 0.001, 0.9),
        clone(one, "single_big_low", 0.01, 0.1),
        clone(one, "single_big_high", 0.01, 0.8),
    ]
    order = [c.case_id for c, _ in rb.candidates(cases, "nodule", "focal")]
    assert order == ["single_big_high", "single_big_low", "single_small", "multi_big"]
    assert rb.select_bank(cases, [("nodule", "focal")], per_label=3)["labels"]["nodule"] == [
        {"case_id": "single_big_high", "finding_id": "single_big_high#F1"},
        {"case_id": "single_big_low", "finding_id": "single_big_low#F1"},
        {"case_id": "single_small", "finding_id": "single_small#F1"},
    ]


def test_normals_need_a_known_ctr_below_half():
    cases = fixture_cases(
        syn_008=BENCH,
        syn_009={**BENCH, "cardiothoracic_ratio": 0.55},
        syn_010={**BENCH, "cardiothoracic_ratio": None},
    )
    assert [c.case_id for c in rb.normal_candidates(cases)] == ["syn_008"]


def test_cli_writes_reviewable_yaml(processed_copy, tmp_path):
    rewrite(processed_copy, syn_001=BENCH, syn_007=BENCH, syn_008=BENCH)
    out = tmp_path / "bank.yaml"
    assert rb.main(["--processed", str(processed_copy), "--out", str(out)]) == 0
    text = out.read_text()
    assert text.startswith("#") and "BENCH" in text and "GENERATED" in text
    doc = yaml.safe_load(text)
    assert doc["version"] == 1 and doc["split"] == "bench"
    assert len(doc["labels"]) == 13
    assert doc["labels"]["nodule"] == [{"case_id": "syn_001", "finding_id": "syn_001#F1"}]
    assert doc["labels"]["cardiomegaly"] == [{"case_id": "syn_007", "finding_id": "syn_007#F1"}]
    assert doc["normal"] == [{"case_id": "syn_008"}]


# ------------------------------------------------------------------ endpoints
@pytest.fixture
def ref_env(api_env, processed_copy, tmp_path, monkeypatch):
    """Client on a fixture copy where syn_001 (nodule), syn_007 (cardiomegaly) and syn_008 (normal) are bench cases;
    everything else stays in practice (syn_005 is moved to assess_A)."""

    def _make(bank: dict | str | None, cards: bool = True):
        rewrite(processed_copy, syn_001={"split": "bench"}, syn_007={"split": "bench"}, syn_008={"split": "bench"})
        rewrite(processed_copy, syn_005={"split": "assess_A"})
        c = api_env(processed_copy)
        if cards:
            monkeypatch.setenv("BLINDSPOT_CARDS_DIR", str(REAL_CARDS))
        p = tmp_path / "reference_bank.yaml"
        if bank is not None:
            p.write_text(bank if isinstance(bank, str) else yaml.safe_dump(bank))
        monkeypatch.setenv("BLINDSPOT_REFERENCE_BANK", str(p))
        return c

    return _make


GOOD_BANK = {
    "version": 1,
    "split": "bench",
    "labels": {
        "nodule": [{"case_id": "syn_001", "finding_id": "syn_001#F1"}],
        "cardiomegaly": [{"case_id": "syn_007", "finding_id": "syn_007#F1"}],
    },
    "normal": [{"case_id": "syn_008"}],
}


def test_reference_shape_matches_contract(ref_env):
    c = ref_env(GOOD_BANK)
    r = c.get("/api/reference")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"labels", "normal_examples"}
    from backend.app import config

    assert [e["label"] for e in body["labels"]] == list(config.labels())  # all 13, taxonomy order
    assert len(body["labels"]) == 13
    for e in body["labels"]:
        assert set(e) == LABEL_KEYS, e["label"]
        assert e["display"] == config.display(e["label"]) and e["kind"] in ("focal", "pattern")
        assert e["one_liner"] and e["key_signs"] and e["search_tip"], e["label"]  # real card text
        assert e["review_status"] in ("ai_draft", "student_reviewed", "radiologist_reviewed")
        assert all(lab in config.labels() for lab in e["commonly_confused_with"])
        assert len(e["examples"]) <= 3
        for ex in e["examples"]:
            assert set(ex) == EXAMPLE_KEYS and set(ex["finding"]) == FINDING_KEYS
    by = {e["label"]: e for e in body["labels"]}
    (ex,) = by["nodule"]["examples"]
    assert ex["case_id"] == "syn_001" and ex["image_url"] == "/api/cases/syn_001/image"
    assert (ex["width"], ex["height"]) == (256, 256)
    assert ex["finding"]["finding_id"] == "F1" and "#" not in json.dumps(body)  # short ids only
    assert len(ex["finding"]["bbox"]) == 4
    assert ex["finding"]["polygon"] is None or all(len(p) == 2 for p in ex["finding"]["polygon"])
    assert ex["finding"]["side"] in ("right", "left", "bilateral", "midline", None)
    assert by["cardiomegaly"]["kind"] == "pattern" and by["cardiomegaly"]["examples"][0]["case_id"] == "syn_007"
    assert by["effusion"]["examples"] == []
    assert body["normal_examples"] == [
        {"case_id": "syn_008", "image_url": "/api/cases/syn_008/image", "width": 256, "height": 256}
    ]
    assert set(body["normal_examples"][0]) == NORMAL_KEYS
    assert c.get(ex["image_url"]).status_code == 200  # the example film is actually servable


def test_reference_label_endpoint(ref_env):
    c = ref_env(GOOD_BANK)
    one = c.get("/api/reference/nodule")
    assert one.status_code == 200, one.text
    assert one.json() == next(e for e in c.get("/api/reference").json()["labels"] if e["label"] == "nodule")
    assert set(one.json()) == LABEL_KEYS
    for bad in ("not_a_label", "normal", "not_sure"):
        assert c.get(f"/api/reference/{bad}").status_code == 404, bad


def test_non_bench_cases_are_refused_even_if_listed(ref_env):
    """Defence in depth: a hand-edited YAML pointing at a practice or assessment case must not expose its outline."""
    bank = {
        "labels": {
            "nodule": [
                {"case_id": "syn_005", "finding_id": "syn_005#F2"},  # assess_A
                {"case_id": "syn_001", "finding_id": "syn_001#F1"},  # bench: kept
            ],
            "pneumothorax": [{"case_id": "syn_002", "finding_id": "syn_002#F1"}],  # practice
            "effusion": [{"case_id": "syn_003", "finding_id": "syn_003#F1"}],  # practice
        },
        "normal": [{"case_id": "syn_009"}, {"case_id": "syn_008"}],  # syn_009 is practice
    }
    c = ref_env(bank)
    body = c.get("/api/reference").json()
    by = {e["label"]: e for e in body["labels"]}
    assert [ex["case_id"] for ex in by["nodule"]["examples"]] == ["syn_001"]
    assert by["pneumothorax"]["examples"] == [] and by["effusion"]["examples"] == []
    assert [n["case_id"] for n in body["normal_examples"]] == ["syn_008"]
    text = json.dumps(body)
    for cid in ("syn_002", "syn_003", "syn_005", "syn_009"):
        assert cid not in text, cid
    assert c.get("/api/reference/pneumothorax").json()["examples"] == []


def test_missing_cases_wrong_findings_and_missing_images_are_skipped(ref_env, processed_copy):
    bank = {
        "labels": {
            "nodule": [
                {"case_id": "cxd_not_in_bundle", "finding_id": "cxd_not_in_bundle#F1"},  # hosted bundle lacks it
                {"case_id": "syn_001", "finding_id": "syn_001#F9"},  # no such finding
                {"case_id": "syn_007", "finding_id": "syn_007#F1"},  # bench, but that finding is cardiomegaly
                {"finding_id": "syn_001#F1"},  # malformed entry
                "syn_001",  # malformed entry
                {"case_id": "syn_001", "finding_id": "syn_001#F1"},
                {"case_id": "syn_001", "finding_id": "syn_001#F1"},  # duplicate case
            ],
            "cardiomegaly": [{"case_id": "syn_007", "finding_id": "syn_007#F1"}],
            "mass": "not a list",
        },
        "normal": [{"case_id": "syn_001"}, {"case_id": "nope"}, {"case_id": "syn_008"}],  # syn_001 is not normal
    }
    c = ref_env(bank)
    (processed_copy / "images" / "syn_007.png").unlink()  # image missing from the bundle
    r = c.get("/api/reference")
    assert r.status_code == 200, r.text
    by = {e["label"]: e for e in r.json()["labels"]}
    assert [ex["case_id"] for ex in by["nodule"]["examples"]] == ["syn_001"]
    assert by["cardiomegaly"]["examples"] == [] and by["mass"]["examples"] == []
    assert [n["case_id"] for n in r.json()["normal_examples"]] == ["syn_008"]


@pytest.mark.parametrize("bank", [None, "", "labels: [1, 2", "- just\n- a list\n", "labels: 3\nnormal: {a: 1}\n"])
def test_missing_or_broken_yaml_gives_empty_examples_not_an_error(ref_env, bank):
    c = ref_env(bank)
    r = c.get("/api/reference")
    assert r.status_code == 200, r.text
    assert len(r.json()["labels"]) == 13 and all(e["examples"] == [] for e in r.json()["labels"])
    assert r.json()["normal_examples"] == []
    assert c.get("/api/reference/effusion").json()["examples"] == []


def test_missing_cards_do_not_500(ref_env):
    c = ref_env(GOOD_BANK, cards=False)  # BLINDSPOT_CARDS_DIR points at an empty tmp dir
    r = c.get("/api/reference")
    assert r.status_code == 200, r.text
    e = next(x for x in r.json()["labels"] if x["label"] == "nodule")
    assert set(e) == LABEL_KEYS
    assert (e["one_liner"], e["key_signs"], e["mimics"], e["search_tip"], e["radiopaedia_url"]) == (
        "",
        [],
        [],
        "",
        None,
    )
    assert e["display"] == "Nodule" and len(e["examples"]) == 1  # taxonomy text and examples still served


def test_bank_edits_are_picked_up_without_restart(ref_env, tmp_path):
    c = ref_env(GOOD_BANK)
    assert len(c.get("/api/reference/nodule").json()["examples"]) == 1
    import os

    p = tmp_path / "reference_bank.yaml"
    p.write_text(yaml.safe_dump({"labels": {}, "normal": []}))
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 5_000_000_000))  # clinician edit
    assert c.get("/api/reference/nodule").json()["examples"] == []


def test_reference_is_behind_the_access_gate(ref_env, monkeypatch):
    from backend.app.settings import get_settings

    c = ref_env(GOOD_BANK)
    monkeypatch.setenv("BLINDSPOT_ACCESS_CODE", "sesame")
    get_settings.cache_clear()
    for path in ("/api/reference", "/api/reference/nodule"):
        assert c.get(path).status_code == 401, path
        ok = c.get(path, headers={"X-Blindspot-Access": "sesame"})
        assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"


def test_reference_image_urls_carry_the_base_path(ref_env, monkeypatch):
    from backend.app.settings import get_settings

    c = ref_env(GOOD_BANK)
    monkeypatch.setenv("BLINDSPOT_BASE_PATH", "/blindspot")
    get_settings.cache_clear()
    body = c.get("/blindspot/api/reference").json()
    ex = next(e for e in body["labels"] if e["label"] == "nodule")["examples"][0]
    assert ex["image_url"] == "/blindspot/api/cases/syn_001/image"
    assert body["normal_examples"][0]["image_url"] == "/blindspot/api/cases/syn_008/image"


# ------------------------------------------------------------------ the committed bank against the real data
def test_committed_bank_is_well_formed():
    doc = yaml.safe_load(COMMITTED_BANK.read_text())
    from backend.app import config

    assert doc["split"] == "bench" and set(doc["labels"]) == set(config.labels())
    for lab, entries in doc["labels"].items():
        assert len(entries) <= 3, lab
        for e in entries:
            assert set(e) == {"case_id", "finding_id"} and e["finding_id"].startswith(e["case_id"] + "#F"), e
    assert len(doc["normal"]) <= 3 and all(set(e) == {"case_id"} for e in doc["normal"])


@pytest.mark.skipif(not REAL_CASES.exists(), reason="real data/processed not present (CI / fresh clone)")
def test_committed_bank_lists_only_bench_cases_never_practice_or_assessment():
    """Non-negotiable #2: a reference outline must never belong to a case a learner can be served."""
    cases = {}
    for line in REAL_CASES.read_text().splitlines():
        if line.strip():
            c = json.loads(line)
            cases[c["case_id"]] = c
    doc = yaml.safe_load(COMMITTED_BANK.read_text())
    listed = [(lab, e) for lab, es in doc["labels"].items() for e in es] + [(None, e) for e in doc["normal"]]
    assert listed
    servable = {cid for cid, c in cases.items() if c["split"] in NON_BENCH}
    for lab, e in listed:
        c = cases.get(e["case_id"])
        assert c is not None, e
        assert c["split"] == "bench", (e, c["split"])
        assert e["case_id"] not in servable
        assert c["qa_flags"] == [], (e, c["qa_flags"])
        if lab is None:
            assert c["is_normal"] and not c["findings"], e
            assert c["cardiothoracic_ratio"] is not None and c["cardiothoracic_ratio"] < 0.5, e
        else:
            f = next((f for f in c["findings"] if f["finding_id"] == e["finding_id"]), None)
            assert f is not None and f["label"] == lab, (lab, e)
    # one film per example within a label
    for lab, es in doc["labels"].items():
        assert len({e["case_id"] for e in es}) == len(es), lab
