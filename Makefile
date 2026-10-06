# Blindspot — one Makefile orchestrates everything (no Docker).
SHELL := /bin/bash
UV ?= uv
NPM ?= npm
export BLINDSPOT_DATA_DIR ?= ./data
export BLINDSPOT_DB_PATH ?= ./data/blindspot.sqlite

.PHONY: setup data anatomy features dev api web test test-py test-web e2e lint eval-vlm eval-faith report demo db-reset types clean-logs

setup:
	$(UV) sync --extra dev --extra eval
	cd frontend && $(NPM) install
	mkdir -p data logs eval/reports eval/cache
	@test -f .env || cp .env.example .env
	@echo "setup done — put ANTHROPIC_API_KEY in .env (never commit it)"

setup-ml:
	$(UV) sync --extra dev --extra eval --extra ml

data:
	mkdir -p logs data
	$(UV) run python -m pipeline.ingest_chestxdet 2>&1 | tee logs/ingest.log
	$(UV) run python -m pipeline.splits 2>&1 | tee logs/splits.log
	$(UV) run python -m pipeline.qa_contact_sheet 2>&1 | tee logs/qa_contact_sheet.log

anatomy:
	mkdir -p logs
	$(UV) run python -m pipeline.anatomy.segment --resume 2>&1 | tee -a logs/anatomy.log
	$(UV) run python -m pipeline.anatomy.orientation 2>&1 | tee -a logs/anatomy.log
	$(UV) run python -m pipeline.anatomy.zones 2>&1 | tee -a logs/anatomy.log

features:
	$(UV) run python -m pipeline.features.lesion 2>&1 | tee logs/features.log
	$(UV) run python -m pipeline.features.ctr 2>&1 | tee -a logs/features.log
	$(UV) run python -m pipeline.features.difficulty 2>&1 | tee -a logs/features.log
	$(UV) run python -m pipeline.splits --rebalance 2>&1 | tee -a logs/features.log

api:
	$(UV) run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd frontend && $(NPM) run dev -- --host 127.0.0.1 --port 5173

dev:
	@mkdir -p logs
	@trap 'kill 0' EXIT; \
	  ($(UV) run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload 2>&1 | tee logs/api.log) & \
	  (cd frontend && $(NPM) run dev -- --host 127.0.0.1 --port 5173 2>&1 | tee ../logs/web.log) & \
	  wait

test: test-py test-web

test-py:
	$(UV) run pytest -q

test-web:
	cd frontend && $(NPM) run test -- --run

e2e:
	cd frontend && BLINDSPOT_OFFLINE=1 npx playwright test --config ../tests/e2e/playwright.config.ts

lint:
	$(UV) run ruff check . && $(UV) run ruff format --check .
	cd frontend && $(NPM) run lint && npx tsc --noEmit -p tsconfig.app.json

types:
	cd frontend && $(NPM) run gen:types

eval-vlm:
	$(UV) run python -m eval.vlm_localization $(ARGS)

eval-faith:
	$(UV) run python -m eval.faithfulness $(ARGS)

report:
	$(UV) run python -m eval.report

demo:
	$(UV) run python -m backend.app.demo_seed
	@echo "open http://127.0.0.1:5173/?projector=1"
	$(MAKE) dev

db-reset:
	$(UV) run python -m backend.app.db --reset

clean-logs:
	rm -f logs/*.log
