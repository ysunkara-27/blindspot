# PROGRESS — Blindspot build log (newest first)

Format for entries:
`YYYY-MM-DD HH:MM — <agent> — <milestone> — <status: started|green|BLOCKED|note>`
then 1–5 lines: what changed, how verified (command + result), next step.

Special entries:
- `CONTRACT CHANGE REQUEST: <what / why>` — orchestrator decides.
- `BLOCKED: <problem> — options: …` — take the SPEC §19 fallback and continue.
- `DECISION: <ambiguity> → <choice>` — when the spec was silent.

---

2026-10-05 22:50 — qa-reviewer — QA gate W1 (M1, M3, M4, M5 offline) — pass with issues, no blockers
- Full notes, commands and 14 issues: docs/REVIEW_NOTES.md ("QA gate W1"). `uv run pytest -q` 429 passed/6 skipped; ruff, tsc, oxlint, vitest 50, build clean; Playwright real API 12/12 + QA spec 6/7 hard (soft: /about Apache-2.0, footer on unknown route).
- Leak (practice + assess A/B, real data, isolated DB): 0 leaks; hint/ask 403, summary 409 until 20/20. Patient-side: 8,011/8,012 lateral findings agree with centroid; heart on image right 91.6%. 600+ offline debriefs on real/fixture cases: 0 validator or independent-check failures.
- Open (owners): major backend `/api/dev/*` exposes GT unauthenticated (gate behind BLINDSPOT_DEV); major frontend `RevealLayer.tsx:51` ignores `arrow.label`; major orchestrator reset dev DB (118 test attempts show as real in cohort); major (M8) /about lacks Apache-2.0; minors in REVIEW_NOTES 5-14.
- New tests: backend/app/tests/test_qa_{leak,semantics,tutor}.py, pipeline/tests/test_qa_data.py, tests/e2e/qa_gate_w1.spec.ts. reading_room.spec.ts now prefixes `live-` on E2E_REAL runs.

2026-10-05 22:36 — vision-ml-engineer — M2 — green
- Files: pipeline/anatomy/{__init__,common,segment,orientation,zones,locate,overlay,synthetic}.py; pipeline/features/{lesion,ctr,difficulty}.py; tests pipeline/tests/test_zones.py, test_zones_locate.py, test_zones_orientation.py, test_zones_acceptance.py (real data, gated by BLINDSPOT_FULL_DATA_CHECK=1), test_features.py. Outputs (gitignored): data/processed/anatomy/*.npz (3,427, 42 MB), data/processed/zones/*.json + preview *.png (3,578, 304 MB), data/qa/orientation_report.json, anatomy_cxd_*.png ×20, anatomy_ctr_stats.json, anatomy_difficulty_params.json, difficulty_prior.png.
- Verified: `BLINDSPOT_FULL_DATA_CHECK=1 uv run pytest pipeline -q` → 105 passed (incl. 6 real-data M2 acceptance checks); `uv run ruff check pipeline` clean; ruff format clean.
- Segmentation: 3,427/3,427 in-scope cases (100%), 0 failures, 23.0 min on MPS at 2.47 img/s (148/min), batch 8. Holdout (151) not segmented → approximate zones + qa flag `anatomy_missing`. 0 `anatomy_failed`.
- Orientation: x(Right Lung) < x(Left Lung) in 100% of 3,427 → TXV names are patient-side, NO swap. 29 `orientation_suspect` (all heart centroid < W/2 − 0.05·W; 0 reversed lungs): practice 23, bench 5, assess_B 1. Heart on the image's right in 92.4% of non-flagged cases (right of the spine midline: 98.3%). Spot checks show off-centre patients, not mirrored films; 14/29 have the heart right of the spine. Kept the spec rule (conservative).
- Locations: all 7,701 in-scope focal findings (8,018 incl. holdout) have side/zones/primary_zone/relative_location; 27% have a review area as primary. Features: contrast + edge_dist 100%; model_prob 7,364 (null = calcification, which has no TXV output, + holdout). CTR: 3,427 cases, 0 implausible; AUC 0.92 against the radiologist cardiomegaly label (mean 0.558 vs 0.453). b0 per-label medians: calcification 1.14, nodule 1.02, fracture 0.81, pleural_thickening 0.81, pneumothorax 0.53, atelectasis −0.12, effusion −0.33, mass −0.51, consolidation −0.69. Ran `python -m pipeline.splits --rebalance`: forms rebuilt (the flagged assess_B case moved out); label mix identical; mean-b0 gap 0.00015 (A 0.2562 / B 0.2561).
DECISION: PSPNet outputs are logits (min −28, max 15) → mask = logit > 0 (= sigmoid > 0.5); predicted at 512², nearest-upsampled to 1024; input downsampled with cv2 INTER_AREA (anti-aliased), not skimage. Thresholding specks removed at load time (largest component for lungs/heart/clavicles/spine/weasand; components ≥ 20% of the largest otherwise).
DECISION: primary_zone = argmax overlap, but overlaps within 0.05 of the max are a tie, broken by specificity: review areas > lung thirds > heart/clavicles/spine > periphery, then smaller area. So an apical nodule reads "right apex", not "right upper zone". If no zone reaches ≥ 0.15 overlap: use the zone the mask overlaps most if it touches any, else the nearest zone by centroid.
DECISION: label-aware diaphragm rule. With a basal opacity the TXV aerated-lung mask stops at the opacity and TXV's diaphragm edge rises to meet it. Without a fix, effusions would be described as "below the diaphragm". For effusion, pleural_thickening, consolidation, atelectasis and pneumothorax, `subdiaphragmatic` is never a zone or primary, and the only diaphragm phrase is "just above the diaphragm". Nodule, mass, calcification and fracture keep it (lung behind the dome is the classic blind spot).
DECISION: relative_location template = "<zone human>[, lateral|central|medial third][, upper|middle|lower part][, <side> side for mediastinum/heart/spine/subdiaphragmatic][, just above|below|lateral to|medial to / extending into the <adjacent review area>]". The vertical part is omitted when an above/below phrase is present. Config adjacency is used symmetrically. Never cm, lobes or ribs (a test asserts this).
DECISION: n_findings = all findings in the case (focal + pattern); a missing contrast or model_prob contributes 0 to b0; pattern-only cases b0 = 0. `ctr_implausible` (CTR outside [0.25, 0.85] → null) is flagged only on cardiomegaly cases, because any qa flag removes a case from the assessment pools. It never fired.
NOTE: TXV densenet121-res224-all was trained on NIH ChestX-ray14 (among others), and ChestX-Det images come from NIH. model_prob is therefore optimistic (possible train overlap). It is used only as a weak b0 feature. Mapping: TXV_CLASSIFIER_MAP in pipeline/anatomy/common.py (11 labels; calcification and diffuse_nodule unmapped → null).
NOTE for backend: (1) `orientation_suspect` and `anatomy_missing` cases stay in split=practice/bench (splits only excludes flagged cases from assessment). /next must skip cases with qa_flags. (2) Torch-free helpers for the backend: `from pipeline.anatomy import zone_at, spatial_relation, locate_finding`. backend/app/search/spatial.py already has its own compatible relation_text, so these are optional. (3) Zones JSON has every config zone id + right_lung/left_lung/lungs and meta midline_x; zones_approximate=True only for the 151 holdout cases.
- Next: Sri reviews data/qa/anatomy_cxd_*.png. Optional: relax the heart check to the spine midline (would un-flag ~14 off-centre cases).

2026-10-05 22:33 — orchestrator — W1 integration — green (M0, M1, M3, M4, M5 committed; M2 zones landed)
- Commits: M4 frontend 32d55d5; Arrow.label contract 6f7df26 (backend fills it, frontend prefers it); M5 tutor c8f84b2; config zone_mimics + validator keys applied.
- Verified live: API on :8000 (offline, 3,578 cases) + web on :5173; walked onboarding → real case → zoom/loupe → 2 marks → submit → reveal (4 outlines, arrows, chips, facts card) in the browser; screenshots tests/e2e/__screenshots__/live-0*.png (gitignored, real films).
- After zones: smoke on data/processed shows full relative_location strings and zone-step arrows; orientation_report: right lung left of left lung in 100% of 3,427 segmented cases, 29 orientation_suspect.
- Full suite at last run: 240 backend + 45 pipeline + 25 shared + 34 vitest green.
- Running: qa-reviewer gate (M1/M3/M4/M5), frontend M6/M7, vision-ml features/CTR/b0, eval dry-run harness.
- HUMAN CHECKPOINT pending: no .env/API key yet → live debrief smoke (est. ≤ $0.42) waits for Yash.


2026-10-05 23:40 — eval-scientist — M7 (harness, DRY RUN only; no live API call made) — green
- Files: eval/{common,llm,adapters,checks,render,scenarios,reference_tutor,vlm_localization,faithfulness,misstype_sensitivity,pilot_analysis,report}.py, eval/{judge_prompt,ablation_prompt}.md, eval/tests/ (45 tests), eval/reports/* (dry-run/synthetic, titled + watermarked), eval/samples/{review_queue,faithfulness_debriefs}.dryrun.jsonl. Log: logs/eval_dryrun.log.
- Verified: `uv run pytest eval -q` → 45 passed (autouse guard: constructing anthropic.Anthropic raises); `ruff check eval` + `ruff format --check eval` clean. Scripts run through the PRODUCTION engines (scoring, search, tutor facts/service/validator/templates via eval/adapters.py; G client = production AnthropicTutorClient with an injected caching SDK stand-in). Scripted behaviours classified as intended: 38/38 fixtures, 89/89 (faithfulness) and 153/153 (misstype) on ChestX-Det masks.
- Live estimates (list prices from the claude-api skill table; `--price` overrides): VLM strict n=43 → $0.79 exp / $3.59 worst; VLM `--selection labeled` n=175 → $3.22 / $14.59; faithfulness 89 scenarios (G + U on sonnet-5-5, judge opus-5-5) → $10.11 / $23.62 (> $5: needs Yash's checkpoint; `--judge-model claude-sonnet-5-5` ≈ $7.4). Live runs print the estimate and exit unless `--yes`; hard-stop at --max-cost on actual usage.
- DECISION: VLM case selection. Strict SPEC rule ("exactly one focal finding") leaves 43 bench cases and ZERO pneumothorax (bench has 31 pneumothorax cases, all multi-finding). Added `--selection single-label` (n≈79) and `--selection labeled` (case contains the label; asked about that label; hit = any instance of it; 25/label × 7 = 175). Default stays strict; recommend `labeled` for the slide.
- DECISION: condition U gets the radiograph with learner marks only (expert outlines and finding-centred crops encode location), label names, learner marks; same model, schema, production cards block, effort ("low") and max_tokens (1200) as G; one call (validator-guided regen would leak truth). No server-side model fallbacks in eval calls (keeps answers attributable to the named model). Judge sees FACTS + debrief JSON only, blind to condition. Infra failures (timeouts/API errors) are excluded and counted; max_tokens/refusal count as failures.
- DECISION: dry runs write eval/samples/review_queue.dryrun.jsonl; only a live run writes eval/samples/review_queue.jsonl (so /review never shows mock items as real). Item = {item_id "faith:<scenario>", item_type "debrief", case_id, image_path, behaviour, learner, facts, debrief, source, validator, dry_run, model, condition "G"}.
- NOTE (tutor/backend): backend.app.tutor.client's process-wide 30 calls/min limiter makes excess calls fall back to templates silently (the eval injects its own limiter). DEBRIEF_MAX_TOKENS=1200 with adaptive thinking may truncate → template; the live faithfulness run reports this rate ("A model call hit max_tokens or refused").
- Next: orchestrator/Yash cost checkpoint → `make eval-vlm ARGS="--selection labeled --yes --max-cost 5"`, `make eval-faith ARGS="--yes --max-cost 12"`, then `make report`. After M2 lands (sides/zones), re-run so side/zone metrics are populated.

2026-10-05 22:29 — tutor-prompt-engineer — M5 (offline parts; no live call made) — green
- Files: backend/app/tutor/{vocab,cards,prompts,facts,render,client,validator,templates,cache,service,hints,ask,smoke}.py; backend/app/prompts/{debrief_system.md (v1, SPEC §8.3 verbatim), ask_system.md (v1)}; content/teaching_cards/*.yaml (13 cards, ai_draft) + _zone_mimics_draft.yaml; tests backend/app/tests/test_tutor_*.py + _tutor_helpers.py (inside existing testpaths; nothing to add).
- Verified: `uv run pytest backend/app -q -k tutor` → 158 passed (mocked clients only; autouse guard makes constructing a real anthropic.Anthropic fail); `uv run pytest -q` → 409 passed, 6 skipped; `ruff check`/`ruff format --check backend/app/tutor` clean. Validator tests seed every error kind (side word, sentence laterality, zone/lobe/rib level, "pneumonia", non-GT label, chest tube/treat/follow-up CT/3 cm/12mm/"this patient has"/prognosis/urgent, extra/missing/duplicate id, wrong result, overcall ids, 20-word headline, >160 words, verdict, fact_ids, raw zone ids) and each is caught.
- Real-data robustness (offline, no API): templates for all 3,578 cases × scripted behaviours = 10,123 debriefs → 0 validator failures. Dry-run smoke (`python -m backend.app.tutor.smoke --n 10 --max-cost 1`) on 10 bench cases incl. image rendering → 0 failures.
- SEAM fixed (orchestrator note): template headline counts localized findings (found + mislabeled + pattern_found) like backend/app/facts_card.py; all-localized-but-mislabeled → "You found it, but the label needs another look." E743 lint fixed.
- SDK check: anthropic 1.11.0 `messages.create(output_config={"format": {"type": "json_schema", "schema": ...}, "effort": ...})` exists as SPEC §8.5 says; used verbatim. Schema = shared/schemas/debrief_output.json minus $schema/$id/title/description (constant). Effort "low" by default (env BLINDSPOT_TUTOR_EFFORT; "none" omits it). Timeout 12 s, max_retries=0 in SDK, one manual retry on 5xx/529/connection errors, no retry on timeout/4xx; refusal/max_tokens → template. Rate limit = BLINDSPOT_MAX_LIVE_CALLS_PER_MIN (process-wide sliding window).
- DECISION: Radiopaedia link check is inconclusive: radiopaedia.org returns the same ~36.6 KB 200 page for every slug, including a bogus control (bodies discarded, nothing parsed). Kept 11 well-known article URLs with review.notes asking the reviewer to click-confirm; mass and calcification set to null (slug uncertain).
- DECISION: size words from area_frac: small < 0.2%, medium < 2%, large ≥ 2% (text "small (about 0.05% of the image)"); difficulty easy ≤ −0.5 < moderate < 0.5 ≤ hard. Never cm.
- DECISION: verdict semantics (in the cached field guide + validator R8): missed_normal_call = learner called an abnormal film normal (also accepts "missed"); normal film with marks/ticks → overcall (also accepts missed_normal_call).
- DECISION: validator R5 allowed set = GT ∪ learner labels ∪ related groups ∪ confused-with ∪ any term in the involved cards' text or the zone mimics of zones in FACTS. Extras beyond §8.6: sentence-level laterality outside where_to_look, no lobes/rib levels in locations, R8 (verdict, fact_ids, empty fields, raw zone ids), tutor safety regexes (prognosis, surgery, emergency, medications, thoracentesis, "the patient has/should…").
- DECISION: R7 on crowded films: +6 words per finding above 8 (98.4% of cases have ≤ 8, so 160 applies to them); templates gain a "tiny" chip-wording level. Defaults in validator.py, overridable by config keys below.
- DECISION: prompt_version = "v1+<sha8 of the cached cards block>" (card text edits invalidate cached debriefs; review-status changes do not). Template rows are never served from cache; templates are never cached.
- CONTRACT CHANGE REQUEST: zone_mimics content for config/review_areas.yaml (replace the empty block; the tutor reads config first and falls back to content/teaching_cards/_zone_mimics_draft.yaml while config is empty):
```yaml
zone_mimics:
  status: ai_draft
  entries:
    right_upper_zone: [Overlap of the first rib and the clavicle, Costal cartilage of the first rib, Crossing points of the upper ribs]
    left_upper_zone: [Overlap of the first rib and the clavicle, Costal cartilage of the first rib, The normal aortic knob at the edge of the mediastinum]
    right_mid_zone: [Normal vessels seen end-on, Crossing points of ribs, Nipple shadow]
    left_mid_zone: [Normal vessels seen end-on, Crossing points of ribs, Nipple shadow]
    right_lower_zone: [Nipple shadow, Edge of the breast soft tissue, Normal vessels crowded together at the lung base]
    left_lower_zone: [Nipple shadow, Edge of the breast soft tissue, Normal vessels crowded together at the lung base]
    right_apex: [Overlap of the first rib and the clavicle, Costal cartilage of the first rib, Companion shadow running along the upper ribs]
    left_apex: [Overlap of the first rib and the clavicle, Costal cartilage of the first rib, Companion shadow running along the upper ribs]
    right_costophrenic_angle: [Fat or soft tissue filling the angle, Edge of the breast soft tissue, Skin fold]
    left_costophrenic_angle: [Fat or soft tissue filling the angle, Edge of the breast soft tissue, Skin fold]
    right_periphery: [Skin fold, Medial border of the scapula, Edges of overlapping ribs]
    left_periphery: [Skin fold, Medial border of the scapula, Edges of overlapping ribs]
    right_hilum: [Normal pulmonary arteries and veins seen end-on, Vessels crossing over each other, A main airway seen end-on as a ring]
    left_hilum: [Normal pulmonary arteries and veins seen end-on, Vessels crossing over each other, A main airway seen end-on as a ring]
    retrocardiac: [Edge of the normal descending aorta, Spine and the soft tissue beside it, Normal vessels behind the heart]
    cardiac_silhouette: [Fat pad beside the lower heart border, Breast tissue overlying the heart, The normal heart borders]
    mediastinum: [The normal aortic knob, The trachea and main airways, The normal edge of the superior vena cava]
    subdiaphragmatic: [Gas in the stomach or bowel below the diaphragm, Muscle slips of the diaphragm, Overlapping rib edges]
    right_clavicle: [The rhomboid fossa (a normal notch under the clavicle), Overlap of the first rib and the clavicle, Soft tissue at the base of the neck]
    left_clavicle: [The rhomboid fossa (a normal notch under the clavicle), Overlap of the first rib and the clavicle, Soft tissue at the base of the neck]
    spine: [Overlapping edges of the vertebrae, The normal line of soft tissue beside the spine, Air in the trachea over the spine]
```
- CONTRACT CHANGE REQUEST (optional): config/scoring.yaml `validator:` add `total_limit_base_findings: 8` and `words_per_extra_finding: 6` (same as code defaults) so the crowded-film allowance is configurable.
- Open: real findings have side/zones = None until M2 writes them, so live debriefs before M2 carry no location facts; run the live smoke after M2. Radiopaedia URLs need a human click-check. Cards are ai_draft (Sri review Tue).
- Next (needs the HUMAN CHECKPOINT first): `uv run python -m backend.app.tutor.smoke --n 10 --max-cost 1.00 --live` → eval/samples/debriefs_smoke.jsonl (worst-case estimate $0.42; prints p50/p90 latency, first-try pass, template fallbacks).

2026-10-05 22:40 — frontend-engineer — M4 reading room — green
- Files: frontend/src/{viewer/{Viewer,RevealLayer,MarkPopover}.tsx, coords.ts, telemetry.ts, heatmap.ts, arrows.ts (+ tests), read/readState.ts (+test), rail/*, pages/*, app/{Shell,ErrorBoundary}.tsx, state/session.ts, api/{client,labels}.ts, api/mock/*}, scripts/gen-mock.mjs, public/mock/ (10 SYNTHETIC drawn-shape PNGs from pipeline fixtures), tests/e2e/reading_room.spec.ts (qa-reviewer: new spec in your dir).
- Verified: `tsc --noEmit -p tsconfig.app.json` clean; `npm run lint` 0 warnings; vitest 34 passed (coords incl. click→image ≤ 2 px at 1×/3× for 1024², 256², 2048×1536; telemetry throttle/cap/downsample; marks reducer; arrows/label placement); `npm run build` ok (mock is a lazy chunk). Playwright mock mode: 11 passed + 1 skipped (real-only); real API with BLINDSPOT_OFFLINE=1: 12 passed incl. no-GT-before-submit. Telemetry 181–217 events / 10 s of movement. Screenshots (synthetic only) in tests/e2e/__screenshots__/m4-01…m4-10; looked at all of them, plus real-film reveals.
- DECISION: mock mode = VITE_MOCK=1, `?mock=1` (sticky per tab), or /api/health unreachable / 0 cases; header shows "Synthetic demo cases". DECISION: next case is prefetched right after submit (backend /next is idempotent, so a reload returns the same open attempt) and its image preloaded. DECISION: single click waits 250 ms before placing a mark so a double-click can reset the view instead. DECISION: pointer throttle 33 ms with 4 ms frame-jitter tolerance (strict 33 ms gives ~25 Hz on 60/120 Hz pointers). DECISION: server heatmap PNG is re-coloured client-side (any greyscale/alpha density works); without it, client gaussian splats (σ = 0.035·W). DECISION: loupe on by default in practice/drill/review, off in assessment. `A` (show anatomy) hidden: no zone outlines in the API yet.
- Open: (1) tests/e2e/playwright.config.ts cannot resolve @playwright/test from tests/e2e — run with `NODE_PATH=$PWD/node_modules` from frontend/ (orchestrator/qa: add to `make e2e`). (2) Gitignore `.playwright-mcp/` (MCP scratch shots include real dataset images) and do not commit tests/e2e/__screenshots__ produced by E2E_REAL=1 runs (real images). (3) Backend arrow `text` is a long sentence and says "unknown region" until M2 zones land; the film shows the last clause ≤ 46 chars, full text as tooltip — a short `label` field would read better. (4) M0 smoke spec still passes (onboarding shows `data-testid=health`).
- Next: M6 dashboards (/progress, /cohort) and M7 /review on the real API.

2026-10-05 22:12 — orchestrator — M1 + M3 verified and committed — green
- M1: pytest pipeline 38 passed; contact sheet visually checked (heart on image right, polygons tight). Commit ae4aad1.
- M3: pytest backend 85 passed; smoke OK on fixtures and on data/processed (3 real cases, template debriefs ready). Commit de68101.
- SEAM (open): case with a mislabeled finding — facts card says "found 1 of 4", template debrief headline says "0 of 4". Tutor templates should count localized (found + mislabeled) consistently with backend/app/facts_card.py, or the headline should say "localized". Assign: tutor-prompt-engineer.
- Lint: backend/app/tests/_tutor_helpers.py E743 (`def O`) — tutor-owned.


2026-10-05 23:55 — backend-engineer — M3 (+ M6 engines/analytics) — green
- Added backend/app/{config,cases,db,engine,facts_card,services,tutor_bridge,smoke}.py, scoring/{hit,matching,outcomes,scores}, search/{dwell,misstype,coverage,heatmap,spatial}, adaptive/{elo,selector}, analytics/{learner,cohort,froc,calibration,blindspot_map}, routes/{sessions,attempts,cases,dashboard,review,pilot,dev,about}; main.py mounts `pilot` (POST /api/sus).
- Verified: `uv run pytest backend -q` → 85 passed (whole repo 208 passed); `ruff check`/`ruff format --check` clean on backend excluding tutor/; `make db-reset` twice OK; `uv run python -m backend.app.smoke` (in-process) and `--base http://127.0.0.1:8765` against uvicorn on fixtures → SMOKE OK, debriefs `ready` from tutor templates.
- Selector simulation (30 seeded SYNTHETIC learners, 40 cases): mean realised success 0.744 (range 0.60–0.85); prevalence within ±5% over 200 draws at 0.3/0.5/0.7; no assess/bench case served.
- Data root: BLINDSPOT_PROCESSED_DIR (else data/processed). Real data with the fixture layout should drop in; missing zones file → approximate fixed-fraction zones (approximate=true).
- DECISION: related-group label = partial label credit 1 − costs.related (0.7); "not_sure"/other = 0. Pattern accuracy = correct / |GT patterns ∪ selected|. On normal cases a pattern_false counts as a false positive (score and success).
- DECISION: prevalence draw is nudged by the session's abnormal-count deficit (p = prev + 0.25·deficit, clipped) so realised prevalence tracks the setting; ε-exploration stays within the drawn class.
- DECISION: QA flags allowlist {synthetic, anatomy_failed, zones_approximate, approximate_zones}; any other flag excludes a case from Practice (falls back to all practice cases if nothing is left).
- DECISION: assessment order = splits.json[mode] if it is an ordered list, else sorted ids shuffled with seed 0. /summary returns 409 until every assessment case is submitted. Hints → 403, debrief → "disabled", ask → 403 in assessment. No Elo updates from assessment.
- DECISION: GT-leak test checks keys ∈ GROUND_TRUTH_KEYS, no "#F" ids, and none of the case's label/zone/location strings; case_id (`syn_…`) itself is allowed (it is in the NextCase contract).
- Schema extensions to §13.1: attempts.idx, attempts.hint_log_json; debriefs.status/error/provenance; `flags` table (POST /api/attempts/{aid}/flag → /review queue). Extra routes: GET /api/dev/cases, GET /api/dev/cases/{id} (QA only, exposes GT by design).
- Learner reuse: settings.learner_id (if it exists) or participant_code → same learner; else a new learner per session.
- Open: /api/dev/* is unauthenticated (exposes GT); FastAPI 0.142 wraps included routers (tests flatten via original_router); review curated queue read from eval/samples/review_queue.jsonl or data/review_queue.jsonl (eval-scientist: one JSON object per line).
- Next: rerun the smoke script on data/processed once M1/M2 land; frontend can switch from mock API to the live API.

2026-10-05 22:09 — vision-ml-engineer — M2 — started
- Code + tests first: pipeline/anatomy/{common,zones,locate,orientation,segment,overlay,synthetic}.py, pipeline/features/{lesion,ctr,difficulty}.py; tests pipeline/tests/test_zones*.py, test_features.py (synthetic masks; 98 pipeline tests green, ruff clean).
- ML deps installed (`uv sync --extra dev --extra eval --extra ml`: torch 2.14.1, torchvision 0.29.1, torchxrayvision 1.5.5). TXV weights in ~/.torchxrayvision: PSPNet 273 MB, DenseNet densenet121-res224-all 28 MB. Device: MPS.
- EMPIRICAL: PSPNet outputs are LOGITS (first real batch min −28.2, max 14.7) → mask = sigmoid > 0.5 ⇔ logit > 0; predicted at 512², nearest-upsampled to 1024. On real images TXV "Right Lung" centroid is at image-left (x≈329/1024) → names look patient-side (orientation.py decides on all cases).
- Segmentation running in background (`logs/anatomy.log`): 3,427 in-scope cases, ~2.5 img/s (~150/min), ETA ~22 min. Order: assess_A, assess_B, practice[:800 by id], bench, practice[rest]; holdout skipped.

2026-10-05 22:05 — data-engineer — M1 — green
- Files: pipeline/ingest_chestxdet.py, pipeline/splits.py, pipeline/qa_contact_sheet.py, pipeline/tests/test_ingest.py, test_splits.py, test_ingest_acceptance.py (skips without data/). Generated (gitignored): data/processed/{images/,masks/,cases.jsonl,taxonomy_report.json,ingest_stats.json,splits.json}, data/qa/contact_sheet_{abnormal_1,abnormal_2,normal}.png + contact_sheet_index.json.
- Source: HF `MedOtter/ChestX-Det` (primary; no fallback needed). Download 1.431 GB (1,431,262,296 B, 9 parquet shards, 317 s). Output: images 1.3 GB, masks 51 MB. Ingest takes 28 s with 6 workers; resumable and idempotent (a re-run gives a byte-identical cases.jsonl and rewrites 0 files; it re-applies an existing splits.json and refuses to clobber M2 fields without --force).
- Counts: 3,578 cases (train 3,025 / test 553), 0 excluded. 611 normal (train 547 / test 64), 2,967 abnormal. 13 unique syms, all mapped. 9,639 raw instances → 9,637 after merge (2 merged away). Polygon masks: 100% (0 bbox fallbacks, 0 clipped, 0 dropped). qa_flags: merged_duplicate_instances ×2 (cxd_40738 emphysema, cxd_57467 nodule). All 42 RGBA-upstream images are already L in the mirror.
- Per-label instances: consolidation 2563, effusion 2112, nodule 986, fibrosis 739, fracture 660, pleural_thickening 631, calcification 348, atelectasis 340, emphysema 297, cardiomegaly 293, diffuse_nodule 290, pneumothorax 211, mass 167. Instances per abnormal case: median 3, max 36. area_frac p5 / p50 / p95 = 0.00064 / 0.018 / 0.133.
- Splits (seed 20261008): practice 2874, holdout 151, assess_A 20, assess_B 20, bench 513. Forms are 8N/12A each with the same mix: pneumothorax 2, effusion 2, consolidation 2, nodule 2, atelectasis 1, mass 1, fracture 1, cardiomegaly 1. Size-proxy gap 0.0004.
- Verified: `BLINDSPOT_FULL_DATA_CHECK=1 uv run pytest pipeline -q` → 45 passed (100% of cases.jsonl validates as Case; all 9,637 masks non-empty, 1024², and bbox == mask extent; splits disjoint and complete); `ruff check` clean on my files.
- Next: vision-ml M2 can start on data/processed/cases.jsonl. After `make features` fills b0, `python -m pipeline.splits --rebalance` re-matches A/B to a mean-b0 gap ≤ 0.1. It moves only test cases among A/B/bench; practice and holdout stay fixed. Clinical review of data/qa contact sheets by Sri.

DECISION: license_tag = "NIH ChestX-ray14 images (attribution required) / ChestX-Det annotations Apache-2.0" (not "CC-BY-like"): the HF card and upstream Deepwise LICENSE say Apache-2.0. The attribution string includes the NIH link, Wang et al. CVPR 2017 and Lian et al. TMI 2021 (NIH terms require all three; /about must show them).
DECISION: the HF per-class `<label>_mask` columns are NOT ground truth. 23 (image, label) pairs have IoU < 0.9 against the union of the instance polygons. In each one the column has holes where same-class instances overlap (even-odd fill; parity-of-instances matches the column at IoU > 0.96). The instance polygons from annotation_json are used, as SPEC §3.1 says.
DECISION: duplicate merge = same label and mask IoU > 0.6, transitive union. The merged polygon is the largest external contour of the union and the mask is the full union. Only 2 merges in the whole dataset.
DECISION: assessment-form "label mix" is keyed on primary_label = the most salient focal label, ordered pneumothorax > mass > fracture > nodule > atelectasis > calcification > pleural_thickening > effusion > consolidation, else the pattern label. Candidate tiers in preference order: single focal finding; one focal + patterns; several instances of one focal label; single pattern finding; two focal findings with different labels. Busier cases are never used. Reason: the test split has only 1 single-finding pneumothorax and 1 single-focal fracture, so a strict single-finding rule left both labels out of the forms. 9 of 12 abnormal cases in A and 8 of 12 in B are single-finding. Target mix is FORM_LABEL_MIX in splits.py and should move to config/ if the orchestrator wants it tunable.
DECISION: holdout = 5% of train (151), stratified by normal / primary_label, seeded. Pre-M2 the A/B balance uses a size proxy (−log10 of the smallest focal area_frac) in place of b0.
NOTE for M2/backend: mask_path and image_path are relative to data/processed/. Mask files are named <case_id>_F<n>.png ('#' replaced by '_'). Bbox is half-open, (x0, y0, x1, y1) = (min, min, max+1, max+1) of mask pixels; the centroid is the mean pixel (x, y). Re-running ingest after M2 is guarded: it needs --force and would erase M2 fields.

2026-10-05 22:30 — tutor-prompt-engineer — M5 — started
- Building backend/app/tutor/ (offline parts only; no live API call until the orchestrator's checkpoint).

TUTOR INTERFACE (tutor provides) — implemented and tested (M5 offline); matches "backend expects" below. All functions are importable now.
```python
# backend/app/tutor/facts.py
def build_facts(*, case, submit, outcomes, spatial_relations, search, mark_zones, level, history) -> DebriefFacts
#   spatial_relations: SpatialRelation | dict ({"from","to","text"} or {"from_mark","to_finding","text"}); from_mark None skipped
#   search: FactsSearch | SearchSummary | dict. Outcome targets "F1" or "<case>#F1" (normalized to short ids).
# backend/app/tutor/service.py
def generate_debrief(facts, case, *, attempt_id, submit, offline, cache_get, client=None, data_root=None, images=None) -> dict
#   -> {"debrief": DebriefOutput, "source": live|cache|template, "provenance", "validator", "latency_ms", "model",
#       "prompt_version", "cache_key", "input_tokens", "output_tokens"}. Never raises. Does not write the cache (you do).
#   cache_get rows with source == "template" are ignored; hits are re-validated. client may be our TutorClient
#   (.complete) or an Anthropic-like SDK object (.messages.create). data_root defaults to backend.app.cases.processed_root().
# backend/app/tutor/hints.py
def hint(level, case, marks, telemetry, zones, cfg=None, cards=None) -> str   # H1 uses backend search.coverage (fallback: local dwell)
# backend/app/tutor/ask.py
def ask(question, facts, case, *, previous, offline, client=None, images=None, data_root=None) -> dict
#   -> {"answer", "source": live|template, "validator", "latency_ms", "model"}; answer_question(...) -> AskResponse
# backend/app/tutor/cards.py
load_cards() -> dict[str, TeachingCard] · lowest_provenance(labels, cards=None, include_zone_mimics=False) · load_zone_mimics()
all_cards_text() · content_hash()
# backend/app/tutor/validator.py      validate(out, facts, cards=None, cfg=None, *, zone_mimics=None) -> ValidationResult{ok, errors}
#                                     validate_ask(text, facts, cards=None, cfg=None) · allowed_verdicts(facts) · total_word_limit(facts)
# backend/app/tutor/templates.py      template_debrief(facts, cards=None, zone_mimics=None, cfg=None) -> DebriefOutput
# backend/app/tutor/cache.py          cache_key(...) · cache_key_for_facts(facts, model, prompt_version) · MemoryStore · SqliteStore
# backend/app/tutor/render.py         render_images(case, facts, marks, data_root) -> {"full","crop","crop_outlined": PNG bytes}
# backend/app/tutor/client.py         AnthropicTutorClient(model=None, *, timeout=12, effort="low", sdk_client=None, limiter=None)
#                                     MockClient(responses) · RateLimiter(per_min) · debrief_schema() · LiveCallError(kind)
```

2026-10-05 22:20 — backend-engineer — M3 — started
- Building engines (scoring/, search/, adaptive/), cases repo, SQLite, routes on synthetic fixtures. Interface for the tutor below.

TUTOR INTERFACE (backend expects) — backend/app/tutor_bridge.py imports these lazily; anything missing → graceful fallback.
All types from shared.contracts. Finding/mark ids in facts are short ("F1", "M1"). Never import backend.app.routes from tutor code.
```python
# backend/app/tutor/facts.py
def build_facts(*, case: Case, submit: AttemptSubmit, outcomes: list[Outcome],
                spatial_relations: list[SpatialRelation], search: FactsSearch,
                mark_zones: dict[str, str | None],      # "M1" -> zone id at the mark (patient side) or None
                level: str, history: dict[str, Any]) -> DebriefFacts
# backend/app/tutor/service.py
def generate_debrief(facts: DebriefFacts, case: Case, *, attempt_id: str, submit: AttemptSubmit,
                     offline: bool, cache_get: Callable[[str], dict | None],   # cache_key -> stored row dict or None
                     client: Any | None = None) -> dict
#   returns {"debrief": DebriefOutput, "source": "live"|"cache"|"template", "provenance": ReviewStatus | None,
#            "validator": dict, "latency_ms": float, "model": str | None, "prompt_version": str,
#            "cache_key": str, "input_tokens": int | None, "output_tokens": int | None}
#   backend stores it in the `debriefs` table; cache_get looks up a previous row with that cache_key
#   (returns {"output_json": <DebriefOutput dict>, "source", "model", "prompt_version", "validator_json"}).
# backend/app/tutor/hints.py
def hint(level: int, case: Case, marks: list[Mark], telemetry: list[TelemetryEvent],
         zones: dict[str, np.ndarray]) -> str          # level 1..3; may use backend.app.search.coverage.review_coverage
# backend/app/tutor/ask.py
def ask(question: str, facts: DebriefFacts, case: Case, *, previous: list[dict],   # [{"question","answer"}]
        offline: bool, client: Any | None = None) -> dict   # {"answer": str, "source": "live"|"template"}
```
Backend helpers the tutor may import: backend.app.cases.get_repo() (.get(case_id), .zones(case_id) -> (masks, meta), .mask(case, finding)),
backend.app.config.review_areas()/taxonomy()/scoring(), backend.app.search.coverage.review_coverage(...).

2026-10-05 21:47 — orchestrator — M0 — green
- Added shared/schemas (10 files), shared/contracts.py (Pydantic mirrors + GROUND_TRUTH_KEYS), shared/tests/test_contracts.py (24 tests), Makefile, backend scaffold (settings.py, main.py w/ /api/health + router autoload), frontend Vite+React+TS shell (router, API client, tokens.css, coords.ts + vitest, generated types via `npm run gen:types`: 33 types), tests/e2e/playwright.config.ts + smoke spec.
- Verified: `uv run pytest -q` → 24 passed; `ruff check` clean; `tsc --noEmit` clean; vitest 3 passed; `npm run build` ok; `curl /api/health` → {"ok":true,"offline":true,"cases":0}.
- DECISION: project pinned to Python 3.12 (system 3.14 has no torch wheels). DECISION: API ids for findings/marks are short (`F1`/`M1`); `source: synthetic` + `syn_` ids allowed for fixtures.
- Next: launch W1 (data-engineer M1, backend M3 engines, frontend M4 viewer, tutor M5).

