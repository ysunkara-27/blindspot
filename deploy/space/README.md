---
title: Blindspot
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Chest X-ray perception trainer (education only)
---

# Blindspot

A chest X-ray perception trainer for medical students. For education only; not for clinical use.

The app is served under `/blindspot/` and is gated by an access code. Open it through
https://ysunkara.com/blindspot/ (or `/blindspot/` on this Space's own URL).

The container holds no dataset: at start it downloads a private, access-controlled data bundle. Dataset images
are not redistributed publicly. Deployment notes: `deploy/README.md` in the source repository.

## Settings (Space → Settings)

Secrets: `ANTHROPIC_API_KEY`, `HF_TOKEN`, `BLINDSPOT_ACCESS_CODE`, `BLINDSPOT_REVIEW_CODE`.

Variables: `BLINDSPOT_BASE_PATH`, `BLINDSPOT_DATA_REPO`, `BLINDSPOT_MODEL_DEBRIEF`, `BLINDSPOT_MODEL_FAST`,
`BLINDSPOT_MAX_LIVE_CALLS_PER_MIN`, `BLINDSPOT_BUDGET_USD_HOURLY` (2), `BLINDSPOT_BUDGET_USD_DAILY` (8),
`BLINDSPOT_BUDGET_USD_TOTAL` (60), `BLINDSPOT_CREDIT_RETRY_MIN` (15), `BLINDSPOT_PRICE_IN_PER_MTOK` (2.0),
`BLINDSPOT_PRICE_OUT_PER_MTOK` (10.0), `BLINDSPOT_ANALYTICS_URL`, optional `BLINDSPOT_SEED_DEMO`,
`BLINDSPOT_CORS_ORIGINS`.

Secrets and variables can be changed in Settings without a rebuild: the Space restarts and picks them up. When
Anthropic credits run out or a budget is reached, the tutor keeps working with built-in explanations and
`/api/health` says why (`tutor.mode`); `POST /api/admin/tutor/resume` with the review code clears a pause early.
