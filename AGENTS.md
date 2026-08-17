# AI-DOS Shared Agent Contract

This file governs every AI tool and human contributor in this repository. More-specific `AGENTS.md` files may add constraints but must not weaken security, ownership, or quality gates here.

## What this repository is

**ChronoScalp** — a multi-timeframe algorithmic scalping bot for XAUUSD / EURUSD
and broker-native crosses. It moves real money, so the constraints below
outrank convenience, backtest results, and any generic process guidance.

| Doc | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Standing rules, workflow, where-to-look map |
| [README.md](README.md) | Setup, run modes, architecture summary |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Broker split (MT5 Windows vs OANDA Linux) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phase checklist — re-check before new work |
| [docs/VPS_TROUBLESHOOTING_FA.md](docs/VPS_TROUBLESHOOTING_FA.md) | Windows VPS ops runbook |

## Hard constraints — never violate

1. Never loosen risk management to chase win rate. Max **1%** equity risk per
   trade and minimum **1:1.5** R:R in `config/settings.yaml` are fixed
   constraints, not tuning parameters. If a change to `risk/` or `strategy/`
   would breach them, stop and flag it instead of implementing it.
2. Never remove, default, or weaken the `CHRONOSCALP_CONFIRM_LIVE` gate in
   `scripts/run_live.py`. The friction is intentional.
3. Broker SDKs (`MetaTrader5`, REST clients) may only be imported inside
   `src/chronoscalp/execution/*_broker.py` and the data connectors. Strategy,
   risk, and filter modules depend on the `Broker` interface in
   `execution/broker.py`, never a concrete SDK.
4. The `MetaTrader5` pip package is Windows-only. Do not write code that
   assumes it imports on Linux/macOS, and do not swallow the ImportError.
5. New strategy or risk logic needs a matching `tests/` file before it counts
   as done — silent regressions here cost money.
6. Never commit secrets (`.env`, `لاگین.txt`, hardcoded API/MT5 passwords).
   `.env.example` carries placeholders only.
7. Strategy Delta (`strategy/delta.py`) is not live-ready until the validation
   gates in `docs/STRATEGY_DELTA.md` pass. Do not describe it as guaranteed.

## Branching

Default branch is **`main`**. Keep task work on short-lived `ai/*` or `cursor/*`
branches and merge to `main` when done — do not leave finished work stranded on
a remote feature branch.

## Start of every session

Read, in order: this file, `.ai-dos/ai-dos.yaml`, `.ai-dos/project/overview.md`, `.ai-dos/project/architecture.md`, `.ai-dos/project/status.md`, `.ai-dos/tasks/active.yaml`, and `.ai-dos/tasks/handoff.md`. Treat repository evidence as authoritative; mark unknown facts instead of inventing them.

## Roles

- Orchestrator: decomposes work, assigns owners, resolves dependencies, and enforces gates.
- Architect: defines boundaries, invariants, ADRs, acceptance criteria, and migration/rollback strategy.
- Implementer: changes only the assigned task and claimed files; supplies tests and evidence.
- Reviewer: independently reviews the diff, edge cases, regressions, and acceptance criteria.
- Security: reviews trust boundaries, auth, secrets, inputs, dependencies, and abuse cases.

One agent may hold multiple roles only when recorded in the task. High-risk changes require Reviewer and Security identities distinct from Implementer.

## Ownership and concurrency

`.ai-dos/tasks/active.yaml` is the source of truth. Before editing, create or claim a task with one owner, branch, worktree, acceptance criteria, and explicit `file_claims`. Do not edit a file claimed by another active task. Glob claims are discouraged; shared/generated/lock files require an explicit handoff. A stale claim may be reclaimed only after recording the reason and notifying the previous owner in `.ai-dos/tasks/handoff.md`.

Use one branch and preferably one Git worktree per task. Branch format: `ai/<task-id>-<slug>` (or `fix/`, `feat/`, `chore/`). Never share a worktree between simultaneous writers. Rebase/merge the base branch before final review and resolve conflicts in the owning task.

## Execution protocol

1. Discover verified context and current tests.
2. Define scope, non-goals, acceptance criteria, risk, rollback, and validation.
3. Claim task and files before modification.
4. Make the smallest coherent change; do not rewrite unrelated user work.
5. Run configured gates and attach commands/results to handoff.
6. Obtain independent review appropriate to risk.
7. Update project status and handoff; release claims only after commit or explicit abandonment.

Stop and escalate on conflicting claims, unclear destructive action, missing authority, secrets exposure, or an architectural choice that materially changes scope.

## Context budget

Load progressively: contract/status/task first, then only relevant architecture and files. Prefer summaries and exact paths over raw logs. At the threshold configured in `ai-dos.yaml`, create a checkpoint in `handoff.md`: objective, decisions, changed files, tests, failures, next action, and unresolved risks. Start a fresh session at phase boundaries or after compaction.

## Quality and security

All enabled gates in `.ai-dos/ai-dos.yaml` must pass or have a recorded, approved exception. New behavior needs proportionate tests. Never commit secrets, weaken auth/TLS, execute untrusted input, or add dependencies without review. Report findings by severity with file/evidence, impact, and remediation. “Done” means acceptance criteria met, tests recorded, review complete, documentation updated, and handoff usable by a fresh agent.

