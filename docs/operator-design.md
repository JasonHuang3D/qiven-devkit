# Qiven Operator Phase 1

Qiven Operator is the shared local engineering orchestration layer for Qiven repositories. Windows CMD remains a thin entry point; Python owns orchestration, human-facing output, process execution, validation semantics, and asynchronous service integration.

## Phase 1 goals

- one reusable Python runtime copied into every Devkit-managed repository;
- deterministic human output with `[ RUN]`, `[WAIT]`, `[ OK ]`, and `[FAIL]` states;
- TTY-aware color with deterministic plain-text output for redirection/CI;
- buffered child logs with failure detail and optional verbose success logs;
- fail-fast sequential gates plus bounded parallel execution for independent tasks;
- truthful heartbeat output for long silent work;
- exact Git HEAD, diff-check, and real clean-tree validation gates;
- asynchronous GitHub Actions dispatch as an asynchronous operation, never hidden behind hard-coded polling delays;
- machine-readable JSON output for future agents/automation.

## Non-goals

Phase 1 does not introduce a daemon, RPC service, webhook server, plugin framework, general task DSL, or cross-repository coordinator. Those require concrete recurring demand.

## Ownership

Devkit owns the Operator runtime and shared mechanisms. Individual repositories provide policy through `.qiven/operator.json`; generated repositories do not call back into a Devkit checkout.

The runtime is intentionally Python-standard-library-only in Phase 1 so a repository does not acquire a package-manager bootstrap dependency merely to validate itself.

## Command surface

`tools\\qiven.cmd` is the Windows entry point. It invokes `tools/qiven.py`, which delegates to the managed `tools/qiven_operator` package.

Initial commands:

- `qiven info` — show repository/operator metadata;
- `qiven gate [--expect-head SHA]` — execute the repository's declared local validation gate;
- `qiven ci start <profile>` — dispatch a declared GitHub Actions profile and return immediately;
- `qiven run <task>...` — execute one or more declared tasks, sequentially by default and in parallel when explicitly requested.

`--json` switches terminal rendering to a stable machine-readable result envelope.

## Async CI semantics

CI dispatch is asynchronous. `ci start` validates the local repository/branch/HEAD context, dispatches through `gh workflow run`, prints the correlation inputs it knows, and exits. It does not sleep, discover a "latest" run, or poll GitHub merely to make an asynchronous operation look synchronous.

Future event-driven coordination may map a request identity to an exact run through workflow inputs, run-name metadata, webhooks, `workflow_run`, or a dedicated coordinator. That is intentionally outside Phase 1.
