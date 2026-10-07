# Volumetric (CT / MR) cases — build plan (branch `volumetric`)

Goal: the same Blindspot loop (pick what you see → click where → how sure → submit → reveal → miss types → facts-only debrief)
for CT and MR volumes. Learners choose the scan type on the start screen; nothing else in the UI changes shape.
The X-ray experience stays byte-identical for `modality: cxr` cases.

## Contract (frozen; shared/schemas, shared/contracts.py, frontend/src/types/contracts.ts)
- `Case.modality` cxr|ct|mr, `body_region`, `volume {shape [nz,ny,nx], spacing [sz,sy,sx] mm, window {wc,ww}, data_path, mask_path, labels {value→id}, sequence}`,
  `provenance {dataset, segmented_by, readers, institution, license, citation, url, grade}` → badge "Segmented by ___ (___)".
- `Finding` adds `label_value(s)`, `centroid3 [x,y,z]`, `slice_range [z0,z1]`, `measure {long_mm, slice}`, `components`, `volume_mm3`.
  Organ labels are NOT findings: they become zones (config/review_areas.yaml `volumetric`).
- Marks carry `plane`, `slice`, `voxel [x,y,z]`; telemetry adds `plane`, `slice` and kinds slice/plane/window; submits add `measurements`.
- Reveal adds `maskvol_url` (post-submit only), `modality`, `provenance`, per-finding `slice_range/measure/size_verdict`, `SearchSummary.slice_dwell`, `slices_viewed_pct`, `finding_slices_viewed`.
- Outcome result `unmatched`: a mark the reference does not label (public CT sets are not exhaustive) — reported, never penalised.
- NextCase: `case.modality`, `case.volume {shape, spacing, window, data_url, presets}` — voxels only, never the mask.

## Files on disk (pipeline → data/processed)
- `cases_msd.jsonl` (separate file; the case repo loads every `cases*.jsonl`), `volumes/<case_id>.i16.gz` (int16 LE, z,y,x), `masks/<case_id>.u8.gz`,
  `previews/<case_id>_axial.png` for QA. Slabs cropped to the body and centred on the finding (~144 px in-plane, ≤ 32 slices; lung 176).
- Provenance from config/provenance.yaml by MSD task id. Splits: practice / assess per modality; bench examples for the reference bank.

## Slice numbering
`slice`, `slice_range`, `measure.slice`, telemetry `slice` and `Mark.slice` are 0-based indices in the contract. EVERY human-facing string (viewer "Slice 8 of 28", facts card, debrief, hints, tutor templates) is 1-based: show index + 1.

## Grading (config/scoring.yaml `volumetric`)
- Hit: voxel lookup in the mask; tolerance 2 % of the larger in-plane FOV (mm); ±2 slices; a mark inside a DIFFERENT labelled structure is never rescued.
- Miss types from slice dwell: finding's slices on screen < 800 ms → missed_search; < 2000 ms or cursor never within 15 mm → missed_recognition; else missed_decision.
- Size: asked only for mass-like labels after marking; correct within max(3 mm, 20 %).
- Score weights unchanged; `unmatched` marks neither score nor penalise.

## Datasets (Medical Segmentation Decathlon, CC BY-SA 4.0; streamed tar → only chosen cases hit disk)
- Task07 Pancreas (pancreatic_tumour; zone pancreas) · Task08 HepaticVessel (liver_tumour; zone hepatic_vessels) · Task01 BrainTumour (brain_tumour with components oedema / core / enhancing; sequence T1c).
- Later: Task03 Liver, Task06 Lung, Task10 Colon, KiTS23.

## Ownership
pipeline/volumetric/** (data) · backend/app/** (backend) · frontend/src/viewer/volume/**, viewer, rail, read (viewer agent) · frontend pages/app/dashboard/reference (pages agent) · backend/app/tutor, prompts, content/teaching_cards (tutor).
Agents do not commit; the orchestrator commits on the `volumetric` branch. Nothing deploys until Yash says so.
