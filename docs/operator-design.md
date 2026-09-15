# Qiven Operator Phase 1

Qiven Operator is the shared local engineering orchestration layer for Qiven repositories. Windows CMD remains a thin entry point; Python owns orchestration, human-facing output, process execution, validation semantics, and asynchronous service integration.

## Phase 1 goals

- one reusable Python runtime copied into every Devkit-managed repository;
- deterministic human output with `[ RUN]`, `[WAIT]`, `[ OK ]`, and `[FAIL]` states;
- TTY-aware color plus explicit `--no-color` output for deterministic plain text;
- buffered child logs with failure detail and optional verbose success logs;
- fail-fast sequential gates plus bounded parallel execution for independent tasks;
- truthful heartbeat output for long silent work;
- task-process isolation so a child task cannot mutate the Operator process, a later task, or the invoking CMD prompt through `set`, `cd`, or process-local environment changes;
- exact Git HEAD, diff-check, and real clean-tree validation gates;
- asynchronous GitHub Actions dispatch only after the named remote branch is verified to point at the exact local HEAD;
- machine-readable JSON output for future agents/automation.

## Non-goals

Phase 1 does not introduce a daemon, RPC service, webhook server, plugin framework, general task DSL, or cross-repository coordinator. Those require concrete recurring demand.

## Ownership

Devkit owns the Operator runtime and shared mechanisms. Individual repositories provide policy through `.qiven/operator.json`; generated repositories do not call back into a Devkit checkout.

The runtime is intentionally Python-standard-library-only in Phase 1 so a repository does not acquire a package-manager bootstrap dependency merely to validate itself.

Phase 1 requires Python 3.9 or newer. `tools\\qiven.cmd` honors an explicit `QIVEN_PYTHON` first and validates its version. Without an override it probes `python` first, then uses `py -3` only as a compatibility fallback; each implicit candidate must successfully execute the same Python 3.9+ version probe before it is selected.

## Command surface

`tools\\qiven.cmd` is the Windows entry point. It uses `setlocal`, invokes `tools/qiven.py`, and preserves the Python exit code. `tools/qiven.py` delegates to the managed `tools/qiven_operator.py` runtime.

Initial commands:

- `qiven info` — show repository/operator metadata;
- `qiven gate [--expect-head SHA]` — execute the repository's declared local validation gate;
- `qiven ci start <profile>` — verify exact remote branch identity, dispatch a declared GitHub Actions profile, and return immediately;
- `qiven run <task>...` — execute one or more declared tasks, sequentially by default and in parallel when explicitly requested.

`--json` switches terminal rendering to a stable machine-readable result envelope. `--no-color` keeps the human layout while disabling ANSI color.

## Process and CMD-context isolation

Every declared task runs as a separate child process with an explicit repository-root working directory and a fresh copy of the Operator process environment. A task may mutate its own environment or current directory, but those changes cannot flow back into the Python Operator, another task, or the interactive CMD prompt that launched `tools\\qiven.cmd`.

Windows `.cmd` and `.bat` tasks receive an additional child `cmd.exe /d /s /c` boundary and are invoked through `call` inside that child. This preserves batch exit semantics without allowing task-local `set` or `cd` changes to contaminate later Operator stages.

The Operator intentionally inherits the environment that existed when it was launched; Phase 1 does not attempt to reconstruct a pristine machine environment from the registry or globally scrub arbitrary third-party variables. Human-issued command blocks that themselves mutate shell state should therefore be scoped so their mutations do not leak into later interactive work.

## Human output semantics

Human-visible execution is state based rather than reassurance based. A task prints `[ RUN]` when it starts, `[WAIT]` only while it is observably still running through a silent interval, and exactly one terminal success/failure state for the task. Long-task heartbeat messages report elapsed time only; they do not invent percentages or ETAs. Successful child output remains buffered unless verbose output is requested, while failing output is surfaced with the failure.

`run` and `gate` commands also emit a final PASS/FAIL summary so the operator does not need to infer overall completion from the final child task.

## Async CI semantics

CI dispatch is asynchronous. Before dispatch, `ci start` resolves the current named local branch and local HEAD, resolves `refs/heads/<branch>` from `origin`, and refuses to dispatch if the remote branch is missing or points at a different SHA. This prevents a locally validated but unpushed commit from being mislabeled as the remote CI identity.

After the exact branch/SHA precondition passes, `ci start` dispatches through `gh workflow run`, prints the correlation inputs it knows, and exits. It does not sleep, discover a "latest" run, or poll GitHub merely to make an asynchronous operation look synchronous.

Future event-driven coordination may map a request identity to an exact run through workflow inputs, run-name metadata, webhooks, `workflow_run`, or a dedicated coordinator. That is intentionally outside Phase 1.
