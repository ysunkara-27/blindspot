"""Volumetric (CT / MR) API: sessions by modality, /next (voxels only), /volume, /maskvol gating (409 before submit;
assessment: after the summary), submit with voxel marks + measurements → reveal, GT-leak invariants, reference bank,
dev preview, and a scripted smoke read of vol_001..vol_004."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend.app.settings import REPO_ROOT
from backend.app.tests.conftest import FIXTURES, make_submit
from backend.app.tests.test_gt_leak import all_keys, assert_no_ground_truth
from shared.contracts import GROUND_TRUTH_KEYS, Mark, Measurement, TelemetryEvent

SCHEMAS = REPO_ROOT / "shared" / "schemas"
VOL_IDS = {"vol_001", "vol_002", "vol_003", "vol_004"}
LEAK_WORDS = ("mask", "label", "slice_range", "measure", "component", "finding", "centroid", "is_normal", "tumour")


def _session(c, mode="practice", **settings):
    r = c.post("/api/sessions", json={"display_name": "Vol", "level": "MS3", "mode": mode, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()


def ev(t, slice_, x=5.0, y=5.0, plane="axial"):
    return TelemetryEvent(
        t=t, kind="move", x=x, y=y, zoom=1.0, vp=(0, 0, 64, 64), loupe=False, plane=plane, slice=slice_
    )


def scroll(slices, ms_each=400.0, x=5.0, y=5.0, step=50.0):
    out, t = [], 0.0
    for s in slices:
        for k in range(int(ms_each / step)):
            out.append(ev(t, s, x + (k % 2) * 0.5, y))
            t += step
    out.append(ev(t, slices[-1], x, y))
    return out


def vmark(mid, voxel, label="pancreatic_tumour", conf=4):
    x, y, z = voxel
    return Mark(mark_id=mid, x=x, y=y, label=label, confidence=conf, plane="axial", slice=int(z), voxel=voxel)


def body(marks=(), measurements=(), telemetry=None, declared_normal=False, normal_confidence=None):
    sub = make_submit(
        marks=marks, telemetry=telemetry, declared_normal=declared_normal, normal_confidence=normal_confidence
    )
    sub = sub.model_copy(update={"measurements": list(measurements)})
    return json.loads(sub.model_dump_json())


def resplit_msd(root: Path, mapping: dict[str, str]) -> None:
    p = root / "cases_msd.jsonl"
    lines = []
    for line in p.read_text().splitlines():
        c = json.loads(line)
        if c["case_id"] in mapping:
            c["split"] = mapping[c["case_id"]]
        lines.append(json.dumps(c))
    p.write_text("\n".join(lines) + "\n")


def _validator(name: str) -> Draft202012Validator:
    reg = Registry()
    for f in SCHEMAS.glob("*.json"):
        doc = json.loads(f.read_text())
        res = Resource.from_contents(doc)
        reg = reg.with_resource(doc["$id"], res).with_resource(f.name, res)
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text()), registry=reg)


# ------------------------------------------------------------------ sessions and /next
def test_ct_session_serves_only_ct_cases_with_voxels_and_presets(api_env):
    c = api_env()
    s = _session(c, modality="ct", selection="random")
    seen = set()
    for _ in range(6):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        case = n["case"]
        seen.add(case["case_id"])
        assert case["modality"] == "ct" and case["body_region"] == "abdomen"
        assert set(case["volume"]) == {"shape", "spacing", "window", "data_url", "sequence", "presets"}
        assert case["volume"]["shape"] == [16, 64, 64] and case["volume"]["spacing"] == [3.0, 1.5, 1.5]
        assert case["volume"]["data_url"] == f"/api/cases/{case['case_id']}/volume"
        assert [p["name"] for p in case["volume"]["presets"]] == [
            "Lung",
            "Mediastinum",
            "Abdomen",
            "Liver",
            "Bone",
            "Brain",
        ]
        assert case["provenance"]["badge"] == "Segmented by a test script (synthetic)"
        assert_no_ground_truth(n, case["case_id"])
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(declared_normal=True, normal_confidence=3))
    assert seen == {"vol_001", "vol_002", "vol_004"}


def test_mr_session_serves_the_brain_case_with_a_single_default_preset(api_env):
    c = api_env()
    s = _session(c, modality="mr")
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    v = n["case"]["volume"]
    assert n["case"]["case_id"] == "vol_003" and n["case"]["modality"] == "mr" and v["sequence"] == "T1c"
    assert v["presets"] == [{"name": "Default", "wc": 300.0, "ww": 600.0}]


def test_bad_modality_is_422_and_a_volumetric_drill_label_implies_its_modality(api_env):
    c = api_env()
    r = c.post(
        "/api/sessions", json={"display_name": "V", "level": "MS3", "mode": "practice", "settings": {"modality": "pet"}}
    )
    assert r.status_code == 422
    s = _session(c, mode="drill", label="brain_tumour")
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    assert n["case"]["case_id"] == "vol_003"


def test_default_and_cxr_sessions_never_serve_a_volume(api_env):
    c = api_env()
    for settings in ({}, {"modality": "cxr"}):
        s = _session(c, selection="random", **settings)
        for _ in range(14):
            n = c.get(f"/api/sessions/{s['session_id']}/next").json()
            assert (
                n["case"]["modality"] == "cxr" and n["case"]["volume"] is None and n["case"]["case_id"] not in VOL_IDS
            )
            c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(declared_normal=True, normal_confidence=3))


def test_next_never_leaks_ground_truth_for_volumes(api_env):
    c = api_env()
    s = _session(c, modality="ct")
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    keys = all_keys(n)
    assert not keys & GROUND_TRUTH_KEYS
    assert not {k for k in keys if any(w in k for w in LEAK_WORDS)} - {"sequence"}, keys
    text = json.dumps(n).lower()
    assert "mask" not in text and "tumour" not in text and "pancreas" not in text and "#f" not in text


# ------------------------------------------------------------------ /volume and /maskvol
def test_volume_bytes_are_gzip_identity_encoded_and_cached(api_env):
    c = api_env()
    r = c.get("/api/cases/vol_001/volume")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-encoding"] == "identity" and "immutable" in r.headers["cache-control"]
    assert r.content[:2] == b"\x1f\x8b"
    arr = np.frombuffer(gzip.decompress(r.content), dtype="<i2")
    assert arr.size == 16 * 64 * 64 and arr.min() >= -1024
    assert r.content == (FIXTURES / "volumes" / "vol_001.i16.gz").read_bytes()  # voxels as stored, nothing else
    assert c.get("/api/cases/syn_001/volume").status_code == 404  # an X-ray has no volume
    assert c.get("/api/cases/nope/volume").status_code == 404


def test_maskvol_is_409_before_submit_and_200_after_with_the_reveal_url(api_env):
    c = api_env()
    s = _session(c, modality="ct", playlist=["vol_001"])
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    aid = n["attempt_id"]
    pre = c.get(f"/api/attempts/{aid}/maskvol")
    assert pre.status_code == 409 and "mask" not in pre.text.lower().replace("maskvol", "")
    sub = c.post(
        f"/api/attempts/{aid}/submit",
        json=body(
            marks=[vmark("M1", (24, 36, 8))],
            measurements=[Measurement(mark_id="M1", long_mm=12.0, plane="axial", slice=8)],
            telemetry=scroll([6, 7, 8, 9, 10], x=24, y=36),
        ),
    )
    assert sub.status_code == 200, sub.text
    res = sub.json()
    assert res["reveal"]["maskvol_url"] == f"/api/attempts/{aid}/maskvol" and res["reveal"]["modality"] == "ct"
    post = c.get(f"/api/attempts/{aid}/maskvol")
    assert post.status_code == 200 and post.headers["cache-control"] == "no-store"
    assert post.content == (FIXTURES / "masks" / "vol_001.u8.gz").read_bytes()
    mv = np.frombuffer(gzip.decompress(post.content), dtype=np.uint8).reshape(16, 64, 64)
    assert mv[8, 36, 24] == 2 and mv[8, 36, 34] == 1
    # the stored result carries the same URL and the learner's measurement
    got = c.get(f"/api/attempts/{aid}/result").json()
    assert got["reveal"]["maskvol_url"] == f"/api/attempts/{aid}/maskvol" and got["case"]["volume"]["shape"] == [
        16,
        64,
        64,
    ]
    assert got["submitted"]["marks"][0]["voxel"] == [24.0, 36.0, 8.0]


def test_maskvol_404_for_an_xray_attempt(api_env):
    c = api_env()
    s = _session(c)
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(declared_normal=True, normal_confidence=3))
    assert c.get(f"/api/attempts/{n['attempt_id']}/maskvol").status_code == 404


def test_submit_reveal_has_size_verdict_slice_dwell_and_validates_against_the_schema(api_env):
    c = api_env()
    v = _validator("submit_result.json")
    s = _session(c, modality="ct", playlist=["vol_001"])
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    res = c.post(
        f"/api/attempts/{n['attempt_id']}/submit",
        json=body(
            marks=[vmark("M1", (24, 36, 8)), vmark("M2", (50, 10, 3), label="liver_tumour", conf=2)],
            measurements=[Measurement(mark_id="M1", long_mm=17.0, plane="axial", slice=8)],
            telemetry=scroll([4, 5, 6, 7, 8], x=24, y=36),
        ),
    ).json()
    assert v.is_valid(res), [e.message for e in v.iter_errors(res)][:3]
    assert res["score"] == 100.0 and res["success"] is True
    outs = {o["target"]: o for o in res["outcomes"]}
    assert outs["F1"]["result"] == "found" and outs["F1"]["slices_viewed"] is True
    assert outs["F1"]["size_verdict"] == {
        "your_mm": 17.0,
        "reference_mm": 13.5,
        "diff_mm": 3.5,
        "diff_pct": 25.9,
        "ok": False,
        "plane": "axial",
    }
    assert outs["M2"]["result"] == "unmatched"
    rv = res["reveal"]
    f = rv["findings"][0]
    assert f["slice_range"] == [6, 10] and f["measure"] == {"long_mm": 13.5, "slice": 8, "plane": "axial"}
    assert f["size_verdict"]["ok"] is False and f["label_values"] == [2] and f["centroid3"] == [24.0, 36.0, 8.0]
    assert [m["result"] for m in rv["marks"]] == ["true_positive", "unmatched"]
    assert rv["marks"][1] == {
        "mark_id": "M2",
        "result": "unmatched",
        "matched_finding": None,
        "zone": "superior_slab",
        "voxel": [50.0, 10.0, 3.0],
        "plane": "axial",
        "slice": 3,
        "polygon": None,
        "outline_verdict": None,
    }
    sd = rv["search"]["slice_dwell"]
    assert [d["slice"] for d in sd] == [4, 5, 6, 7, 8] and [d["has_finding"] for d in sd] == [
        False,
        False,
        True,
        True,
        True,
    ]
    assert rv["search"]["slices_viewed_pct"] == 31.2 and rv["search"]["finding_slices_viewed"] == {"F1": True}
    assert rv["search"]["heatmap_png_b64"] is None and rv["provenance"]["grade"] == "unknown"
    assert f["slice_range"] == [6, 10]  # contract: 0-based
    assert "slices 7–11 of 16 (you viewed 3 of them)" in res["facts_card"]["lines"][0]  # people: 1-based
    assert "you measured 17 mm, reference 13.5 mm — larger than the reference" in res["facts_card"]["lines"][0]
    assert res["facts_card"]["lines"][-1] == "You viewed 31% of the 16 slices. Score 100."


def test_submit_validation_on_a_volume(api_env):
    c = api_env()
    s = _session(c, modality="ct", playlist=["vol_001"])
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    aid = n["attempt_id"]
    bad = body(marks=[Mark(mark_id="M1", x=10, y=10, label="pancreatic_tumour", confidence=3)])  # no slice, no voxel
    r = c.post(f"/api/attempts/{aid}/submit", json=bad)
    assert r.status_code == 422 and "needs a voxel or a slice" in r.text
    r = c.post(f"/api/attempts/{aid}/submit", json=body(marks=[vmark("M1", (24, 36, 40))]))
    assert r.status_code == 422 and "outside the volume" in r.text
    r = c.post(
        f"/api/attempts/{aid}/submit",
        json=body(
            marks=[vmark("M1", (24, 36, 8))],
            measurements=[Measurement(mark_id="M7", long_mm=5, plane="axial", slice=8)],
        ),
    )
    assert r.status_code == 422 and "unknown mark" in r.text
    assert c.get(f"/api/attempts/{aid}/maskvol").status_code == 409  # still unsubmitted


# ------------------------------------------------------------------ assessment
@pytest.fixture
def assess_root(processed_copy):
    resplit_msd(processed_copy, {"vol_001": "assess_A", "vol_004": "assess_A"})
    return processed_copy


def test_assessment_hides_the_mask_until_the_summary(api_env, assess_root):
    c = api_env(assess_root)
    s = _session(c, mode="assess_A", modality="ct")
    sid = s["session_id"]
    aids = []
    for i in range(2):
        n = c.get(f"/api/sessions/{sid}/next").json()
        assert n["case"]["modality"] == "ct" and n["total"] == 2
        assert_no_ground_truth(n, n["case"]["case_id"])
        r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(marks=[vmark("M1", (24, 36, 8))]))
        assert r.json() == {"recorded": True, "index": i + 1, "total": 2}
        aids.append(n["attempt_id"])
        if i == 0:
            for path in (
                f"/api/attempts/{aids[0]}/maskvol",
                f"/api/attempts/{aids[0]}/result",
                f"/api/sessions/{sid}/summary",
            ):
                assert c.get(path).status_code == 409, path
    summ = c.get(f"/api/sessions/{sid}/summary").json()
    assert summ["complete"] and {r["modality"] for r in summ["cases"]} == {"ct"}
    for aid in aids:
        assert c.get(f"/api/attempts/{aid}/maskvol").status_code == 200
        assert c.get(f"/api/attempts/{aid}/result").json()["reveal"]["maskvol_url"] == f"/api/attempts/{aid}/maskvol"
    # an X-ray assessment in the same bundle is unaffected by the CT split
    xs = _session(c, mode="assess_A")
    assert c.get(f"/api/sessions/{xs['session_id']}/next").json()["done"] is True  # no cxr assess cases in fixtures


# ------------------------------------------------------------------ hints, dev preview, reference
def test_hints_on_a_volume_are_deterministic_and_never_say_mm(api_env):
    c = api_env()
    s = _session(c, modality="ct", playlist=["vol_001"])
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    tel = [e.model_dump() for e in scroll([8], 1000, x=5, y=5)]
    texts = []
    for level in (1, 2, 3):
        r = c.post(f"/api/attempts/{n['attempt_id']}/hint", json={"marks": [], "telemetry": tel})
        assert r.status_code == 200, r.text
        assert r.json()["level"] == level and r.json()["remaining"] == 3 - level
        texts.append(r.json()["text"])
    assert texts[0].startswith("You haven't looked at the pancreas")
    assert "mm" not in " ".join(texts) and "cm" not in " ".join(texts)


def test_dev_volume_preview_is_gated_and_returns_a_png(api_env, monkeypatch):
    c = api_env()
    assert c.get("/api/dev/cases/vol_001/volume_preview").status_code == 404
    monkeypatch.setenv("BLINDSPOT_DEV", "1")
    c = api_env()
    r = c.get("/api/dev/cases/vol_001/volume_preview")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert c.get("/api/dev/cases/vol_003/volume_preview", params={"slice": 12, "scale": 2}).status_code == 200
    assert c.get("/api/dev/cases/syn_001/volume_preview").status_code == 404


def test_reference_bank_lists_volumetric_examples_from_bench_only(api_env, processed_copy):
    resplit_msd(processed_copy, {"vol_001": "bench"})
    c = api_env(processed_copy)
    labels = {e["label"]: e for e in c.get("/api/reference").json()["labels"]}
    assert set(labels) >= {"pancreatic_tumour", "liver_tumour", "brain_tumour"}
    (ex,) = labels["pancreatic_tumour"]["volume_examples"]
    assert ex["case_id"] == "vol_001" and ex["modality"] == "ct" and ex["volume_url"] == "/api/cases/vol_001/volume"
    assert ex["mask_url"] == "/api/reference/vol_001/maskvol" and ex["shape"] == [16, 64, 64]
    assert ex["measure_slice"] == 8 and ex["finding"]["slice_range"] == [6, 10] and ex["finding"]["side"] == "right"
    assert ex["labels"] == {"1": "pancreas", "2": "pancreatic_tumour"} and ex["provenance"]["badge"]
    assert labels["liver_tumour"]["volume_examples"] == []  # vol_002 is a practice case: never a reference example
    assert labels["nodule"]["volume_examples"] == [] and labels["pancreatic_tumour"]["examples"] == []
    assert c.get("/api/reference/vol_001/maskvol").status_code == 200
    assert c.get("/api/reference/vol_002/maskvol").status_code == 404  # practice case: never
    assert c.get("/api/reference/syn_001/maskvol").status_code == 404
    # the written bank file is honoured
    from backend.app import reference as bank
    from backend.app.cases import CaseRepository

    repo = CaseRepository(processed_copy)
    p = bank.write_volumetric_bank(repo)
    doc = json.loads(p.read_text())
    assert p.name == "reference_bank_volumetric.json" and doc["labels"]["pancreatic_tumour"] == [
        {"case_id": "vol_001", "finding_id": "vol_001#F1"}
    ]
    assert doc["labels"]["liver_tumour"] == []


# ------------------------------------------------------------------ smoke: scripted reads of every fixture volume
def test_smoke_read_of_all_four_volumes_through_the_api(api_env):
    c = api_env()
    reads = {
        "vol_001": body(marks=[vmark("M1", (24, 36, 8))], telemetry=scroll(range(16), x=24, y=36)),
        "vol_002": body(marks=[vmark("M1", (18, 24, 5), "liver_tumour")], telemetry=scroll(range(16), x=18, y=24)),
        "vol_004": body(declared_normal=True, normal_confidence=4, telemetry=scroll(range(16))),
        "vol_003": body(marks=[vmark("M1", (40, 28, 8), "brain_tumour")], telemetry=scroll(range(16), x=40, y=28)),
    }
    results = {}
    for modality, playlist in (("ct", ["vol_001", "vol_002", "vol_004"]), ("mr", ["vol_003"])):
        s = _session(c, modality=modality, playlist=playlist)
        for _ in playlist:
            n = c.get(f"/api/sessions/{s['session_id']}/next").json()
            cid = n["case"]["case_id"]
            r = c.post(f"/api/attempts/{n['attempt_id']}/submit", json=reads[cid])
            assert r.status_code == 200, (cid, r.text)
            results[cid] = r.json()
            assert c.get(f"/api/attempts/{n['attempt_id']}/maskvol").status_code == 200
            d = c.get(f"/api/attempts/{n['attempt_id']}/debrief").json()
            assert d["status"] in ("pending", "ready", "failed")
        assert c.get(f"/api/sessions/{s['session_id']}/next").json()["done"] is True
        summ = c.get(f"/api/sessions/{s['session_id']}/summary").json()
        assert summ["n_cases"] == len(playlist) and all(r["modality"] == modality for r in summ["cases"])
    # vol_002: one of two liver tumours localized → 35 + 10 label + 10 pattern = 55
    assert {k: r["score"] for k, r in results.items()} == {
        "vol_001": 100.0,
        "vol_002": 55.0,
        "vol_003": 100.0,
        "vol_004": 100.0,
    }
    assert results["vol_004"]["facts_card"]["headline"] == "Correct: this scan is normal"
    # F2's slices were on screen for 3.2 s but the cursor stayed 24 mm away (on F1): looked past it
    assert {o["target"]: o["result"] for o in results["vol_002"]["outcomes"]}["F2"] == "missed_recognition"
    assert all(r["reveal"]["search"]["slices_viewed_pct"] == 100.0 for r in results.values())


# ------------------------------------------------------------------ round-4 pages contract: dashboard, summary, about
def test_dashboard_modality_filter_n_by_modality_and_misses_by_zone(api_env):
    c = api_env()
    s = _session(c, modality="ct", playlist=["vol_001", "vol_002", "vol_004"])
    lid = s["learner_id"]
    reads = {
        "vol_001": body(marks=[vmark("M1", (24, 36, 8))], telemetry=scroll(range(16), x=24, y=36)),  # found
        "vol_002": body(marks=[vmark("M1", (18, 24, 5), "liver_tumour")], telemetry=scroll(range(16))),  # F2 missed
        "vol_004": body(declared_normal=True, normal_confidence=4),
    }
    for _ in range(3):
        n = c.get(f"/api/sessions/{s['session_id']}/next").json()
        c.post(f"/api/attempts/{n['attempt_id']}/submit", json=reads[n["case"]["case_id"]])
    xs = _session(c, learner_id=lid, playlist=["syn_001"])  # one X-ray read by the same learner
    n = c.get(f"/api/sessions/{xs['session_id']}/next").json()
    assert n["case"]["modality"] == "cxr"
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(declared_normal=True, normal_confidence=3))

    d = c.get(f"/api/learners/{lid}/dashboard").json()
    assert d["modality"] is None and d["n_attempts"] == 4 and d["n_by_modality"] == {"cxr": 1, "ct": 3, "mr": 0}
    assert "misses_by_zone" not in d
    ct = c.get(f"/api/learners/{lid}/dashboard", params={"modality": "ct"}).json()
    assert ct["modality"] == "ct" and ct["n_attempts"] == 3 and ct["n_by_modality"] == d["n_by_modality"]
    assert ct["summary"]["n_abnormal"] == 2 and ct["summary"]["n_normal"] == 1
    assert ct["misses_by_zone"] == [{"zone": "mid_slab", "human": "middle slices of the volume", "n": 3, "n_missed": 1}]
    cx = c.get(f"/api/learners/{lid}/dashboard", params={"modality": "cxr"}).json()
    assert cx["n_attempts"] == 1 and "misses_by_zone" not in cx
    assert c.get(f"/api/learners/{lid}/dashboard", params={"modality": "mr"}).json()["n_attempts"] == 0
    assert c.get(f"/api/learners/{lid}/dashboard", params={"modality": "pet"}).status_code == 422

    summ = c.get(f"/api/sessions/{s['session_id']}/summary").json()
    assert summ["modality"] == "ct" and all(r["modality"] == "ct" for r in summ["cases"])
    assert all(r["provenance"]["badge"] == "Segmented by a test script (synthetic)" for r in summ["cases"])
    xsumm = c.get(f"/api/sessions/{xs['session_id']}/summary").json()
    assert xsumm["modality"] == "cxr" and xsumm["cases"][0]["provenance"] is None  # synthetic source: no badge


def test_xray_cases_from_chestx_det_get_the_config_provenance_at_read_time(api_env, processed_copy):
    p = processed_copy / "cases.jsonl"
    lines = []
    for line in p.read_text().splitlines():
        d = json.loads(line)
        if d["case_id"] == "syn_001":
            d["source"] = "chestx-det"
            d.pop("provenance", None)
        lines.append(json.dumps(d))
    p.write_text("\n".join(lines) + "\n")
    c = api_env(processed_copy)
    s = _session(c, playlist=["syn_001"])
    n = c.get(f"/api/sessions/{s['session_id']}/next").json()
    prov = n["case"]["provenance"]
    assert (
        prov["dataset"] == "ChestX-Det" and prov["grade"] == "radiologist" and prov["modality"] is None
        if "modality" in prov
        else True
    )
    assert prov["badge"] == "Segmented by three board-certified radiologists (ChestX-Det)"
    assert_no_ground_truth(n, "syn_001")
    c.post(f"/api/attempts/{n['attempt_id']}/submit", json=body(declared_normal=True, normal_confidence=3))
    row = c.get(f"/api/sessions/{s['session_id']}/summary").json()["cases"][0]
    assert row["provenance"]["badge"] == prov["badge"] and row["modality"] == "cxr"
    assert json.loads(p.read_text().splitlines()[0]).get("provenance") is None  # the file is never rewritten


def test_about_provenance_is_the_yaml_keyed_with_a_modality(api_env):
    prov = api_env().get("/api/about").json()["provenance"]
    assert {"chestx-det", "Task07_Pancreas", "Task01_BrainTumour", "Task08_HepaticVessel"} <= set(prov)
    assert prov["chestx-det"]["modality"] == "cxr" and prov["Task01_BrainTumour"]["modality"] == "mr"
    assert prov["Task07_Pancreas"]["modality"] == "ct" and prov["Task07_Pancreas"]["license"] == "CC BY-SA 4.0"
    assert all({"dataset", "segmented_by", "grade", "modality"} <= set(v) for v in prov.values())


def test_reference_labels_carry_their_modality(api_env):
    labels = {e["label"]: e["modality"] for e in api_env().get("/api/reference").json()["labels"]}
    assert labels["nodule"] == "cxr" and labels["pancreatic_tumour"] == "ct" and labels["brain_tumour"] == "mr"


def test_anatomy_endpoint_on_a_volume_returns_labels_not_outlines(api_env):
    """/anatomy must not crash on a volumetric case; it reports the anatomy label map and no 2-D zones."""
    c = api_env()
    sid = _session(c, modality="ct", selection="random")["session_id"]
    nxt = c.get(f"/api/sessions/{sid}/next").json()
    aid = nxt["attempt_id"]
    assert c.get(f"/api/attempts/{aid}/anatomy").status_code == 409
    body = {
        "marks": [],
        "patterns": [],
        "declared_normal": True,
        "normal_confidence": 3,
        "telemetry": [],
        "hints_used": 0,
        "client_timing": {"shown_at": "2026-10-07T00:00:00Z", "submitted_at": "2026-10-07T00:00:10Z"},
        "measurements": [],
    }
    assert c.post(f"/api/attempts/{aid}/submit", json=body).status_code == 200
    r = c.get(f"/api/attempts/{aid}/anatomy")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["volumetric"] is True and d["zones"] == [] and isinstance(d["labels"], dict)
