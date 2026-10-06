# Blindspot evaluation report — contains DRY RUN / synthetic sections (not results)

Generated 2026-10-06 02:32 UTC from `eval/reports/*.json` at commit a66471d.

> **Not for slides yet:** these sections are dry-run or synthetic-fixture outputs: vlm_localization, faithfulness. Their numbers test the harness only. Re-run live (after the human cost checkpoint) before quoting anything.

## Slide lines

- **VLM localization benchmark (§12.1):**
  - [DRY RUN — mock outputs, not a result] Asked where a radiologist-marked finding is, claude-sonnet-5-5 put its point on the radiologist's outline in 0% (95% CI 0–0; n=4) of bench cases — vs 50% (95% CI 0–100; n=4) for the label-prior baseline and 3% (95% CI 2–4; n=4) for a random point in the lungs (selection: strict).
  - [DRY RUN — mock outputs, not a result] Patient side correct: 75% (95% CI 25–100; n=4); named grid cell overlaps the finding: 50% (95% CI 0–100; n=4).
- **Debrief faithfulness and grounding ablation (§12.2):**
  - [DRY RUN — mock outputs, not a result] Judged fully grounded in the radiologist truth: grounded pipeline 100% (95% CI 100–100; n=39) vs labels-only ablation 38% (95% CI 23–54; n=39); paired difference 62% (95% CI 46–77; n=39).
  - [DRY RUN — mock outputs, not a result] Laterality errors: grounded 0% (95% CI 0–0; n=39) vs ablation 0% (95% CI 0–0; n=39); hallucinated findings per debrief: 0.00 (95% CI 0.00–0.00; n=39) vs 0.00 (95% CI 0.00–0.00; n=39).
  - [DRY RUN — mock outputs, not a result] The deterministic validator passed 100% (95% CI 100–100; n=39) of grounded debriefs on the first try and 100% (95% CI 100–100; n=39) within one regeneration; learners saw the template fallback in 0% (95% CI 0–0; n=39).
- **Miss-type engine sanity check (§12.3):**
  - On scripted (synthetic) telemetry the production miss-type engine classified 153/153 behaviours as intended; varying ρ and the 300/1,000 ms thresholds by ±30% (27 configs), the worst config still classified scripted misses as intended at: decision 100%, recognition 95%, search 100%. Cursor dwell is a proxy for gaze.
- **Pilot and expert review (§12.4):**
  - No complete pilot data yet (pilot, n = 0, not powered; usability testing, not a research study).
  - No expert ratings yet (/review).

## Sections

### VLM localization benchmark (§12.1)

Full report: [vlm_localization.md](vlm_localization.md). Title: *VLM localization benchmark — DRY RUN — mock model outputs, synthetic fixtures*.

![vlm_localization.png](vlm_localization.png)

![vlm_laterality.png](vlm_laterality.png)

Live-run cost estimate: expected $0.00, worst case $0.00; actual spend recorded: $0.00.

### Debrief faithfulness and grounding ablation (§12.2)

Full report: [faithfulness.md](faithfulness.md). Title: *Debrief faithfulness and grounding ablation — DRY RUN — mock model outputs, synthetic fixtures*.

![faithfulness.png](faithfulness.png)

Live-run cost estimate: expected $4.14, worst case $10.07; actual spend recorded: $0.00.

Engines: scoring → backend.app.scoring.{hit,matching,outcomes,scores} (production); search → backend.app.search.{dwell,misstype,coverage,spatial} (production); tutor.cards → backend.app.tutor.cards.load_cards (production); tutor.facts → backend.app.tutor.facts.build_facts (production); tutor.service → backend.app.tutor.service.generate_debrief (production); tutor.templates → backend.app.tutor.templates.template_debrief (production); tutor.validator → backend.app.tutor.validator.validate (production).

### Miss-type engine sanity check (§12.3)

Full report: [misstype_sensitivity.md](misstype_sensitivity.md). Title: *Miss-type engine sanity check — synthetic scripted telemetry on ChestX-Det masks*.

![misstype_sensitivity.png](misstype_sensitivity.png)

Engines: scoring → backend.app.scoring.{hit,matching,outcomes,scores} (production); search → backend.app.search.{dwell,misstype,coverage,spatial} (production); search.dwell → backend.app.search.dwell.dwell_ms (production); search.misstype → backend.app.search.misstype.miss_type (production).

### Pilot and expert review (§12.4)

Full report: [pilot_analysis.md](pilot_analysis.md). Title: *Pilot analysis — pilot, n = 0, not powered; usability testing, not a research study*.

## Honesty rules applied

- Every number states n and a 95% CI (percentile bootstrap; Wilson interval added where the bootstrap collapses at 0% or 100%).
- Dry-run and synthetic-fixture outputs are labeled in titles, figures (watermark) and here.
- The pilot is usability testing, not a research study: not powered, no p-values.
- The miss-type engine uses cursor/loupe/zoom dwell as a proxy for gaze.
- Inconvenient results are reported as measured.
