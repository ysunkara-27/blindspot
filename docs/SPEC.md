# Blindspot — Build Spec v1.0

Monday, October 5, 2026. Event: UVA School of Medicine AIM × Anthropic hackathon. Demo night: Thursday, October 8, 6:00–8:00 PM, MEB Auditorium. **Code freeze: Thursday 2:00 PM.**

> **For:** the Claude Code orchestrator and the project subagents in `.claude/agents/`.
> **Authority:** this file defines *what* to build and *how we know it works*. `CLAUDE.md` defines the rules and wins on any conflict. Where this spec is silent or ambiguous, choose the simplest option that keeps the non-negotiables, log the decision in `docs/PROGRESS.md`, and keep moving.
> **Evidence and citations:** `docs/RESEARCH.md`. **Team plan, pilot, demo script:** `docs/DEMO_AND_PITCH.md`.

---

## 0. Summary

Blindspot is a chest X-ray **perception trainer**. Learners read real radiographs annotated by radiologists and mark what they see. On submit, Blindspot shows them where the findings were *and how their search went wrong*:

1. **Scores localization** against expert pixel masks (not multiple choice).
2. **Replays the search**: a hardware-free search trace built from the cursor-following loupe, zoom and pan, mapped onto anatomy (apices, hila, retrocardiac region, costophrenic angles, below the diaphragm).
3. **Classifies every miss** with the Kundel perception taxonomy — *search error* (never looked there), *recognition error* (looked past it), *decision error* (looked, judged it normal) — or as an *interpretation error* (found it, named it wrong), and every extra mark as an *overcall*.
4. **Claude debriefs** the learner in about 100 words, using only facts the system computed plus teaching cards a clinician reviews. A deterministic validator checks every debrief against the facts before it is shown.
5. **Adapts**: an Elo/Rasch engine picks the next case near the learner's edge of competence, controls normal/abnormal prevalence, and powers learning curves.

Claude is the voice; the system is the brain. That is our answer to "couldn't you just paste the X-ray into Claude?" (RESEARCH.md §4 explains why that fails).

### 0.1 Scope tiers

**P0 — demo-critical (must work by Wednesday night)**
- ChestX-Det ingest into canonical cases with instance masks; normals included.
- Anatomy segmentation into zones and review areas; every finding described in patient-side anatomical language.
- Reading room: zoom, pan, brightness/contrast, invert, loupe, marks (label + confidence), "Call it normal", global findings, telemetry.
- Scoring (mask hit-test + Hungarian matching), miss-type engine, review-area coverage.
- Reveal sequence (search trace → expert outline → arrow) plus an instant deterministic facts card.
- Claude debrief with structured output, validator, cache, and offline template fallback.
- Adaptive next case (Elo); learner dashboard (learning curve, miss-type mix).
- `/about` page with data attribution and the education-only disclaimer. Demo playlist. Projector mode.

**P1 — differentiators (aim: done Wednesday)**
- Hint ladder (first hint = the review areas you haven't looked at yet). Ask-the-tutor follow-ups.
- Calibration plot, FROC curve, blind-spot map. CTR overlay for cardiomegaly. "Show anatomy" toggle.
- Expert review page (`/review`) for debriefs and teaching cards.
- Evaluation: VLM localization benchmark, debrief faithfulness eval with grounding ablation, pilot tooling (assessment A/B + SUS) and analysis.
- Cohort dashboard (instructor view).

**P2 — stretch, only after P0 and P1 are green:** VinDr-CXR via Kaggle; CXAS fine anatomy (lobes, ribs); detector training as an "AI second reader"; webcam gaze validation; MSK fracture module; hosted deployment. See §18.

### 0.2 Thursday definition of done
- A judge can sit down, read 3 cases in under 4 minutes, and see their search trace, a correct miss type, a grounded Claude debrief, and their learning curve move.
- We can show numbers we actually measured: raw VLM localization versus radiologist truth; debrief faithfulness with versus without grounding; radiologist ratings of debriefs; a small, honestly labeled pre/post pilot.
- The entire demo runs offline if the network dies.

---

## 1. Product

### 1.1 Problem (sources in RESEARCH.md §1)
- 60–80% of diagnostic radiology errors are perceptual: the abnormality is on the image but is not seen. Reading blind spots (apices, hila, behind the heart, below the diaphragm) are a classic cause.
- Only about 1 in 5 US medical schools require a radiology clerkship; in a multi-school survey, 83% of students rated their radiology teaching inadequate.
- Non-radiologists read many first-pass chest X-rays and miss subtle findings. In one emergency department study, small pneumothoraces were correctly identified about half the time.
- Deliberate practice with immediate feedback works (ImageSim, RadGame). What is missing is feedback on *how* the learner searched.

### 1.2 Users and the job
- **Primary:** medical students MS1–MS4. **Secondary:** EM/IM interns, PA/NP students. **Buyer:** curriculum and radiology clerkship directors.
- **Job to be done:** "Help me stop missing things on chest X-rays, and show me why I miss them."

### 1.3 Core loop (one case)
1. Case loads in a dark reading surround, fit to height. Telemetry starts.
2. Learner inspects: wheel-zoom at cursor, drag to pan, brightness/contrast, invert. The **loupe** (2.5× circle) follows the cursor by default.
3. Learner marks: click → label picker (focal labels) → confidence 1–5. Optional **Global findings** checklist (cardiomegaly, emphysema, fibrosis, diffuse nodules). Or **Call it normal** + confidence.
4. Optional hints (up to 3; each costs 5 points).
5. **Submit read** → one orchestrated reveal (≈1.2 s): search-trace heatmap fades in → expert outline draws itself → grease-pencil arrow from the nearest wrong mark to each missed finding → outcome chips appear.
6. The rail shows the **facts card** instantly (deterministic), then the **Claude debrief** (target p50 < 4 s; cached < 200 ms).
7. Optional: Ask the tutor (up to 3 questions), Show anatomy, Compare with a normal.
8. **Next case** (adaptive).

### 1.4 Modes
| Mode | Case selection | Feedback | Purpose |
|---|---|---|---|
| Practice (default) | adaptive (§9) | after every case | learning |
| Drill | one label + matched normals at a chosen prevalence | after every case | targeted practice |
| Assessment A / B | fixed 20-case set, fixed order | none until the end, then a summary | pre/post measurement |
| Review missed | the learner's past misses, spaced | after every case | consolidation |
| Instructor | — | cohort analytics | curriculum view |

### 1.5 Why this isn't "a system prompt"
Real expert-masked data (about 3,500 radiographs), a vision model that turns pixels into anatomy, behavioral telemetry, perception science (Kundel taxonomy, prevalence effects, FROC, calibration), psychometrics (Elo/Rasch), and a *verified* LLM layer (facts-only prompting, structured outputs, deterministic validator, LLM judge, clinician review). None of that exists in a chat window.

---

## 2. Architecture

```
Browser (Vite + React + TS)              FastAPI (Python 3.11)                    Offline pipeline (Python)
┌─────────────────────────────┐          ┌─────────────────────────────────┐      ┌──────────────────────────────┐
│ Viewer: zoom/pan/WL/loupe   │  REST    │ sessions, adaptive selection    │      │ ingest ChestX-Det (HF mirror)│
│ Marks, global findings,     │ ───────▶ │ scoring (hit-test, Hungarian)   │ ◀─── │ anatomy seg (TorchXRayVision)│
│ hints                       │          │ search engine (dwell, miss type)│ reads│ zones, review areas, CTR     │
│ Telemetry buffer (~30 Hz)   │ ◀─────── │ facts builder → Claude tutor    │      │ lesion features, difficulty  │
│ Reveal, facts card, debrief │ GT only  │ validator, cache, templates     │      │ splits, QA contact sheets    │
│ Dashboards, review page     │ after    │ Elo, analytics, review, SUS     │      └──────────────────────────────┘
└─────────────────────────────┘ submit   │ SQLite                          │
                                         └────────────────┬────────────────┘
                                                          │ Anthropic API: vision, structured outputs, prompt caching
```

### 2.1 Stack
- **Backend:** Python ≥ 3.11, uv, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, SQLite (sqlite3 or SQLModel), NumPy, SciPy, OpenCV (headless), Pillow, PyYAML, orjson, `anthropic` (latest SDK).
- **Pipeline/ML:** torch + torchvision (CPU or Apple MPS), torchxrayvision, scikit-image, huggingface_hub and/or datasets, pyarrow, pandas, matplotlib.
- **Frontend:** Vite, React, TypeScript (strict), TanStack Query, Zustand (or React context), Recharts, CSS modules + CSS variables (no component kit), Vitest, Playwright.
- **No Docker.** A Makefile orchestrates everything. One uv project at the repo root covers `backend/`, `pipeline/`, and `eval/`.

### 2.2 Repository layout
```
.
├── CLAUDE.md                      # rules (loaded every session and by every subagent)
├── Makefile
├── pyproject.toml                 # single uv project: backend, pipeline, eval
├── .env.example                   # copy to .env; never commit .env
├── config/
│   ├── taxonomy.yaml              # canonical labels, kinds, source maps, related groups
│   ├── review_areas.yaml          # zone ids, human names, review areas, hardness, adjacency
│   ├── scoring.yaml               # tolerances, dwell thresholds, score weights
│   ├── adaptive.yaml              # Elo constants, target success, prevalence
│   └── demo_playlist.yaml         # curated demo cases (filled Wednesday)
├── shared/schemas/*.json          # JSON Schemas = API contract source of truth
├── pipeline/
│   ├── ingest_chestxdet.py  splits.py  qa_contact_sheet.py
│   ├── anatomy/   segment.py  orientation.py  zones.py
│   ├── features/  lesion.py  difficulty.py  ctr.py
│   └── tests/
├── backend/app/
│   ├── main.py  settings.py  db.py  models.py  cases.py
│   ├── scoring/   hit.py  matching.py  outcomes.py  scores.py
│   ├── search/    dwell.py  misstype.py  coverage.py  heatmap.py
│   ├── adaptive/  elo.py  selector.py
│   ├── analytics/ learner.py  cohort.py  froc.py  calibration.py  blindspot_map.py
│   ├── tutor/     facts.py  render.py  client.py  validator.py  templates.py  hints.py  ask.py  cache.py
│   ├── prompts/   debrief_system.md  ask_system.md
│   ├── routes/    sessions.py  attempts.py  dashboard.py  review.py  dev.py  about.py
│   └── tests/
├── content/teaching_cards/*.yaml
├── frontend/src/  app/ pages/ viewer/ rail/ dashboard/ review/ api/ types/ styles/
├── eval/          vlm_localization.py  faithfulness.py  pilot_analysis.py  report.py  judge_prompt.md  tests/  reports/
├── tests/e2e/                     # Playwright
├── docs/          SPEC.md RESEARCH.md DEMO_AND_PITCH.md PLAN.md PROGRESS.md REVIEW_NOTES.md
├── data/                          # gitignored: raw/ processed/ qa/ blindspot.sqlite
└── logs/                          # gitignored
```

### 2.3 Make targets
| target | does |
|---|---|
| `make setup` | `uv sync`; install frontend deps; create `data/` and `logs/` |
| `make data` | ingest ChestX-Det → `data/processed/` (+ splits, QA contact sheets) |
| `make anatomy` | segmentation + zones (resumable; logs to `logs/anatomy.log`) |
| `make features` | lesion features, difficulty prior, CTR |
| `make dev` | backend on :8000 (reload) + frontend on :5173 |
| `make test` | pytest (all Python) + vitest |
| `make e2e` | Playwright with `BLINDSPOT_OFFLINE=1` |
| `make eval-vlm` / `make eval-faith` / `make report` | evaluation scripts (§12) |
| `make demo` | seed the demo playlist, warm caches, start with projector mode on |
| `make db-reset` | recreate the SQLite schema |
| `make lint` | ruff + eslint + `tsc --noEmit` |

### 2.4 Environment (`.env` at the repo root; template in `.env.example`)
| variable | default | notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | never printed, never committed |
| `BLINDSPOT_MODEL_DEBRIEF` | `claude-sonnet-5-5` | debriefs + ask-the-tutor |
| `BLINDSPOT_MODEL_FAST` | `claude-haiku-4-5-20251001` | optional cheap tasks |
| `BLINDSPOT_MODEL_JUDGE` | `claude-opus-5-5` | evaluation judge (or `claude-fable-5-1`) |
| `BLINDSPOT_MODEL_BENCH` | `claude-sonnet-5-5` | subject model for the VLM benchmark |
| `BLINDSPOT_DATA_DIR` | `./data` | |
| `BLINDSPOT_DB_PATH` | `./data/blindspot.sqlite` | |
| `BLINDSPOT_OFFLINE` | `0` | `1` = never call the API; cache or templates only |
| `BLINDSPOT_MAX_LIVE_CALLS_PER_MIN` | `30` | server-side rate limit |

---

## 3. Data

### 3.1 Sources, in priority order
1. **ChestX-Det (P0, primary).** Hugging Face mirror `MedOtter/ChestX-Det` (parquet): about 3,578 rows (train ≈ 3,025 / test 553), 1024×1024 images, an `annotation_json` field with per-instance `boxes`, `polygons`, and `syms` (label names), an `is_negative` flag (normal films are included), and per-class mask columns. Underlying images come from NIH ChestX-ray14; instance annotations (13 categories, boxes and masks) come from Deepwise AI Lab, labeled by three board-certified radiologists. Use `huggingface_hub.snapshot_download(repo_id="MedOtter/ChestX-Det", repo_type="dataset")` or `datasets.load_dataset(...)`. No credentials needed. Log the actual download size.
   - Use the **instance polygons** from `annotation_json` as the source of truth (they separate instances, e.g. bilateral effusions). Use the per-class mask columns only for cross-checking.
   - **Fallback A:** the original Deepwise repo (`github.com/Deepwise-AILab/ChestX-Det-Dataset`) JSON polygons + NIH images.
   - **Fallback B:** NIH ChestX-ray14 bounding-box subset (`BBox_List_2017.csv`, ≈ 984 boxes on ≈ 880 images, 8 labels) — boxes only, no masks.
2. **VinDr-CXR (P2).** Kaggle competition `vinbigdata-chest-xray-abnormalities-detection` (a human must accept the competition rules on kaggle.com first): 15,000 training images, each read by 3 radiologists, 14 box classes; ≈ 4,394 training images have at least one abnormality. Original data is DICOM; prefer a community resized-PNG dataset found with `kaggle datasets list -s vinbigdata` that includes original width and height so boxes can be rescaled. The PhysioNet route needs credentialing and is not feasible this week. Per-reader boxes enable an inter-reader agreement feature for difficulty.

### 3.2 Ingest steps (ChestX-Det) — `pipeline/ingest_chestxdet.py`
1. Download to `data/raw/chestxdet/`.
2. For each row: decode the image; convert RGBA/RGB to 8-bit grayscale `L`; assert 1024×1024; save `data/processed/images/cxd_<image_id>.png`.
3. Parse `annotation_json`: zip `boxes`, `polygons`, `syms` into instances. Print the set of unique `syms` before mapping. Map each sym through `config/taxonomy.yaml` (case- and whitespace-insensitive). **Unmapped sym → fail loudly.**
4. Rasterize each polygon with `cv2.fillPoly` into an instance mask. If a polygon is invalid or rasterizes to zero pixels, fall back to the box and add the qa flag `mask_from_bbox`. Save `data/processed/masks/<finding_id>.png` (0/255). Recompute the bbox from the mask.
5. `is_normal = is_negative and n_instances == 0`. A mismatch adds the qa flag `negative_flag_mismatch` and excludes the case.
6. Merge same-label instances with IoU > 0.6 (log how many).
7. Write `data/processed/cases.jsonl` (one `Case` per line, §3.3), `taxonomy_report.json`, `ingest_stats.json` (counts by label, normals, instances per case, area distribution, flags).
8. Contact sheets for clinical QA: 24 random abnormal + 6 normal cases with outlines and labels → `data/qa/contact_sheet_*.png`.

### 3.3 Canonical schema (Pydantic; mirror in `shared/schemas/case.json`)
```python
from typing import Literal
from pydantic import BaseModel

Side = Literal["right", "left", "bilateral", "midline"]     # PATIENT side

class Geometry(BaseModel):
    kind: Literal["polygon", "bbox"]
    bbox: tuple[float, float, float, float]                 # x0, y0, x1, y1 (image px)
    polygon: list[tuple[float, float]] | None = None
    mask_path: str | None = None                             # 0/255 PNG, same size as image

class Finding(BaseModel):
    finding_id: str                     # "<case_id>#F<n>", 1-based
    label: str                          # canonical id from taxonomy.yaml
    source_label: str
    kind: Literal["focal", "pattern"]
    geometry: Geometry
    centroid: tuple[float, float]
    area_frac: float                    # mask area / image area
    side: Side | None = None            # filled by M2
    zones: list[str] = []               # filled by M2, ordered by overlap
    primary_zone: str | None = None
    relative_location: str | None = None    # templated human string (M2)
    contrast: float | None = None       # |z| lesion vs surrounding ring (M2)
    model_prob: float | None = None     # TXV classifier prob for mapped pathology (M2)
    readers: int | None = None          # VinDr only
    agreement: float | None = None      # VinDr only

class Case(BaseModel):
    case_id: str                        # "cxd_<image_id>"
    source: Literal["chestx-det", "vindr-cxr", "nih-bbox"]
    source_split: str
    split: Literal["practice", "assess_A", "assess_B", "bench", "holdout"]
    image_path: str
    width: int
    height: int
    pixel_spacing_mm: float | None = None   # unknown for ChestX-Det → never state cm
    is_normal: bool
    findings: list[Finding]
    anatomy_path: str | None = None         # npz, 14 packed-bit masks (M2)
    zones_path: str | None = None           # json, RLE zone masks (M2)
    cardiothoracic_ratio: float | None = None
    difficulty_prior: float = 0.0           # b0 (M2)
    features: dict[str, float] = {}
    license_tag: str
    attribution: str
    qa_flags: list[str] = []
```
Coordinates everywhere: pixel space of the canonical 1024 px PNG, origin top-left, x right, y down, floats.

### 3.4 Taxonomy (authoritative copy in `config/taxonomy.yaml`)
| canonical id | display | kind | ChestX-Det sym |
|---|---|---|---|
| pneumothorax | Pneumothorax | focal | Pneumothorax |
| effusion | Pleural effusion | focal | Effusion |
| consolidation | Consolidation | focal | Consolidation |
| atelectasis | Atelectasis | focal | Atelectasis |
| nodule | Nodule | focal | Nodule |
| mass | Mass | focal | Mass |
| calcification | Calcification | focal | Calcification |
| fracture | Fracture | focal | Fracture |
| pleural_thickening | Pleural thickening | focal | Pleural Thickening |
| cardiomegaly | Cardiomegaly | pattern | Cardiomegaly |
| emphysema | Emphysema | pattern | Emphysema |
| fibrosis | Fibrosis | pattern | Fibrosis |
| diffuse_nodule | Diffuse nodules | pattern | Diffuse Nodule |

- **Focal** findings are localized by clicking. **Pattern** findings are reported with the Global findings checklist (location is not scored; for cardiomegaly we teach the cardiothoracic ratio).
- **Related groups** (partial label credit, and allowed as "commonly confused with" in debriefs): {consolidation, atelectasis}, {nodule, mass, calcification}, {effusion, pleural_thickening}, {fibrosis, diffuse_nodule}.
- **Core curriculum** (default practice pool): pneumothorax, effusion, consolidation, atelectasis, nodule, mass, fracture, cardiomegaly, plus normals. Other labels appear in Drill mode.

### 3.5 Splits — `pipeline/splits.py` (seeded; write `data/processed/splits.json`)
- From the HF **test** split (553): build `assess_A` and `assess_B`, 20 cases each: 8 normal + 12 abnormal, matched label mix, mean difficulty prior within 0.1 of each other, single-focal-finding cases preferred, no qa-flagged cases. All remaining test cases → `bench` (evaluation only).
- From the HF **train** split: `practice`; reserve 5% as `holdout`.
- Assessment and bench cases never appear in practice. (Difficulty priors come from M2; until M2 lands, build splits on label mix only, then rebalance once b0 exists.)

### 3.6 Data QA (acceptance in §15)
Pydantic validation of 100% of `cases.jsonl`; every finding mask non-empty and inside the image; every sym mapped; per-label counts; normals count; contact sheets written; fixture-based tests for rasterization and mapping.

---

## 4. Anatomy, zones, features

### 4.1 Segmentation — `pipeline/anatomy/segment.py`
TorchXRayVision's ChestX-Det PSPNet segments 14 structures. Reference usage:
```python
import torch, torchvision, skimage.io
import torchxrayvision as xrv

seg = xrv.baseline_models.chestx_det.PSPNet().eval()
img = skimage.io.imread(path)                         # uint8, (1024, 1024)
x = xrv.datasets.normalize(img, 255)[None, ...]       # (1, H, W), range [-1024, 1024]
x = torchvision.transforms.Compose([xrv.datasets.XRayCenterCrop(),
                                    xrv.datasets.XRayResizer(512)])(x)
with torch.no_grad():
    out = seg(torch.from_numpy(x)[None, ...])          # (1, 14, 512, 512)
# Check the value range empirically: if outputs are logits, apply sigmoid. Threshold 0.5.
# Upsample masks to 1024 with nearest-neighbour.
targets = seg.targets
# ['Left Clavicle','Right Clavicle','Left Scapula','Right Scapula','Left Lung','Right Lung',
#  'Left Hilus Pulmonis','Right Hilus Pulmonis','Heart','Aorta','Facies Diaphragmatica',
#  'Mediastinum','Weasand','Spine']
```
- Device: MPS on Apple Silicon if available, else CPU. Batch 8. Resumable (skip existing outputs). Log throughput to `logs/anatomy.log`. Run in the background.
- Save `data/processed/anatomy/<case_id>.npz` with `np.packbits` masks (compressed).
- Classifier features: `xrv.models.DenseNet(weights="densenet121-res224-all")`; store probabilities for labels that map to `model.pathologies`; leave others null. Do not trust targets the weights were not trained on.
- Scope: all cases in `practice`, `assess_*`, `bench`.

### 4.2 Orientation check — `pipeline/anatomy/orientation.py`
Display convention: **patient right appears on the image left** (standard PA display). Zone ids always name the **patient's** side.
- For each case compute centroids of Heart, "Left Lung", "Right Lung". Expected: `x(Right Lung) < x(Left Lung)` and `x(Heart) > W/2 − 0.05·W`.
- If ≥ 80% of cases satisfy `x(Right Lung) < x(Left Lung)`, TXV names are patient-side: keep them. If the reverse holds, swap Left/Right channel names globally and document it in PROGRESS.md.
- Per-case violations → qa flag `orientation_suspect` → exclude from practice and assessment.
- Write `data/qa/orientation_report.json`.

### 4.3 Zones and review areas — `pipeline/anatomy/zones.py`
`derive_zones(masks: dict[str, np.ndarray]) -> dict[str, np.ndarray]` (boolean masks at 1024²). Midline `xm` = Spine centroid x (fallback W/2). Patient-right pixels have `x < xm`.

| zone id | definition |
|---|---|
| `right_upper_zone`, `right_mid_zone`, `right_lower_zone` | right lung mask split into vertical thirds of its own extent |
| `left_upper_zone`, `left_mid_zone`, `left_lower_zone` | same for the left lung |
| `right_apex`, `left_apex` | top 18% of that lung's vertical extent |
| `right_costophrenic_angle`, `left_costophrenic_angle` | bottom 18% of the lung's extent ∩ lateral 45% of its horizontal extent (lateral = smaller x for the right lung, larger x for the left lung) |
| `right_periphery`, `left_periphery` | lung minus the lung eroded by 8% of lung width (outer band) |
| `right_hilum`, `left_hilum` | TXV hilus masks dilated by 1.5% of W |
| `retrocardiac` | Heart ∩ {x > xm} ∩ {y > left-hilum centroid y} |
| `cardiac_silhouette` | Heart |
| `mediastinum` | Mediastinum ∪ Aorta ∪ Weasand |
| `subdiaphragmatic` | band from the top edge of the diaphragm mask down 8% of H, within the lungs' x-range |
| `right_clavicle`, `left_clavicle`, `spine` | TXV masks |

- **Review areas** (coverage targets; list in `config/review_areas.yaml`): right_apex, left_apex, right_hilum, left_hilum, retrocardiac, right_costophrenic_angle, left_costophrenic_angle, subdiaphragmatic, mediastinum.
- Store zones as RLE in `data/processed/zones/<case_id>.json`; also write a small preview PNG for `/dev`.
- If a lung mask is implausible (area < 3% of the image) → qa flag `anatomy_failed`; fall back to fixed-fraction zones (image halves and thirds) and mark them `approximate: true` so the facts builder can say "approximately".

### 4.4 Finding locations
- `overlap(zone) = |mask ∩ zone| / |mask|`. `zones` = zones with overlap ≥ 0.15, sorted descending, max 3. `primary_zone` = argmax. If a finding touches no lung zone, use the nearest zone by centroid distance.
- `side`: mask area on each side of `xm`; `bilateral` if both sides ≥ 25%; `midline` for mediastinal/spine-centered findings.
- `relative_location` (templated, deterministic): e.g. "right lower zone, lateral third, just above the right costophrenic angle". Lateral/central/medial thirds are computed within that lung's x-extent; upper/middle/lower part within the zone's y-extent.
- Mark-to-finding spatial relation (computed at scoring time, §6): same vs opposite lung; zone steps ("one zone lower"); direction in units of lung height/width ("lower and more lateral"). **Never state centimetres unless `pixel_spacing_mm` is known.**

### 4.5 Lesion features and difficulty prior — `pipeline/features/`
Per focal finding:
- `area_frac`; `contrast` = |mean(mask) − mean(ring)| / std(ring), ring = mask dilated 15 px minus mask; `edge_dist` = distance of centroid to the lung boundary / lung width; `zone_hardness` from `config/review_areas.yaml`; `n_findings` in the case; `model_prob` (TXV).

Difficulty prior (z-scores over all focal findings in `practice`):
```
b0 = 0.9·z(−log area_frac) + 0.6·z(−contrast) + 0.5·z(zone_hardness)
   + 0.4·z(n_findings)    + 0.6·z(1 − model_prob, missing → 0)
case b0 = max over its focal findings; normal cases b0 = 0; clip to [−2.5, 2.5]
```
This is a heuristic prior; Elo (§9) corrects it from real attempts. Plot the b0 distribution per label to `data/qa/difficulty_prior.png`.

### 4.6 Cardiothoracic ratio — `pipeline/features/ctr.py`
CTR = max horizontal width of the Heart mask / max row-wise distance between the outer edges of the two lungs. Store per case. Debrief caveat: "measured automatically; the projection (PA vs AP) is not recorded for these images, and AP films exaggerate heart size."

---

## 5. Reading room: viewer, marking, telemetry

### 5.1 Viewer
- Layers in one transformed container: image (`<canvas>` or `<img>`), SVG overlay in image coordinates (`viewBox="0 0 1024 1024"`), heatmap layer.
- Wheel = zoom at cursor (1×–6×); drag = pan; double-click = reset; brightness/contrast sliders (CSS filter or canvas); invert toggle.
- Keyboard: `L` loupe on/off, `N` call it normal, `1–5` confidence for the selected mark, `Backspace` delete selected mark, `Enter` submit, `H` hint, `A` show anatomy (after submit only), `→` next case.
- **Projector mode** (toggle + `?projector=1`): boosts displayed image contrast/brightness, doubles stroke widths, enlarges type. Auditorium projectors wash out chest X-rays; this matters.
- Fit-to-height by default; preload the next case image.

### 5.2 Marking
- Single click (no drag) places a mark at image coordinates and opens a popover: focal label list (display names) + "Not sure" + confidence chips 1–5. Marks are draggable and deletable.
- Rail: **Global findings** checklist (cardiomegaly, emphysema, fibrosis, diffuse nodules), each with confidence.
- **Call it normal** clears/disables marks (confirm if marks exist) and asks for confidence.
- Hints button shows remaining count. Submit is disabled until there is at least one mark, one global finding, or a normal call.

### 5.3 Loupe
180 px circle, 2.5× magnification of the image under the cursor, follows the pointer, hides while panning, on by default in Practice and Drill. The loupe makes reading easier *and* makes the cursor a better proxy for attention, because learners steer it to where they are looking.

### 5.4 Telemetry contract (`shared/schemas/telemetry_event.json`)
```ts
type TelemetryEvent = {
  t: number;                                   // ms since case shown
  kind: 'move' | 'down' | 'up' | 'wheel' | 'enter' | 'leave' | 'loupe' | 'wl' | 'pan';
  x?: number; y?: number;                      // image px (float), only while pointer is over the image
  zoom: number;                                // 1 = fit
  vp: [number, number, number, number];        // visible image rect [x0, y0, x1, y1] in image px
  loupe: boolean;
};
```
- Sample pointer moves throttled to 33 ms (~30 Hz), plus every viewport change and toggle. Buffer in memory; send the whole buffer with the submit (cap 20,000 events; downsample if over).
- Screen → image coordinate conversion lives in one tested function. The e2e test asserts a click at a known screen point maps to the expected image coordinate within 2 px at zoom 1× and 3×.
- Store raw events per attempt in the `telemetry` table.

---

## 6. Scoring — `backend/app/scoring/`

### 6.1 Hit test
```python
TAU = scoring.tolerance_frac * width            # default 0.02 → ~20 px at 1024

def hits(x: float, y: float, f: Finding) -> bool:
    if f.geometry.mask_path:                    # dilated instance mask, LRU-cached
        m = dilated_mask(f.finding_id, TAU)
        return bool(m[int(round(y)), int(round(x))])
    x0, y0, x1, y1 = f.geometry.bbox
    return x0 - TAU <= x <= x1 + TAU and y0 - TAU <= y <= y1 + TAU
```

### 6.2 Matching (marks ↔ focal findings)
Cost matrix `C[m, f]`: 0.0 if hit and label exact; 0.3 if hit and label in the same related group; 0.6 if hit and any other label or "Not sure"; 1e6 if no hit. Solve with `scipy.optimize.linear_sum_assignment`; drop pairs with cost ≥ 1e6. An unassigned mark that hits an already-matched finding is a **duplicate** (no penalty). Any other unassigned mark is a **false positive**.

### 6.3 Outcomes and scores
Per focal finding: `found` (matched, exact label) · `mislabeled` (matched, other label) · `missed_search` · `missed_recognition` · `missed_decision` (the miss subtype comes from §7).
Per pattern finding: `pattern_found` · `pattern_missed`. Pattern selections not in ground truth: `pattern_false`.
Per mark: `true_positive` · `duplicate` · `false_positive` (with its zone).
Normal case: `true_negative` if called normal with no marks; each mark is a `false_positive`.

Case score (0–100; weights in `config/scoring.yaml`):
- Abnormal: `70·(localized focal / focal) + 20·(exact labels / focal) + 10·(pattern accuracy) − 10·FP − 5·hints`, floored at 0. Cases with no focal findings: patterns carry 100.
- Normal: 100 if called normal with no marks; −25 per false positive; −5 per hint; floor 0.

Binary **success** for Elo: abnormal → every focal finding localized and ≤ 1 FP (patterns: all selected); normal → zero FP marks.

### 6.4 FROC rows
Store per mark `(case_id, mark_id, confidence, is_lesion_localization)` and per case the number of focal lesions, so §10 can plot FROC curves (lesion localization fraction vs non-lesion localizations per image at each confidence threshold).

---

## 7. Search analysis and the miss-type engine — `backend/app/search/`

### 7.1 Dwell
```python
def dwell_ms(events, region, cfg) -> float:
    """region: boolean mask (H, W). Returns attention-proxy dwell inside region."""
    total, still = 0.0, 0.0
    for e0, e1 in pairwise(events):
        dt = min(e1.t - e0.t, cfg.max_dt_ms)                      # default 250
        if e0.x is None:
            continue                                               # pointer off-image
        moved = e1.x is None or (abs(e1.x - e0.x) + abs(e1.y - e0.y)) > 1.0
        still = 0.0 if moved else still + dt
        if still > cfg.max_still_ms:                               # default 1500: idle cap
            continue
        if region[int(e0.y), int(e0.x)]:
            total += dt
        if e0.zoom >= cfg.zoom_dwell_min and center_in(e0.vp, region):   # 2.0×
            total += cfg.zoom_dwell_weight * dt                     # 0.5
    return total
```
Finding ROI = instance mask dilated by `ρ = roi_frac·W` (default 0.035 → ~36 px), a stand-in for a useful field of view around the point of attention.

### 7.2 Miss types (Kundel taxonomy, proxy version)
For each missed focal finding: `dwell < 300 ms` → **search** ("never looked there"); `300 ≤ dwell < 1000 ms` → **recognition** ("looked past it"); `dwell ≥ 1000 ms` → **decision** ("looked, judged it normal"). Matched with the wrong label → **interpretation** ("found it, named it wrong"). Extra marks → **overcall** ("called something that isn't there"). Thresholds live in `config/scoring.yaml`.
UI tooltip, always shown with the miss type: "Based on your cursor, loupe and zoom — a proxy for where you looked."

### 7.3 Review-area coverage
An area counts as visited if its dwell (no dilation) ≥ 300 ms. Output: visited, unvisited, and the order of first visits.

### 7.4 Search metrics (per attempt)
Lung coverage % (fraction of lung pixels within ρ of any dwelled sample), time to first mark, total time, time to first entry into each finding ROI, zoom usage, loupe usage, unvisited review areas. Heatmap: gaussian splats (σ = ρ) of dwell-weighted samples rendered to a 256×256 PNG for the reveal (server or client; both must use the same events).

---

## 8. The Claude tutor — `backend/app/tutor/`

### 8.1 Facts builder (`facts.py`) — the only thing Claude is allowed to believe
Deterministically assemble `DebriefFacts` (`shared/schemas/debrief_facts.json`). Example:
```json
{
  "schema": "debrief_facts.v1",
  "case": {
    "case_id": "cxd_36204", "is_normal": false,
    "projection": "frontal; PA vs AP not recorded",
    "findings": [
      {"id": "F1", "label": "cardiomegaly", "display": "Cardiomegaly", "kind": "pattern", "ctr": 0.61},
      {"id": "F2", "label": "nodule", "display": "Nodule", "kind": "focal", "side": "right",
       "primary_zone": "right_lower_zone", "zones": ["right_lower_zone", "right_periphery"],
       "relative_location": "right lower zone, lateral third, just above the right costophrenic angle",
       "size": "small (about 0.05% of the image)", "difficulty": "hard", "zones_approximate": false}
    ]
  },
  "learner": {
    "level": "MS2", "declared_normal": false, "hints_used": 0, "time_to_submit_s": 41,
    "marks": [{"id": "M1", "label": "nodule", "confidence": 4, "zone": "left_mid_zone"}],
    "pattern_selections": []
  },
  "outcomes": [
    {"target": "F2", "result": "missed_search", "dwell_ms": 120},
    {"target": "F1", "result": "pattern_missed"},
    {"target": "M1", "result": "false_positive", "zone": "left_mid_zone"}
  ],
  "spatial_relations": [
    {"from": "M1", "to": "F2", "text": "The nodule is in the other lung: your mark was in the left mid zone; the nodule is in the right lower zone."}
  ],
  "search": {
    "lung_coverage_pct": 46,
    "unvisited_review_areas": ["right_costophrenic_angle", "retrocardiac", "left_apex"],
    "first_visits": ["right_hilum", "left_hilum", "left_mid_zone"]
  },
  "history": {"nodule": {"attempts": 6, "localized": 2}, "recent_miss_types": {"search": 3, "recognition": 1, "decision": 0}},
  "teaching_cards": ["nodule", "cardiomegaly"]
}
```
All human-readable strings (zones, relative locations, relations) are produced by code, not by Claude.

### 8.2 Images sent (`render.py`)
1. Full image at 1024 px with overlays: expert outlines in cyan labeled F1, F2…; learner marks in amber labeled M1, M2…
2. Unannotated crop (512×512 window around the primary missed/mislabeled finding, upscaled ×2 if small) so the visual sign isn't hidden under the outline.
3. The same crop with a thin outline.
Image tokens ≈ width·height/750, so ≈ 1.4k + 2×0.35k tokens. Keep every image ≤ 1568 px on the long edge.

### 8.3 System prompt (`prompts/debrief_system.md`, versioned header `v1`)
```
You write the debrief for Blindspot, a chest X-ray perception trainer for medical students.
You explain one practice case: what the learner found, what they missed, and how they missed it.

Rules — follow all of them:
1. FACTS are the reference standard, taken from radiologist annotations. FACTS lists every
   finding on this case. Never mention, suggest, or speculate about any other abnormality,
   even if you think you see one. If the image seems to disagree with FACTS, defer to FACTS.
2. Locations come only from FACTS (side, zones, relative_location, spatial_relations).
   Do not invent positions, measurements, rib levels, or lobes. Sides are the PATIENT's
   side; the patient's right appears on the left of the image.
3. Describe appearance using the TEACHING CARDS for the labels involved and what is visible
   inside the outlined region in the crop. Plain language for a second-year medical student;
   define jargon in a few words.
4. Match "why" to the result:
   missed_search → they never examined that region: coach the search pattern.
   missed_recognition → they passed over it briefly: teach the sign to look for.
   missed_decision → they looked at length and judged it normal: teach how to tell it from
     normal anatomy and its mimics.
   mislabeled → contrast the two entities in one sentence each.
   false_positive → radiologists marked nothing there; name common normal structures in that
     zone that get mistaken for abnormalities (from the cards), framed as possibilities.
5. Education only. No management, treatment, urgency, prognosis, or statements about a real
   patient. No disclaimers.
6. Direct and warm; never shaming. Headline ≤ 14 words. All text fields together ≤ 140 words.
7. Copy result values exactly from FACTS. List the FACTS ids you relied on in fact_ids.
Return JSON that matches the provided schema.
```
The teaching cards for **all** labels go in a second system block with `cache_control` so the prefix is identical across calls and caches. The relevant labels for this case are named inside FACTS.

### 8.4 Output schema (`shared/schemas/debrief_output.json`; pass as structured output)
```json
{
  "type": "object", "additionalProperties": false,
  "required": ["headline", "verdict", "findings", "overcalls", "search_coaching", "calibration_note", "next_step", "fact_ids"],
  "properties": {
    "headline": {"type": "string"},
    "verdict": {"type": "string", "enum": ["all_found", "partly_found", "missed", "overcall", "correct_normal", "missed_normal_call"]},
    "findings": {"type": "array", "items": {
      "type": "object", "additionalProperties": false,
      "required": ["finding_id", "result", "where_to_look", "what_it_looks_like", "why"],
      "properties": {
        "finding_id": {"type": "string"},
        "result": {"type": "string", "enum": ["found", "mislabeled", "missed_search", "missed_recognition", "missed_decision", "pattern_found", "pattern_missed"]},
        "where_to_look": {"type": "string"},
        "what_it_looks_like": {"type": "array", "items": {"type": "string"}},
        "why": {"type": "string"}
      }}},
    "overcalls": {"type": "array", "items": {
      "type": "object", "additionalProperties": false,
      "required": ["mark_id", "explanation", "possible_mimics"],
      "properties": {
        "mark_id": {"type": "string"},
        "explanation": {"type": "string"},
        "possible_mimics": {"type": "array", "items": {"type": "string"}}
      }}},
    "search_coaching": {"type": "string"},
    "calibration_note": {"type": "string"},
    "next_step": {"type": "string"},
    "fact_ids": {"type": "array", "items": {"type": "string"}}
  }
}
```
Use an empty string for `calibration_note` when there is nothing to say. Avoid schema keywords the structured-output feature may not support (length limits, numeric bounds); enforce lengths in the validator instead.

### 8.5 API call (`client.py`) — verify parameter names against the current docs and SDK before coding
```python
from anthropic import Anthropic
client = Anthropic()          # reads ANTHROPIC_API_KEY

resp = client.messages.create(
    model=settings.model_debrief,                     # env, never hard-coded
    max_tokens=1200,
    system=[
        {"type": "text", "text": DEBRIEF_SYSTEM},
        {"type": "text", "text": ALL_TEACHING_CARDS, "cache_control": {"type": "ephemeral"}},
    ],
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": full_annotated_b64}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": crop_clean_b64}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": crop_outlined_b64}},
        {"type": "text", "text": "FACTS:\n" + facts_json},
    ]}],
    output_config={"format": {"type": "json_schema", "schema": DEBRIEF_SCHEMA}},
)
```
- Structured outputs: `output_config.format` with `type: "json_schema"` (generally available; no beta header). Keep the schema constant across calls so caching is not invalidated.
- If the chosen model supports an effort setting, use a low/medium effort for runtime debriefs to cut latency; confirm in the docs.
- Timeouts: 12 s; one retry on 5xx/overload; then template fallback.
- Run the call in a background task after submit; the client polls `GET /attempts/{id}/debrief`.

### 8.6 Validator (`validator.py`) — deterministic, runs on every debrief
1. Output `finding_id`s == the case's finding ids (each exactly once); each `result` equals the computed outcome.
2. Overcall `mark_id`s == the false-positive marks.
3. Laterality: `left`/`right` words in `where_to_look` must match the finding's side (both allowed for `bilateral`; ignore "patient's right appears on the left of the image" phrasing).
4. Zone vocabulary: zone terms in `where_to_look` (apex, hilum, costophrenic, retrocardiac, upper/mid/lower zone, periphery, mediastinum, diaphragm) must be among the finding's zones or their neighbors (`adjacency` in `config/review_areas.yaml`).
5. Label mentions anywhere must be in: ground-truth labels ∪ learner-chosen labels ∪ related groups ∪ the cards' mimic lists. This catches hallucinated findings.
6. Banned content (regex list in config): management/treatment terms ("treat", "management", "antibiotic", "chest tube", "drain", "biopsy", "admit", "urgent", "follow-up CT"), statements about a real patient, centimetre/millimetre measurements when `pixel_spacing_mm` is null.
7. Lengths: headline ≤ 14 words; all text ≤ 160 words.
On failure: regenerate once, appending "Fix these problems: …"; if it still fails, use the template debrief. Log every validator result (this feeds the faithfulness metric in §12).

### 8.7 Cache and offline fallback (`cache.py`, `templates.py`)
- Cache key = sha256(case_id, model, prompt_version, learner level, sorted `(target, result)` pairs, sorted FP zones, sorted unvisited review areas). Store in the `debriefs` table.
- `BLINDSPOT_OFFLINE=1` → cache hit or template, never the network.
- Templates: one per result type, filled from FACTS + card fields (e.g. missed_search → where = relative_location; why = "Your search never paused in the {zone}. {card.search_tip}"; what = first two `key_signs`). Templates must pass the validator (tested).

### 8.8 Hint ladder (`hints.py`, deterministic, no LLM)
`POST /attempts/{id}/hint` with current marks and the telemetry so far.
- **H1 (all cases):** "You haven't looked at: {unvisited review areas}." If all were visited: "Compare each region with the same region on the other side."
- **H2:** abnormal → side + primary zone of the hardest finding not yet marked; normal → "Asymmetry is the clue: compare left and right zone by zone."
- **H3:** abnormal → the first key sign from that finding's card; normal → "If every review area is clear, normal is a valid call."
Each hint costs 5 points and is logged. Hints never reveal ground truth on assessment cases (hints are disabled in Assessment mode).

### 8.9 Ask the tutor (`ask.py`)
Up to 3 follow-up questions per case, same FACTS and images, system prompt `prompts/ask_system.md`: answer only about this case's FACTS plus general educational explanations of the labels involved (e.g. why air looks dark); refuse to speculate about anything else on the image; no management; ≤ 90 words. Validator rules 3, 5, 6 apply.

### 8.10 Teaching cards (`content/teaching_cards/<label>.yaml`)
```yaml
label: pneumothorax
display_name: Pneumothorax
kind: focal
one_liner: Air in the pleural space separating the lung from the chest wall.
key_signs:
  - A thin white visceral pleural line parallel to the chest wall
  - No lung markings beyond that line
  - On supine films, an unusually deep, dark costophrenic angle (deep sulcus sign)
where_it_hides: [right_apex, left_apex, right_periphery, left_periphery]
mimics:
  - Skin fold (the line runs past the chest wall, or lung markings continue beyond it)
  - Medial border of the scapula
commonly_confused_with: []
search_tip: Trace the lung edge at both apices with the loupe before calling a film normal.
radiopaedia_url: https://radiopaedia.org/articles/pneumothorax   # verify with one GET; else null
review: {status: ai_draft, reviewer: null, date: null, notes: null}
```
- The tutor agent drafts all 13 cards (`status: ai_draft`). Sri reviews Tuesday (`student_reviewed`); radiologists Thursday morning (`radiologist_reviewed`). The UI shows the provenance badge on every debrief.
- Radiopaedia: link only. Verify each URL with a single GET; never scrape or download content (their terms prohibit automated copying, and their API does not support downloading).
- Also draft `zone_mimics` in `config/review_areas.yaml` (common normal structures per zone that get overcalled, e.g. hilum → vessels seen end-on; lower zone lateral → nipple shadow; apex → overlapping rib and clavicle; periphery → skin fold), status `ai_draft`.

### 8.11 Models and cost
| use | env var | default |
|---|---|---|
| debrief, ask-the-tutor | `BLINDSPOT_MODEL_DEBRIEF` | `claude-sonnet-5-5` |
| optional cheap tasks | `BLINDSPOT_MODEL_FAST` | `claude-haiku-4-5-20251001` |
| evaluation judge | `BLINDSPOT_MODEL_JUDGE` | `claude-opus-5-5` (or `claude-fable-5-1`) |
| VLM benchmark subject | `BLINDSPOT_MODEL_BENCH` | `claude-sonnet-5-5` (add others if budget allows) |

A debrief is roughly 4–5k input tokens and ≤ 600 output tokens, about one to two cents at Sonnet 5.5 list pricing (≈ $2 / $10 per million input/output tokens; verify on the pricing page). Whole-hackathon API budget: about $25–40, including evaluations. Every script that calls the API takes `--max-cost` and refuses to start if its estimate exceeds it.

---

## 9. Adaptive engine — `backend/app/adaptive/` (constants in `config/adaptive.yaml`)

### 9.1 Model
Elo as a lightweight Rasch model: `P(success) = 1 / (1 + exp(−(θ − b)))`.
- Learner abilities: `θ_label` for each focal label and pattern label, plus `θ_normal` (specificity skill). Global θ = mean of the abilities the learner has used.
- Case difficulty `b` starts at the prior `b0` (§4.5) and is updated from all learners' attempts.
```python
def update(theta, b, outcome, n_learner, n_case, cfg):
    p = 1 / (1 + math.exp(-(theta - b)))
    k_t = cfg.k_learner / (1 + cfg.k_decay * n_learner)      # 0.4, 0.05
    k_b = cfg.k_case / (1 + cfg.k_decay * n_case)            # 0.3
    return theta + k_t * (outcome - p), b - k_b * (outcome - p)
```
- Abnormal case: update each involved `θ_label` with that finding's outcome (1 = localized) against the case `b`; update `b` with the case success. Normal case: update `θ_normal` and `b` with success.

### 9.2 Next-case selection (Practice)
1. Candidate pool: practice cases not seen in this session and not in the learner's last 50 attempts; exclude qa-flagged cases.
2. Draw normal vs abnormal with probability `prevalence_abnormal` (default 0.5; instructor-settable 0.3–0.7 — prevalence trades sensitivity against specificity, see RESEARCH.md §2).
3. Abnormal: with probability 0.6 target the learner's weakest core label (lowest θ with at least 2 attempts, else least practiced); otherwise sample a core label. Penalize repeating the same label twice in a row (interleaving).
4. Choose the candidate minimizing `|P(success) − target_p| + 0.15·repeat_penalty + noise(0, 0.05)`, `target_p` default 0.7.
5. ε-exploration 0.1: random eligible case.
Drill mode fixes the label; Review mode samples from the learner's misses with a 1-day/3-case spacing rule.

### 9.3 Assessment mode
Fixed 20-case sets `assess_A` / `assess_B`, fixed order, no hints, no reveal until the end. Elo is not updated by assessment attempts. The end screen shows a summary (sensitivity, specificity, localization, miss-type mix).

### 9.4 Tests
Simulation with synthetic learners (seeded; labeled "synthetic" and never shown in the UI): selection keeps realized success within 0.6–0.8 after 40 cases; prevalence within ±5% over 200 draws; no assessment/bench case is ever served in Practice.

---

## 10. Analytics — `backend/app/analytics/` + `frontend/src/dashboard/`

### 10.1 Learner dashboard ("Reading log")
- **Learning curve:** rolling accuracy (window 10) of case success vs attempt number, overall and per label (Pusic-style learning curves).
- **Miss-type mix:** stacked bars over time windows: search / recognition / decision / interpretation / overcall. The story we want to see: search errors shrink first.
- **Sensitivity / specificity** at case level; lesion localization fraction; false positives per image.
- **Calibration:** accuracy by confidence level (1–5), plus "confident misses" count.
- **FROC curve** from confidence-rated marks (§6.4).
- **Blind-spot map:** each missed finding centroid mapped into a canonical chest frame (normalize x, y by the union lung bounding box) and drawn as a density over a schematic chest outline; found findings in a second color.
- **Review-area habit:** % of cases in which each review area was visited.

### 10.2 Cohort dashboard (Instructor)
Same metrics aggregated across learners, plus a per-label difficulty table (empirical success vs b) and a cohort blind-spot map. Filters: level, mode, date.

### 10.3 Honesty rule
Every chart displays n. Charts built from synthetic data are never shown outside tests. If the demo needs history, it comes from real team and pilot attempts.

---

## 11. Expert review and the content workflow

### 11.1 `/review` page
- **Debrief review:** shows case image with overlays, the learner answer, FACTS summary, the debrief. Reviewer enters name + role, rates *accuracy* (1–5), *teaching value* (1–5), *safety concern* (yes/no), free-text correction. Keyboard-friendly; next item auto-loads.
- **Teaching card review:** renders each card; reviewer can approve, edit fields inline, or flag. Approvals bump `review.status` and record reviewer + date in the YAML (write-back through the API; the backend owns the file write).
- Export: `GET /api/review/export.csv`.
- Item source: a curated queue of 20 debriefs (stratified by result type) generated from bench cases by `eval/faithfulness.py` plus any live debriefs flagged by learners ("This seems wrong" link on every debrief).

### 11.2 Content flow
Tutor agent drafts cards (`ai_draft`) → Sri reviews Tuesday (`student_reviewed`) → radiologists review Thursday morning (`radiologist_reviewed`) → provenance badge on debriefs reflects the lowest status among the cards used.

---

## 12. Evaluation and science — `eval/`
Every script: `--dry-run` (no API, uses mocks) and `--max-cost`; caches raw responses in `eval/cache/` (gitignored); writes Markdown + PNG figures to `eval/reports/`; never puts patient images in committed reports (example galleries go to `data/eval_galleries/`).

### 12.1 VLM localization benchmark (`vlm_localization.py`) — "Can a frontier VLM find the finding?"
Method adapted from Gosai & Kavishwar (ML4H 2025), who overlaid a grid and elicited coordinates.
- Cases: bench split, exactly one focal finding of a core label; up to 25 per label (≤ 200 total).
- Prompt (structured output): "This is a frontal chest radiograph with a reference grid (columns A–H, rows 1–8). A radiologist identified a {display} on this image. Return the grid cell containing its center, your estimate of its center in pixels (image 1024×1024, x right, y down), and which side of the patient it is on."
- Scoring: point hit (inside mask dilated by τ), cell hit (cell intersects mask), patient-side accuracy, primary-zone accuracy.
- Baselines: (a) **label prior** — that label's mean centroid in the practice split; (b) **random point inside the lungs** (mean of 100 draws). Report per label and overall with bootstrap 95% CIs (1,000 resamples) and a laterality confusion matrix (does the model confuse image-left with patient-right?).
- Models: `BLINDSPOT_MODEL_BENCH`; optionally Opus/Fable if budget allows.
- Interpretation: whatever the result, report it straight. Even a strong VLM is not a guarantee; our tutor's truth comes from radiologists by construction.

### 12.2 Debrief faithfulness + grounding ablation (`faithfulness.py`)
- Scenarios (≈100): bench cases × learner behaviours {all correct; wrong-side mark; mislabeled; missed with scripted telemetry that never enters the ROI (search), passes through for ~500 ms (recognition), lingers ~2,000 ms (decision); overcall on a normal}. Run the real scoring and search engines to produce FACTS.
- Conditions: **G** = production pipeline (FACTS + cards + images). **U** = ablation: same images and learner marks plus only the ground-truth label names, no locations or outcomes — Claude must find and explain them itself.
- Metrics: schema validity; deterministic validator pass rate (first try and after one regeneration); judge-rated groundedness; hallucinated findings per debrief; laterality errors; pedagogy score (1–5); management-advice rate.
- Judge (`judge_prompt.md`, model `BLINDSPOT_MODEL_JUDGE`, structured output): sees FACTS (ground truth) and the debrief; returns `{grounded: bool, violations: [str], laterality_correct: bool, hallucinated_findings: [str], pedagogy: 1–5, management_advice: bool}`.
- Headline chart: G vs U on groundedness and laterality errors.

### 12.3 Miss-type engine sanity check
Scripted telemetry replays (unit tests + a small report table) showing that each synthetic behaviour is classified as intended, and how sensitive classification is to ρ and the 300/1000 ms thresholds (±30%).

### 12.4 Pilot analysis (`pilot_analysis.py`)
Protocol in DEMO_AND_PITCH.md. Per participant: assessment A or B (pre) → 15 minutes of Practice → the other assessment (post), counterbalanced by participant-code parity; then SUS. Report per-participant and median paired changes in sensitivity, specificity, localization fraction, false positives per image, and miss-type mix, with bootstrap CIs and the SUS score. Label it "pilot, n = X, not powered; usability testing, not a research study".

### 12.5 Report (`report.py`)
Assemble `eval/reports/REPORT.md` with the tables and figures above plus one-line takeaways for slides.

---

## 13. API contract (prefix `/api`; JSON; Pydantic models mirror `shared/schemas/`)

| method | path | request | response |
|---|---|---|---|
| GET | `/health` | — | `{ok: true, offline: bool, cases: int}` |
| POST | `/sessions` | `{display_name, level, participant_code?, mode, settings?}` | `{session_id, learner_id}` |
| GET | `/sessions/{sid}/next` | — | `{attempt_id, case: {case_id, image_url, width, height}, index, total?}` |
| GET | `/cases/{case_id}/image` | — | `image/png` (long cache) |
| POST | `/attempts/{aid}/hint` | `{marks, telemetry}` | `{level, text, remaining}` |
| POST | `/attempts/{aid}/submit` | `AttemptSubmit` | `SubmitResult` (practice/drill/review) or `{recorded: true}` (assessment) |
| GET | `/attempts/{aid}/debrief` | — | `{status: "pending"\|"ready"\|"failed", debrief?, source: "live"\|"cache"\|"template", provenance}` |
| POST | `/attempts/{aid}/ask` | `{question}` | `{answer, remaining}` |
| GET | `/sessions/{sid}/summary` | — | assessment summary |
| GET | `/learners/{lid}/dashboard` | — | learner metrics |
| GET | `/cohort/dashboard` | filters | cohort metrics |
| GET | `/review/items` | `type=debrief\|card` | review queue |
| POST | `/review/ratings` | rating payload | `{ok}` |
| GET | `/review/export.csv` | — | CSV |
| POST | `/sus` | `{learner_id, answers: [10 ints]}` | `{score}` |
| GET | `/dev/cases/{case_id}/overlay` | `layers=anatomy,zones,findings` | PNG (dev/debug only) |
| GET | `/about` | — | attributions JSON |

```ts
type Mark = { mark_id: string; x: number; y: number; label: string | 'not_sure'; confidence: 1|2|3|4|5 };
type PatternSelection = { label: string; confidence: 1|2|3|4|5 };
type AttemptSubmit = {
  marks: Mark[]; patterns: PatternSelection[];
  declared_normal: boolean; normal_confidence?: 1|2|3|4|5;
  telemetry: TelemetryEvent[]; hints_used: number;
  client_timing: { shown_at: string; submitted_at: string };
};
type SubmitResult = {
  score: number; success: boolean;
  outcomes: Array<{ target: string; result: string; dwell_ms?: number; zone?: string }>;
  reveal: {
    findings: Array<{ finding_id: string; label: string; display: string; kind: 'focal'|'pattern';
                      polygon?: [number, number][]; bbox: [number, number, number, number];
                      side?: string; zones: string[]; relative_location?: string }>;
    marks: Array<{ mark_id: string; result: 'true_positive'|'duplicate'|'false_positive'; matched_finding?: string }>;
    arrows: Array<{ from_mark: string; to_finding: string; text: string }>;
    search: { lung_coverage_pct: number; unvisited_review_areas: string[]; heatmap_png_b64?: string };
    ctr?: number;
  };
  facts_card: { headline: string; lines: string[] };   // deterministic, instant
  debrief_status: 'pending' | 'disabled';
};
```
**Invariant (tested):** no ground-truth field appears in any response before submit for that attempt; assessment responses never include ground truth until the session summary.

### 13.1 SQLite schema (`backend/app/db.py`)
`learners(id, display_name, level, participant_code, created_at)` · `sessions(id, learner_id, mode, settings_json, started_at, ended_at)` · `attempts(id, session_id, learner_id, case_id, mode, shown_at, submitted_at, declared_normal, normal_confidence, marks_json, patterns_json, hints_used, score, success, outcomes_json, search_json, elo_json)` · `telemetry(attempt_id, events_json, n_events)` · `debriefs(id, attempt_id, cache_key, model, prompt_version, facts_json, output_json, validator_json, source, latency_ms, input_tokens, output_tokens, created_at)` · `asks(id, attempt_id, question, answer, created_at)` · `ability(learner_id, label, theta, n)` · `case_difficulty(case_id, b, n)` · `reviews(id, reviewer, role, item_type, item_id, accuracy, teaching, safety_flag, comment, created_at)` · `sus(learner_id, answers_json, score, created_at)`.

---

## 14. UI and design direction (frontend agent: follow this; it is a choice, not a default)

**Subject:** a radiology reading room. **Audience:** medical students; judges include radiologists and physicians. **Primary job:** make the learner *see their own search*.

### 14.1 Tokens
| name | hex | role |
|---|---|---|
| PACS surround | `#1C1F22` | viewer background — a dark neutral is functional for image perception, as on clinical workstations |
| Film black | `#000000` | letterbox around the radiograph |
| Report paper | `#F3F5F6` | the rail and pages: a cool report-sheet white |
| Report ink | `#1D2329` | text on paper |
| Lightbox cyan | `#35C9DD` | expert truth: outlines, "found" chips |
| Grease-pencil amber | `#F0A92E` | the learner: marks, arrows, search trace ramp |
| Graticule | `#8C99A6` | anatomy lines at ~40% opacity |

Cyan vs amber is the only color logic (truth vs you) and is color-blind safe; never use red/green to encode correctness. Misses are cyan outlines with a "missed" chip; overcalls are amber marks with a hollow ring.

**Type:** Atkinson Hyperlegible Next for everything (designed for legibility; fits a clinical reading task). Scale 15 / 17 / 20 / 26 / 34 px. `font-variant-numeric: tabular-nums` for statistics. Sentence case everywhere; no all-caps labels.

### 14.2 Layout
```
┌──────────────────────────────────────────────────────┬────────────────────────────┐
│ Practice   Case 7                       Loupe  Proj. │ Your read                  │
│                                                      │  Marks: 2                  │
│                                                      │  Global findings  □ □ □ □  │
│            radiograph on PACS surround               │  Call it normal            │
│            (zoom, pan, loupe)                        │  Hints left: 3             │
│                                                      │  [ Submit read ]           │
│                                                      ├────────────────────────────┤
│                                                      │ after submit → the debrief │
└──────────────────────────────────────────────────────┴────────────────────────────┘
```
Viewer ≈ 68% width, rail ≥ 360 px. Targets: 1280×800 laptop and 1920×1080 projector. The dashboard is a single report-style column (sections separated by rules), not a grid of identical cards.

### 14.3 The one memorable moment: the reveal
On submit, one sequence (~1.2 s total; instant under `prefers-reduced-motion`):
1. Search trace (amber density) fades in at 45% opacity — "where you looked."
2. Expert outline draws itself in cyan (stroke-dashoffset).
3. A hand-drawn grease-pencil arrow sweeps from the nearest wrong mark (or the image center if none) to each missed finding, with the spatial-relation text.
4. Outcome chips settle in the rail: *Never looked there* · *Looked past it* · *Looked, judged it normal* · *Found it, named it wrong* · *Called something that isn't there* · *Found it*.
Nothing else in the app animates on its own.

### 14.4 Copy
Plain verbs; buttons say what happens: "Submit read", "Next case", "Call it normal", "Show anatomy", "Ask the tutor". Errors say what happened and how to fix it ("The tutor is offline. Showing the built-in explanation instead."). Empty dashboard: "Read 5 cases to see your first learning curve."

### 14.5 Pages
`/` onboarding (name or participant code, level, mode; a 3-line explanation: "Mark what you see. We'll show you how you looked.") · `/read` reading room · `/progress` reading log · `/cohort` instructor · `/review` expert review · `/about` data sources, attributions, disclaimer · `/dev/case/:id` overlays for clinical QA.

---

## 15. Milestones, owners, and waves

### 15.1 Ownership (edit only what you own; request contract changes in PROGRESS.md)
| path | owner |
|---|---|
| `shared/`, `config/`, `Makefile`, `pyproject.toml`, `CLAUDE.md`, `docs/PLAN.md` | orchestrator (main session) |
| `pipeline/ingest_chestxdet.py`, `pipeline/splits.py`, `pipeline/qa_contact_sheet.py`, `data/` | data-engineer |
| `pipeline/anatomy/`, `pipeline/features/` | vision-ml-engineer |
| `backend/app/` except `tutor/` and `prompts/` | backend-engineer |
| `backend/app/tutor/`, `backend/app/prompts/`, `content/teaching_cards/` | tutor-prompt-engineer |
| `frontend/` | frontend-engineer |
| `eval/` | eval-scientist |
| `tests/e2e/`, `docs/REVIEW_NOTES.md` | qa-reviewer |

### 15.2 Milestones and acceptance checks
**M0 — Contracts and scaffold** (orchestrator, ~45 min)
- `make setup` succeeds; `uv run pytest -q` runs; frontend builds; `make dev` serves `/api/health` → `{ok: true}` and a frontend shell.
- `shared/schemas/` holds JSON Schemas for Case, Finding, TelemetryEvent, AttemptSubmit, SubmitResult, DebriefFacts, DebriefOutput; frontend types are generated from them (json-schema-to-typescript) or hand-written with a contract test that fails on drift.
- `config/*.yaml` present (defaults shipped in the kit); `docs/PLAN.md` and `docs/PROGRESS.md` exist.

**M1 — Data** (data-engineer, ~2 h)
- `cases.jsonl` validates 100%; ≥ 3,000 cases; ≥ 90% of instances have polygon masks; normals counted and reported.
- Every sym mapped; every mask non-empty and inside the image.
- `splits.json`: `assess_A`, `assess_B` (20 each, 8 normal / 12 abnormal), `bench`, `practice`, `holdout`; disjointness tested.
- Contact sheets in `data/qa/`; `ingest_stats.json` written; pipeline tests pass.

**M2 — Anatomy, zones, features** (vision-ml-engineer, ~3 h + background compute)
- Anatomy npz for ≥ 95% of in-scope cases; orientation report written; failures flagged and excluded.
- Unit tests for `derive_zones` on synthetic masks (thirds, lateral side, patient-side naming, retrocardiac).
- Every focal finding has `side`, `zones`, `primary_zone`, `relative_location`, features, and the case has `b0` and CTR.
- 20 random overlay PNGs in `data/qa/anatomy_*.png`; heart on the image's right in ≥ 90% of non-flagged cases.

**M3 — Engines, API, DB** (backend-engineer, ~4 h; engines can start on synthetic fixtures before M1/M2 land)
- Tests: hit test; Hungarian matching incl. duplicates and related labels; outcomes and scores; dwell + miss types on scripted telemetry; coverage; Elo math; GT-leak invariant on `/next` and assessment submits.
- All §13 endpoints implemented; OpenAPI ↔ `shared/schemas` contract test; `make db-reset` idempotent.

**M4 — Reading room UI** (frontend-engineer, ~5 h; start against a mock API)
- Playwright (offline mode): onboarding → case loads → zoom/pan → loupe → 2 marks with labels and confidence → hint → submit → reveal shows trace + outline + arrow → facts card → debrief (template) → next case. Screenshots saved.
- Telemetry: ≥ 30 events per 10 s of movement; coordinate mapping within 2 px at 1× and 3× zoom.
- Projector mode, keyboard shortcuts, reduced motion.

**M5 — Claude tutor** (tutor-prompt-engineer; backend wires routes, ~4 h)
- 13 teaching cards + `zone_mimics` drafted (`ai_draft`), schema-valid; Radiopaedia URLs verified (one GET each) or null.
- Facts builder, renderer, client, validator, templates, cache, hints, ask — unit-tested with a mocked client. The validator catches seeded laterality, zone, label, and banned-content errors.
- Offline: every result type has a validator-passing template.
- **Human checkpoint** before the first live call. Then a live smoke test: 10 debriefs on bench cases → `eval/samples/debriefs_smoke.jsonl`; p50 latency logged; zero validator failures after regeneration.

**M6 — Adaptive engine and dashboards** (backend + frontend, ~3 h)
- Simulation tests from §9.4 pass.
- Learner dashboard renders learning curve, miss-type mix, calibration, blind-spot map, FROC from real attempts; cohort view works; assessment mode withholds feedback and shows the summary.

**M7 — Evaluation and review** (eval-scientist; frontend builds `/review`, ~4 h + run time)
- §12.1 and §12.2 run in dry-run mode, then live after the cost checkpoint; reports and figures in `eval/reports/`.
- `/review` works end to end; ratings stored; CSV export.
- Pilot flow (A → practice → B, counterbalanced) and SUS form work; `pilot_analysis.py` runs on the DB.

**M8 — Demo hardening** (orchestrator + qa-reviewer, ~3 h)
- `make demo` seeds the playlist, warms the debrief cache, enables projector mode.
- The full demo e2e passes 3 times in a row, both offline and online. Cold start < 10 s; reveal < 300 ms; cached debrief < 200 ms.
- `/about` attributions complete; disclaimer visible on every page footer; README run steps verified from a clean clone.

### 15.3 Parallel waves (times are targets, not promises)
| wave | when | runs in parallel |
|---|---|---|
| W0 | Mon ~21:30–22:15 | orchestrator: M0 (contracts first, then scaffold) |
| W1 | Mon 22:15 → overnight | data-engineer M1 · backend M3 engines on synthetic fixtures · frontend M4 viewer on mock API · tutor M5 cards, prompts, validator on mocks |
| W2 | overnight → Tue AM | vision-ml M2 (after M1; long compute in background) · backend M3 API + DB · frontend M4 reveal + facts card · eval M7 harness in dry-run |
| W3 | Tue | integrate real data end to end · M5 live debrief (after checkpoint) · M6 · qa e2e |
| W4 | Wed | M7 live runs · `/review` · pilot tooling · M8 · **18:00 feature freeze for the pilot** |
| W5 | Thu | fixes from pilot and radiologist review only · **14:00 code freeze** |

QA gates (qa-reviewer) after M1, M3, M4, M5, M6, M8: run checks, review diffs, file issues in `docs/REVIEW_NOTES.md`; the orchestrator assigns fixes.

---

## 16. Testing strategy
- **Python unit tests:** scoring, matching, dwell, miss types, coverage, zones (synthetic masks), Elo, facts builder, validator, templates, cache keys, GT-leak invariant.
- **Fixtures:** `pipeline/tests/fixtures/` holds 10 tiny synthetic cases (e.g. 256×256 with drawn masks) so tests never need the real dataset.
- **Contract tests:** Pydantic ↔ JSON Schema ↔ TS types.
- **Frontend:** Vitest for coordinate math and reducers; Playwright e2e in offline mode; screenshots in `tests/e2e/__screenshots__/` for human review.
- **Never** call the Anthropic API from unit tests or CI; mock the client.

---

## 17. Demo hardening
- `config/demo_playlist.yaml` (Sri picks Wednesday from `/dev`): 6 cases with talking points — (1) small apical pneumothorax (search-error story), (2) retrocardiac or hilar finding (decision-error story), (3) effusion (an easy win), (4) a normal film (specificity + calibration), (5) a multi-finding case (satisfaction of search), (6) cardiomegaly with the CTR overlay.
- Rehearse the exact clicks; the debrief cache key (§8.7) makes rehearsed paths instant. Offline mode as a fallback.
- Projector mode on; test it on the actual MEB projector at 17:30 Thursday.
- Dashboards in the demo show only real attempts (team + pilot). If any simulated data is ever shown, it must be visibly labeled.
- Backup: a 90-second screen recording of the full flow (record Thursday morning).

---

## 18. Stretch (P2) — only after P0 and P1 are green
- **S1 VinDr-CXR** via Kaggle (human must accept the rules): per-reader boxes → agreement feature for difficulty; bigger bank.
- **S2 CXAS** (`pip install cxas`, 159 anatomical classes incl. lobes and ribs) for richer location language; check its license before use.
- **S3 AI second reader:** fine-tune a detector on VinDr (e.g. on free Kaggle GPUs); show the model's guess after the learner's read; correlate model confidence with human success.
- **S4 Webcam gaze** (e.g. WebGazer.js, GPL) on 2–3 people to compare against the cursor/loupe proxy.
- **S5 Second module:** musculoskeletal fracture radiographs (e.g. FracAtlas or GRAZPEDWRI-DX; verify licenses); the schema is modality-agnostic.
- **S6 Hosted deploy** behind a password; no public redistribution of dataset images.

---

## 19. Risks and fallbacks
| risk | fallback |
|---|---|
| HF mirror unavailable or malformed | Deepwise GitHub JSON + NIH images; then NIH bbox subset |
| torch/TXV install pain | CPU wheels; or run segmentation on Colab/Kaggle and download the npz files |
| Segmentation fails on some films | flag and exclude; approximate zones marked `approximate` |
| API slow, down, or out of credit | instant facts card + template debrief + cache; `BLINDSPOT_OFFLINE=1` |
| Judges question the cursor-as-gaze proxy | say it plainly: a proxy, labeled in the UI; grounded in viewport-log research; validation is on the roadmap (S4) |
| Scope creep | P0 list wins; feature freeze Wed 18:00; code freeze Thu 14:00 |
| Venue Wi-Fi | everything runs locally; phone hotspot as a backup |
| Projector washes out images | projector mode; demo on the laptop screen as well |
| Usage limits in Claude Code | subagents on cheaper models (see README); main session for integration only |

---

## 20. Safety, ethics, licensing
- **Education only.** Footer on every page: "For education. Not for clinical use." No uploads of real patient images in this build.
- **Data:** public, de-identified research datasets only; no PHI. NIH ChestX-ray14 requires attribution (link, citation, NIH Clinical Center acknowledgment — confirm in its README). Cite ChestX-Det. VinDr (if used) per Kaggle/PhysioNet terms. Keep the repo private; never commit `data/`; no public hosting of dataset images. Radiopaedia: links only.
- **LLM safety:** facts-only prompting, validator, judge evaluation, clinician review, provenance badges on every debrief.
- **Pilot:** voluntary, anonymous participant codes, no grades, framed as product usability testing. Don't present it as research; publishing later would need UVA IRB review.
- **Bias and limits:** NIH images come from a single US center; label noise exists even in expert sets; the miss-type engine is a proxy. Say so on `/about`.
