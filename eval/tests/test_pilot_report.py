"""Pilot analysis on a tiny SYNTHETIC SQLite DB (labeled synthetic; tests only), the miss-type script, and the
report assembler."""

from __future__ import annotations

import json
import sqlite3

import pytest

from eval import misstype_sensitivity, pilot_analysis, report

SCHEMA = """
CREATE TABLE learners (id TEXT PRIMARY KEY, display_name TEXT, level TEXT, participant_code TEXT, created_at TEXT);
CREATE TABLE sessions (id TEXT PRIMARY KEY, learner_id TEXT, mode TEXT, settings_json TEXT, started_at TEXT,
  ended_at TEXT);
CREATE TABLE attempts (id TEXT PRIMARY KEY, session_id TEXT, learner_id TEXT, case_id TEXT, mode TEXT, idx INTEGER,
  shown_at TEXT, submitted_at TEXT, declared_normal INTEGER, normal_confidence INTEGER, marks_json TEXT,
  patterns_json TEXT, hints_used INTEGER, hint_log_json TEXT, score REAL, success INTEGER, outcomes_json TEXT,
  search_json TEXT, elo_json TEXT);
CREATE TABLE sus (learner_id TEXT, answers_json TEXT, score REAL, created_at TEXT);
CREATE TABLE reviews (id TEXT PRIMARY KEY, reviewer TEXT, role TEXT, item_type TEXT, item_id TEXT, accuracy INTEGER,
  teaching INTEGER, safety_flag INTEGER, comment TEXT, created_at TEXT);
"""

# outcome templates: abnormal case found / missed (search) ; normal clean / normal with one false positive
ABN_FOUND = [{"target": "F1", "result": "found"}, {"target": "M1", "result": "true_positive"}]
ABN_MISS_SEARCH = [{"target": "F1", "result": "missed_search", "dwell_ms": 0}]
ABN_MISS_DECISION = [{"target": "F1", "result": "missed_decision", "dwell_ms": 2000}]
NOR_CLEAN = [{"target": "case", "result": "true_negative"}]
NOR_FP = [{"target": "M1", "result": "false_positive", "zone": "left_mid_zone"}]


def make_db(path) -> None:  # noqa: ANN001
    """SYNTHETIC pilot: P01 (odd → A first) improves; P02 (even → B first) unchanged; P03 incomplete."""
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    plan = {
        "P01": [
            ("assess_A", [ABN_MISS_SEARCH, ABN_MISS_SEARCH, ABN_FOUND, NOR_FP]),
            ("assess_B", [ABN_FOUND, ABN_FOUND, ABN_MISS_DECISION, NOR_CLEAN]),
        ],
        "P02": [
            ("assess_B", [ABN_FOUND, ABN_MISS_SEARCH, NOR_CLEAN, NOR_CLEAN]),
            ("assess_A", [ABN_FOUND, ABN_MISS_SEARCH, NOR_CLEAN, NOR_CLEAN]),
        ],
        "P03": [("assess_A", [ABN_FOUND, NOR_CLEAN, NOR_CLEAN, NOR_CLEAN])],
    }
    for li, (code, sessions) in enumerate(plan.items()):
        lid = f"L{li}"
        con.execute("INSERT INTO learners VALUES (?,?,?,?,?)", (lid, f"synthetic {code}", "MS2", code, "t"))
        for si, (mode, outs) in enumerate(sessions):
            sid = f"S{li}{si}"
            con.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?)", (sid, lid, mode, "{}", f"2026-10-07T2{si}:00", None)
            )
            for ai, o in enumerate(outs):
                con.execute(
                    "INSERT INTO attempts (id, session_id, learner_id, case_id, mode, idx, shown_at, "
                    "submitted_at, score, success, outcomes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"A{li}{si}{ai}", sid, lid, f"syn_case_{mode}_{ai}", mode, ai, "t", "t", 50.0, 1, json.dumps(o)),
                )
        con.execute("INSERT INTO sus VALUES (?,?,?,?)", (lid, json.dumps([5, 1, 5, 1, 5, 1, 5, 1, 5, 1]), None, "t"))
    con.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("R1", "synthetic reviewer", "radiologist", "debrief", "faith:x", 4, 5, 0, "fine", "t"),
    )
    con.commit()
    con.close()


def test_sus_formula_matches_backend() -> None:
    assert pilot_analysis.sus_from_answers([5, 1, 5, 1, 5, 1, 5, 1, 5, 1]) == 100.0
    assert pilot_analysis.sus_from_answers([3] * 10) == 50.0
    from backend.app.routes.pilot import sus_score

    for a in ([4, 2, 4, 2, 3, 3, 5, 1, 4, 2], [1] * 10):
        assert pilot_analysis.sus_from_answers(a) == sus_score(a)


def test_code_parity() -> None:
    assert pilot_analysis.code_parity("P01") == 1 and pilot_analysis.code_parity("P12") == 0
    assert pilot_analysis.code_parity("anon") is None


def test_pilot_on_synthetic_db(tmp_path) -> None:  # noqa: ANN001
    db = tmp_path / "synthetic_pilot.sqlite"
    make_db(db)
    res = pilot_analysis.analyse(pilot_analysis.load(db), {}, min_cases=4, n_boot=200, seed=0)
    assert res["n_participants"] == 3 and res["n_paired"] == 2
    p1 = next(p for p in res["participants"] if p["code"] == "P01")
    assert p1["order_as_protocol"] and p1["pre_form"] == "assess_A"
    assert p1["pre"]["sensitivity"] == pytest.approx(1 / 3)  # 3 abnormal, 1 detected
    assert p1["post"]["sensitivity"] == pytest.approx(2 / 3)
    assert p1["pre"]["specificity"] == 0.0 and p1["post"]["specificity"] == 1.0
    assert p1["pre"]["false_positives_per_image"] == pytest.approx(0.25)
    assert p1["pre"]["search_share"] == 1.0 and p1["post"]["search_share"] == 0.0
    assert p1["sus"] == 100.0
    p2 = next(p for p in res["participants"] if p["code"] == "P02")
    assert p2["order_as_protocol"] and p2["pre_form"] == "assess_B"
    assert not next(p for p in res["participants"] if p["code"] == "P03")["complete"]
    ch = res["changes"]["sensitivity"]
    assert ch["n"] == 2 and ch["change_median"].point == pytest.approx((1 / 3 + 0) / 2)
    assert res["reviews"]["debrief"]["n_ratings"] == 1 and res["reviews"]["debrief"]["accuracy"].point == 4
    path = pilot_analysis.write_report(res, db, tmp_path, 4, 200, 0)
    text = path.read_text()
    assert "pilot, n = 2, not powered; usability testing, not a research study" in text
    assert "synthetic P01" not in text  # display names never reach the report


def test_pilot_main_without_db(tmp_path) -> None:  # noqa: ANN001
    assert pilot_analysis.main(["--db", str(tmp_path / "missing.sqlite"), "--out-dir", str(tmp_path)]) == 0
    assert "pilot, n = 0" in (tmp_path / "pilot_analysis.md").read_text()


def test_misstype_sensitivity_runs_on_fixtures(tmp_path) -> None:  # noqa: ANN001
    assert misstype_sensitivity.main(["--source", "fixtures", "--out-dir", str(tmp_path)]) == 0
    j = json.loads((tmp_path / "misstype_sensitivity.json").read_text())
    assert j["n_ok"] == j["n_scenarios"] > 30
    assert j["synthetic_telemetry"] is True
    assert set(j["robustness"]) == {"search", "recognition", "decision"}
    assert (tmp_path / "misstype_sensitivity.png").exists()


def test_report_labels_dry_runs_and_missing_sections(tmp_path) -> None:  # noqa: ANN001
    ci = {"point": 0.5, "lo": 0.4, "hi": 0.6, "n": 30}
    summ = {
        k: {
            m: ci
            for m in (
                "grounded",
                "laterality_error",
                "hallucinated_per_debrief",
                "validator_first",
                "model_pass_within_regen",
                "template_fallback",
            )
        }
        for k in ("G", "U")
    }
    (tmp_path / "faithfulness.json").write_text(
        json.dumps({"title": "x", "dry_run": True, "synthetic": True, "summary": summ})
    )
    text = report.build(tmp_path)
    assert "DRY RUN" in text.splitlines()[0]
    assert "[DRY RUN — mock outputs, not a result]" in text
    assert "VLM localization benchmark (§12.1):** not run yet" in text
    assert "n=30" in text
    assert report.main(["--reports-dir", str(tmp_path)]) == 0 and (tmp_path / "REPORT.md").exists()
