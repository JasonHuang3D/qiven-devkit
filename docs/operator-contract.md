# Qiven Operator Contract (current)

> This document states the operator contract as IMPLEMENTED and
> accepted today, derived from `tools/qiven_operator.py`,
> `.qiven/operator.json` and ADR-0046/0052. The Phase-1 design document
> it replaces is preserved at `docs/legacy/design/operator-phase1.md`.

## What the Operator is

The Qiven Operator is the shared Python orchestration layer behind
human- and agent-facing engineering commands in every managed
repository. Windows CMD (`tools\qiven.cmd`) is a thin entry point;
Python owns process execution, layout/color, buffered logs, heartbeat,
parallel task groups, fail-fast gates, exact Git validation, bounded
process custody, and asynchronous CI dispatch/observation semantics.
Standard-library only; Python 3.9+ (`QIVEN_PYTHON` override honored).

## Ownership and distribution states (ADR-0046 → ADR-0052)

- Devkit owns the Operator MECHANISM; each repository owns its
  declarative policy (`.qiven/operator.json`: tasks, gates, CI
  profiles).
- Two ownership states exist and must not be conflated:
  1. **Vendored copies** (historical): repositories generated before
     ADR-0046 carry their own operator snapshot; the generation
     template no longer materializes this shape (v44 template 0.1.10
     retirement), and surviving grandfathered instances are tracked
     as fail-closed sync conflicts pending the wr6-report
     consolidation residual.
  2. **Workspace-resolved** (ADR-0052 endpoint, DELIVERED through
     WR-8, 2026-09-28): the workspace control lock
     (`qiven-workspace/workspace.lock.json`) selects revisions
     (repository-manifest declarations, `shadow_only: false` on all
     nodes); each repository's `tools/qiven.py` is a thin launcher
     that runs the bootstrap identity-check BEFORE any Devkit import
     (WR-6; no `QIVEN_DEVKIT_ROOT`, no consumer-local pin), and
     `qiven-bootstrap.py gate-configure` supplies the resolution file
     to CMake. The rollout is universal across the governed workspace;
     the former ADR-0046 shim+pin stage is historical record.

## Command surface (current)

- `qiven info` — repository/operator metadata.
- `qiven gate [--expect-head SHA]` — the repository's declared local
  validation gate (fail-fast; per-task receipts).
- `qiven run <task>... [--parallel]` — declared tasks, sequential by
  default.
- `qiven ci start <profile>` — exact-remote-identity dispatch through
  `gh`; asynchronous by contract (no sleeps, no latest-run guessing).
- `qiven ci watch [PROFILE]` (or explicit identity `--repo O/N
  --workflow W --branch B --head SHA`) — identity-bound,
  observation-only CI runner (ADR-0051-era addition): locks onto the
  exact head SHA with a same-head decoy guard, bounded internal polling
  (`--timeout` minutes, default 60 — inherently terminating), clean
  output, JSON receipt. It runs in the CALLER's foreground by design:
  place it under the harness's `run_in_background` (gate-class denial →
  guarded re-call); it does NOT self-detach and never routes through
  `qiven exec` (a watch observes a REMOTE run — ADR-0051).
- `qiven exec start/status/stop/list/sweep` — detached bounded custody for
  survival-class commands (ADR-0048): watchdog + KILL_ON_JOB_CLOSE
  Job-Object tree lifetime + lease; `CREATE_NO_WINDOW` children; the
  harness's `run_in_background` remains the default for ordinary
  in-session long work (ADR-0051).

`--json` selects the machine envelope; `--no-color` keeps the human
layout without ANSI.

## Process and output law (binding)

- Every task runs as a separate child process rooted at the repository
  root; task-local environment/working-directory changes cannot leak
  into the Operator, sibling tasks, or the invoking prompt. Batch
  children get a `cmd.exe /d /s /c` + `call` boundary.
- Human output is state-based (`[ RUN]` / `[WAIT]` / `[ OK ]` /
  `[FAIL]` + terminal summary); heartbeats report elapsed time only;
  no invented percentages or ETAs; child output buffered unless a task
  fails or verbose is requested (testing standard §14).
- Bounded custody is law for every spawned tree (ADR-0048); an exit no
  living supervisor observed is reported indeterminate, never guessed.
- The hook router (`tools/hook_exec_router.py`, Devkit-owned) enforces
  ADR-0051 routing and the heredoc-authorship deny at the ZCode
  PreToolUse boundary; every denial carries the `[qiven-hook]`
  provenance tag.

## Policy surface

Repository policy is declarative: `.qiven/operator.json` names tasks
(argv with `{python}`/`{cmake}`/`{ctest}` substitutions), gate
sequences (with parallel groups), and CI profiles (workflow +
inputs). Mechanism changes land in Devkit with its test suite; policy
changes are repository-local.
