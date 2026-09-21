# Qiven Operator Usage (canonical reference)

The Qiven Operator is the repository-local engineering CLI every managed
repository carries. This document is its single usage reference; sessions
and repositories point here instead of restating it. The pointer chain:
each repository's `AGENTS.md` → `docs/conventions/README.md` (this index)
→ here, and `collaboration/operating-contract.md` rule 5 names this file
for the hang-contract execution path.

## Entry and discovery

One entry per platform: `tools\qiven.cmd` (Windows), `tools/qiven.py`
(everywhere), `tools/qiven.sh` (POSIX shells). ALWAYS start a session's
first use with `--help`, then the subcommand's own `--help` — the
installed snapshot is the truth, this document is the map.

```text
qiven [--json] [--verbose] [--no-color] {info,gate,run,ci,exec} ...
```

Global flags are accepted before or after the subcommand. `--json` is the
machine view (stable JSON on stdout; large buffered logs spill to a
durable file whose path is carried in `log_file`). `--verbose` shows
successful task logs. Human sessions and supervised agents should prefer
the human view (`[ RUN]` / `[WAIT]` / `[ OK ]` / `[FAIL]` markers,
heartbeats).

## info

`qiven info` — repository name, default gate, exact HEAD. Cheap identity
probe for a fresh session.

## gate — the configured local validation

`qiven gate [NAME]`, default gate from `.qiven/operator.json`. A gate is a
fail-fast task sequence (strings serial, lists parallel); it stops at the
first failing stage and preserves the failing exit code. `--expect-head
SHA` pins validation to an exact commit. A PASS writes a merge-proof
receipt for that exact head (required before any merge-class publication,
pit P-53).

## run — declared tasks

`qiven run TASK...` (`--parallel` to run them concurrently). Unknown names
return the available alternatives.

## ci — explicit CI dispatch only

`qiven ci start PROFILE` verifies the remote branch matches local HEAD,
dispatches the declared workflow via `gh`, and returns immediately. Qiven
workflows are `workflow_dispatch`-only — a push never triggers CI
(`collaboration/session-ci-handoff-contract.md`).

## exec — supervised detached execution (the hang-contract path)

For any command whose duration class is long or unknown (builds, test
suites, compiler/linker invocations, long tools), LLM sessions MUST route
it through exec instead of a raw shell call:
`collaboration/operating-contract.md`, hang-classification rule 5.

```text
qiven exec start [--timeout S] -- CMD ARGS...   supervise; default 120s
qiven exec status ID [--tail N]                 re-attach: state + log tail
qiven exec stop ID                              terminate the process tree
qiven exec list                                 inventory known runs
```

Semantics that matter to a caller:

- The child runs DETACHED in its own process group with stdout/stderr to
  a durable log under `.generated-temp/operator/exec/<id>.log`; a run
  record (id, pid, argv, times) sits beside it as `<id>.json`.
- While supervising, exec heartbeats every ~5s (`running for Ns, log X
  bytes`). Heartbeat is the liveness discriminator — with beats, extending
  the budget deliberately is correct; silence means investigate the log,
  not wait longer.
- `--timeout` bounds the OPERATOR's own wait, never the command: at the
  ceiling exec returns exit code 124 with status `still-running` and the
  child CONTINUES. Caller death (shell killed, tool timeout) does not kill
  the child. Breakaway from a restrictive ancestor job is best-effort with
  fallback; survival is never overstated.
- Exit codes: the child's code when observed; 124 still-running at the
  operator ceiling; 2 operator error. An exit no living supervisor
  observed is reported `indeterminate` — the code is genuinely unknown and
  is never guessed.
- Typical loop: `exec start --timeout 60 -- <build command>` → if 124,
  either `exec status ID` (bounded observations per the session contracts
  — at most three per 60s) or re-invoke start is NOT needed; the run
  continues — keep checking status until done/indeterminate, then read the
  log.

## What NOT to do

- Do not pipe a machine-JSON stream through text filters; parse it or read
  the spilled `log_file`.
- Do not treat `git status --short` exit code as a cleanliness gate (the
  clean-tree builtin exists for that).
- Do not widen a gate, comment a test, or lower a warning to make a run
  pass (testing standard §11).
- Do not run long-class commands through a raw shell when exec exists in
  the repository.
