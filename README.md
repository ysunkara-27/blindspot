# Blindspot build kit

A ready-to-run Claude Code project for the UVA SoM AIM × Anthropic hackathon (Oct 5–8, 2026). It contains the full spec, the research behind it, seven project subagents, config defaults, and the kickoff prompt. Claude Code writes all the code during the event.

**Blindspot** is a chest X-ray perception trainer: learners mark findings on radiologist-annotated X-rays, and the tool shows them *how* they missed what they missed (never looked there, looked past it, looked and judged it normal), with a Claude debrief grounded in computed facts and checked by a validator.

## What's inside
| file | what it is |
|---|---|
| `KICKOFF_PROMPT.md` | the message you paste into Claude Code |
| `CLAUDE.md` | standing rules; loaded by the main session and every subagent |
| `docs/SPEC.md` | full build spec: architecture, algorithms, schemas, prompts, milestones, acceptance checks |
| `docs/RESEARCH.md` | evidence, prior art, datasets and licenses, citations (pitch material) |
| `docs/DEMO_AND_PITCH.md` | team roles, Mon→Thu timeline, pilot and radiologist-review protocols, pitch, demo script, judge Q&A |
| `docs/PROGRESS.md` | build log template |
| `config/*.yaml` | taxonomy, zones/review areas, scoring thresholds, adaptive settings, demo playlist |
| `.claude/agents/*.md` | data-engineer, vision-ml-engineer, backend-engineer, frontend-engineer, tutor-prompt-engineer, eval-scientist, qa-reviewer |
| `.claude/settings.json` | pre-approved commands so long runs don't stall on permission prompts |

## Start tonight (about 15 minutes)
1. **Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+, git, about 6 GB free disk. macOS or Linux.
2. **Make the repo** (keep it private):
   ```bash
   unzip blindspot-kit.zip && cd blindspot
   git init && git add -A && git commit -m "chore: kit"
   cp .env.example .env      # then paste your API key into .env
   ```
3. **API key for the app.** Your Max plan covers Claude Code, not the app's own API calls. Create a key in the Claude Console and ask the organizers about Anthropic credits. Expected spend for the whole hackathon is roughly $25–40.
4. **Launch Claude Code** in the repo:
   ```bash
   claude --permission-mode auto     # if your account offers auto mode; otherwise just `claude`
   ```
   If you can't use auto mode, press Shift+Tab until edits are auto-accepted; `.claude/settings.json` already allows the common commands.
5. **Set the model and effort**, then paste `KICKOFF_PROMPT.md` (everything below its line):
   ```
   /model fable
   /effort xhigh
   ```
6. **Answer the human checkpoints** when it stops: confirming the API key exists, approving eval spend over $5, any dataset terms, and deletions outside `data/`.

## Model and usage strategy
- The main session runs Fable at `xhigh`: it plans, writes the contracts, and integrates.
- Subagents default to Opus (builders, ML, tutor, evals) and Sonnet (QA). Subagent usage counts against the same plan limits as your main session, and seven agents in parallel burn usage fast. Running out on Wednesday would hurt more than slightly weaker boilerplate.
- **Max-power switch** (everything on Fable), if you have headroom:
  ```bash
  CLAUDE_CODE_SUBAGENT_MODEL=fable CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 claude --permission-mode auto
  ```
- If you hit limits: drop subagents to Sonnet with `CLAUDE_CODE_SUBAGENT_MODEL=sonnet CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`, and keep the main session for integration and debugging.
- `max` effort mostly adds tokens; use it only for a nasty bug. `ultracode` (xhigh plus automatic multi-agent workflows) is an alternative if you'd rather let Claude Code orchestrate itself.

## Watching it work
- `/tasks` shows running subagents and their models.
- `docs/PROGRESS.md` is the build log; `docs/PLAN.md` the plan; `docs/REVIEW_NOTES.md` QA findings; `logs/` long jobs.
- Overnight: leave it running in auto mode; the anatomy segmentation runs in the background.

## What your teammates do
See `docs/DEMO_AND_PITCH.md` §1–§2. In short: Sri reviews the teaching cards and picks the demo cases and radiologist reviewers; AG builds the pitch, runs the Wednesday pilot, and turns `eval/reports/REPORT.md` into slides.

## If something breaks
Look in PROGRESS.md for `BLOCKED:` entries; SPEC §19 lists the fallback for each known risk. `BLINDSPOT_OFFLINE=1` makes the app run without the API.
