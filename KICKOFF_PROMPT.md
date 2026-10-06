# Kickoff prompt for Claude Code

Before pasting, in Claude Code:
1. `/model fable` (or the strongest model your plan lists)
2. `/effort xhigh` (`max` mostly burns usage; `ultracode` is an option if you want Claude Code to auto-orchestrate, but this prompt already defines the orchestration)
3. Permission mode: launch with `claude --permission-mode auto` if your account offers auto mode; otherwise press Shift+Tab until edits are auto-accepted. `.claude/settings.json` pre-approves the common commands.

Then paste everything below the line.

---

You are the orchestrator and lead engineer for **Blindspot**, a chest X-ray perception trainer we are building for the UVA School of Medicine AIM × Anthropic hackathon. It is Monday night, October 5. Demo night is Thursday, October 8, at 6:00 PM. Feature freeze is Wednesday 6:00 PM (we run a usability pilot that night); code freeze is Thursday 2:00 PM. We are three undergrads competing against Darden and School of Medicine teams, so the product has to be technically deep, evidence-backed, and demo-proof.

## Read first, in this order
1. `CLAUDE.md` — binding rules.
2. `docs/SPEC.md` — what to build and the acceptance checks. Read all of it; §0, §2, §13, and §15 most carefully.
3. `docs/RESEARCH.md` §2–§5 — why the design is the way it is.
4. `config/*.yaml` and `.claude/agents/*.md` — shipped defaults and your team.

## How we work
- **Plan.** Write `docs/PLAN.md` (≤ 150 lines): milestone → owner subagent → files → acceptance checks → estimate → dependencies, following SPEC §15. Start `docs/PROGRESS.md` (timestamped log; newest entries at the top). Then begin immediately; don't wait for approval unless a human checkpoint applies.
- **Contracts first (M0, you personally).** Create `shared/schemas/*.json`, the Pydantic API models, the generated (or contract-tested) TS types, `pyproject.toml`, `Makefile`, `.gitignore` additions, and the backend/frontend scaffolds. Reconcile the shipped `config/*.yaml` with the schemas. Freeze the contracts. Subagents never edit `shared/` or `config/`; they write a CONTRACT CHANGE REQUEST in PROGRESS.md and you decide.
- **Then run the waves in SPEC §15.3 in parallel** using the project subagents: `data-engineer`, `vision-ml-engineer`, `backend-engineer`, `frontend-engineer`, `tutor-prompt-engineer`, `eval-scientist`, `qa-reviewer`. Give each a self-contained brief: the SPEC sections to read, the files it owns, its acceptance checks, and the required report format (≤ 25 lines: files changed, how verified, open issues, next step). Independent work must not wait on other work: engines are built against synthetic fixtures, the UI against a mock API, the tutor against a mocked client.
- **Verification is mandatory.** A milestone is green only when its checks pass. Run them yourself or via `qa-reviewer`, and paste a short summary into PROGRESS.md. Look at UI screenshots before calling UI work done.
- **Integration is your job.** After each wave, pull the pieces together, run `make test` and `make e2e`, fix seams, and commit (`feat(...)`/`fix(...)`). Never commit `data/`, `logs/`, `.env`, weights, or images. Never push without asking.
- **Long jobs** (dataset download, anatomy segmentation, eval runs) go in the background with logs in `logs/`; keep other work moving while they run.
- **Blocked > 30 minutes?** Log `BLOCKED:` with options in PROGRESS.md, take the SPEC §19 fallback, continue.
- **Scope discipline.** P0 first, then P1. No P2 until P0 and P1 are green and I say go.
- **Status.** At the end of each wave, give me a 5-line status: done, in progress, blocked, next, anything you need from me.

## Human checkpoints — stop and ask me
- Before the first live Anthropic API call: confirm `ANTHROPIC_API_KEY` is set by checking that the variable exists (never print it).
- Before any evaluation run estimated above $5.
- If any dataset needs credentials or accepting terms (Kaggle, PhysioNet).
- Before deleting anything outside `data/` and `logs/`.

## Tonight's target (by Tuesday ~8 AM)
- M0 and M1 green. M2 finished or running in the background with progress logged.
- M3 scoring, search, and miss-type engines passing their tests on synthetic fixtures; API skeleton up.
- M4 viewer with zoom, pan, loupe, marks, and telemetry working on real cases.
- M5 teaching cards drafted (`ai_draft`), validator and templates tested, debrief pipeline working in offline mode.
- `make dev` lets me read 5 real cases, mark them, submit, and see the reveal (expert outline, my marks, search trace) plus the deterministic facts card.

Start now: (1) print toolchain versions (python, uv, node, npm, git) and free disk space, (2) write PLAN.md, (3) do M0, (4) launch Wave 1.
