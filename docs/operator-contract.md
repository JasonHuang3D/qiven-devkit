# Qiven Operator Contract (current)

> This document states the operator's OWNERSHIP and DISTRIBUTION contract.
> Usage law (command surface, routing, custody semantics, exit codes) has a
> single home: `docs/conventions/operator-usage.md`. The Phase-1 design
> document it grew from is preserved at `docs/legacy/design/operator-phase1.md`.

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

## Usage law — single home

Command surface, gate/run/ci/exec semantics, hook-router routing,
custody, exit codes and process/output laws:
`docs/conventions/operator-usage.md` plus the engineering standards —
this file does not restate them.

## Policy surface

Repository policy is declarative: `.qiven/operator.json` names tasks
(argv substitutions: `{root}`, `{python}`, `{cmake}`, `{ctest}`,
`{clang_format}`, `{toolchain_root}`; builtin task kinds: `exact_head`,
`git_diff_check`, `git_clean_tree`, `gate_proof`), gate
sequences (with parallel groups), and CI profiles (workflow +
inputs). Launcher/locator environment: `QIVEN_WORKSPACE_CONTROL`,
`QIVEN_DEVKIT_CHECKOUT` (and the full locator precedence:
qiven-workspace README "Locator vocabulary"). Deploy policy is separate: `.qiven/deploy.json` (schema
`qiven-deploy-policy-v1`; law: `docs/engineering/deployment.md`).
Mechanism changes land in Devkit with its test suite; policy
changes are repository-local.
