# Blindspot — rules for Claude Code (main session and every subagent)

## Mission
A chest X-ray perception trainer. Learners mark findings on radiologist-annotated radiographs; we score localization against expert masks, replay their search (loupe/zoom/pan telemetry), classify each miss (search / recognition / decision / interpretation / overcall), and Claude delivers a short debrief grounded in facts we computed. Adaptive case selection and learning analytics. Demo Thursday Oct 8, 6 PM. **Code freeze Thursday 2 PM. Feature freeze Wednesday 6 PM.**

Full spec: `docs/SPEC.md` (authoritative for what to build). Evidence: `docs/RESEARCH.md`. Human plan: `docs/DEMO_AND_PITCH.md`.

## Non-negotiables
1. **Truth comes from radiologist annotations.** Claude never decides what is on an image; it explains `DebriefFacts` built by code. Every debrief passes the validator or falls back to a template.
2. **No ground truth reaches the client before that attempt is submitted** (and none during Assessment mode until the summary). Tested.
3. **Patient-side convention:** patient RIGHT is displayed on the image LEFT. Zone ids name the patient's side. Tests assert this.
4. **No fabricated data or results.** Synthetic learners exist only in tests and are labeled synthetic. Reports state n. Never present simulated numbers as real.
5. **No Anthropic API calls in unit tests** (mock the client). Live calls only from the running app or eval scripts with `--max-cost`, caching, and a human checkpoint before the first run.
6. **Secrets and data:** never print or commit `ANTHROPIC_API_KEY`; never commit `data/`, `logs/`, `.env`, weights, or images. Repo stays private. Radiopaedia is link-only; no scraping.
7. **Education only:** no clinical management advice in any generated text; disclaimer in the footer.
8. **Model IDs come from env vars** (`BLINDSPOT_MODEL_*`), never hard-coded in app code.
9. **Never state centimetres** unless `pixel_spacing_mm` is known (it isn't for ChestX-Det).

## Stack and layout
Python ≥3.11 + uv (one project at repo root: `backend/`, `pipeline/`, `eval/`), FastAPI, Pydantic v2, SQLite, NumPy/SciPy/OpenCV, torch + torchxrayvision. Frontend: Vite + React + TypeScript (strict), TanStack Query, Recharts, CSS modules + CSS variables. Playwright e2e. Layout and file map: SPEC §2.2.

## Commands
`make setup` · `make data` · `make anatomy` · `make features` · `make dev` (API :8000, web :5173) · `make test` · `make e2e` · `make lint` · `make eval-vlm` · `make eval-faith` · `make report` · `make demo` · `make db-reset`

## Conventions
- Coordinates: pixel space of the canonical 1024 px PNG; origin top-left; x right, y down; floats.
- IDs: case `cxd_<id>`; finding `<case_id>#F<n>`; marks `M<n>`.
- Python: type hints, ruff format + lint, pytest, small pure functions for engines (scoring, search, zones, Elo) so they are easy to test.
- TypeScript: strict; API types generated from `shared/schemas/` (or contract-tested against them).
- Config, not constants: thresholds and weights live in `config/*.yaml`.
- Long jobs (downloads, segmentation, evals) run in the background, log to `logs/<job>.log`, and are resumable.

## Ownership (edit only what you own)
orchestrator: `shared/`, `config/`, `Makefile`, `pyproject.toml`, `CLAUDE.md`, `docs/PLAN.md` · data-engineer: `pipeline/ingest_*`, `pipeline/splits.py`, `pipeline/qa_*`, `data/` · vision-ml-engineer: `pipeline/anatomy/`, `pipeline/features/` · backend-engineer: `backend/app/` except `tutor/` and `prompts/` · tutor-prompt-engineer: `backend/app/tutor/`, `backend/app/prompts/`, `content/teaching_cards/` · frontend-engineer: `frontend/` · eval-scientist: `eval/` · qa-reviewer: `tests/e2e/`, `docs/REVIEW_NOTES.md`.
Need a contract change? Write `CONTRACT CHANGE REQUEST: <what/why>` in `docs/PROGRESS.md`; the orchestrator decides and edits `shared/`.

## Working agreements
- Before coding a component, read its SPEC section. Implement the simplest version that meets the acceptance checks, then improve.
- A milestone is done only when its acceptance checks pass; paste a short summary of the check output into `docs/PROGRESS.md`.
- Commit after each green milestone with a conventional message (`feat(scoring): …`). Never `git push` without asking.
- Stuck for more than 30 minutes? Write `BLOCKED: <problem> — options: …` in PROGRESS.md, take the fallback from SPEC §19, keep moving.
- Subagent reports back in ≤ 25 lines: what changed (files), how verified (commands + results), open issues, next suggested step.
- UI work: verify with Playwright screenshots, not just by reading code.

## Human checkpoints (stop and ask Yash)
Before the first live Anthropic API call · before any eval run estimated > $5 · whenever a dataset needs credentials or accepting terms (e.g. Kaggle) · before deleting anything outside `data/` and `logs/`.
