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

## exec — supervised detached execution under bounded custody (the hang-contract path)

For any command whose duration class is long or unknown (builds, test
suites, compiler/linker invocations, long tools, filesystem tree sweeps),
LLM sessions MUST route it through exec instead of a raw shell call:
`collaboration/operating-contract.md`, hang-classification rule 5.

```text
qiven exec start [--timeout S] [--max-lifetime M] -- CMD ARGS...
                                                 supervise; default 120s / 3600s
qiven exec status ID [--tail N]                 re-attach: state + custody + log tail
qiven exec stop ID                              terminate the process tree
qiven exec list                                 inventory known runs with lease
qiven exec sweep                                terminate expired runs, finalize stale
```

Semantics that matter to a caller:

- **Bounded process custody (v2, 2026-09-23 incident redesign;
  `docs/design/exec-custody.md`).** Every exec run has a WATCHDOG
  custodian holding a Windows Job Object (`KILL_ON_JOB_CLOSE`) that
  contains the ENTIRE run tree. The kernel, not agent discipline,
  enforces: the tree dies no later than its lease (`--max-lifetime`,
  default 3600 s, clamped to [10, 86400]); if the watchdog dies for any
  reason the tree dies with it instantly; and when the primary command
  exits, surviving tree members (the MSBuild node-reuse leak class) are
  terminated after a 1.5 s output grace. A session can no longer leave
  invisible build processes burning CPU behind it — the 2026-09-23
  incident (dozens of msbuild/cmd orphans + a ghost find.exe surviving
  the session and the IDE exit) is the governing precedent. Children also
  run with `MSBUILDDISABLENODEREUSE=1`.
- The child runs detached with stdout/stderr to a durable log under
  `.generated-temp/operator/exec/<id>.log`; the run record (`<id>.json`)
  carries the custody identity: `pid`, `watchdog_pid`, `job_name`,
  `deadline_utc`, live `heartbeat_utc`, `max_lifetime_seconds`.
- **Window discipline (2026-09-23 fix, unchanged)**: children are spawned
  with `CREATE_NO_WINDOW` — a HIDDEN console — never `DETACHED_PROCESS`
  (popup windows / empty logs / `0xC0000142`). `.cmd`/`.bat` targets run
  through an explicit `cmd.exe /d /c call <abs path>`, and a path-like
  argv[0] is resolved against the repository ROOT before spawning. The
  operator-tests gate task carries the regression suite (capture, batch
  chains, grandchild consoles, custody laws C1-C10).
- While supervising, exec heartbeats every ~5s (`running for Ns, log X
  bytes`). Heartbeat is the liveness discriminator — with beats, extending
  the budget deliberately is correct; silence means investigate the log,
  not wait longer.
- `--timeout` bounds the OPERATOR's own wait, never the command: at the
  ceiling exec returns exit code 124 with status `still-running` and the
  run continues UNDER ITS LEASE under watchdog custody. Caller death
  (shell killed, tool timeout) does not kill the run before its lease.
- Exit codes: the child's code when observed; 124 still-running at the
  operator ceiling; 2 operator error; 1 when the run's lease expired
  (`expired` — the business exit code is unknown and never guessed). An
  exit no living supervisor observed is reported `indeterminate` — the
  code is genuinely unknown.
- **Sweep insurance**: every operator invocation piggybacks a sweep that
  terminates runs past their lease and finalizes stale records; `qiven
  exec sweep` runs it explicitly. Dead runs can be listed for postmortem
  via `exec list`.
- Typical loop: `exec start --timeout 60 -- <build command>` → if 124,
  `exec status ID` (bounded observations per the session contracts — at
  most three per 60s); the run continues under its lease — keep checking
  status until done/expired/indeterminate, then read the log. Runs you
  abandon are still bounded: the lease kills them without any caller.

## What NOT to do

- Do not pipe a machine-JSON stream through text filters; parse it or read
  the spilled `log_file`.
- Do not treat `git status --short` exit code as a cleanliness gate (the
  clean-tree builtin exists for that).
- Do not widen a gate, comment a test, or lower a warning to make a run
  pass (testing standard §11).
- Do not run long-class commands through a raw shell when exec exists in
  the repository.

## The hook router (backstop) — 2026-09-23 review

The PreToolUse Bash hook (`tools/hook_exec_router.py`, registered in the
workspace `.zcode/config.json`) denies RAW long-class and interactive
commands and prints the exec pattern. It is a backstop, never the
contract; it fails open on unparseable input and cannot catch
indirection (`BASE=<tool>; $BASE ...`). Its classification table is
pinned by `tools/hook_exec_router_test.py` (gate task `router-tests`).

Long classes (each entry earned by an observed incident or by class
logic — additions need a case in the test table):

- builds/toolchains: cmake `-S/-B/--preset/--build/--install`, ctest,
  msbuild, devenv, `cl.exe`, `link.exe`, `dotnet build/test`;
- repo gate/tool entrypoints that sweep or build: `format_sources.py`,
  the format entrypoints, the pinned formatter binary, `test_all.py`,
  pytest, `deploy_bundle.py`/`deploy.cmd` (the 2026-09-23 vendored
  amalgamation format hang is the governing incident);
- network acquisition: the transfer tools (curl-class and the
  PowerShell equivalents), `pip install/download`, `npm install/ci/run
  build`, `git clone`, `git submodule update/sync`, `gh run watch` (the
  raw transfer-tool slip during the SQLite acquisition is the incident);
- filesystem tree sweeps (2026-09-23 ghost find.exe incident): `find`
  with a path-argument form (`find /d/...`, `find D:\...`, flags then
  path), `grep -r/--recursive`, `dir /s` — the Windows text-FILTER form
  (`find /i "text" file`) stays raw;
- interactive class (separate verdict; suspends the shell awaiting a
  human — the 2026-09-19 modal incident class): editors, git
  interactive/patch modes, `cmake --open`.

`git fetch`/`git pull`/`git push` are NOT blanket classes — see the v3
section below (measured per invocation).

## v3 (2026-09-23, owner review): measured git, gate routing, provenance

- **Registry of record**: the canonical class list lives in
  `qiven-context collaboration/long-command-registry.md` (owner-governed
  thresholds and evidence); this router implements it.
- **git push/fetch/pull are MEASURED**: the hook probes first (push:
  upstream ahead-count over 25 → deny; then a `push --dry-run` within a
  5 s budget. fetch/pull: a `fetch --dry-run`; fast AND changeless →
  allow). `git clone` stays unconditional (nothing local to probe).
  Every denial carries the measurement.
- **`qiven gate/run/ci` invoked raw are denied** with exec guidance
  (minutes-class; they block the session shell); `qiven exec/info/
  status` stay raw. Classification is PER SEGMENT: an exec wrapper in
  one segment never launders a raw long command in another. Segments
  following `&&`/`;`/`|` arrive with leading whitespace and are
  lstripped before classification — chained exec invocations classify
  correctly (OBL-20260923T224500Z-A7B8C9, closed 2026-09-23).
- **Every denial is prefixed `[qiven-hook]`** with its evidence, so the
  receiving agent can attribute the verdict (no ambiguous denials —
  owner direction: an unattributed denial splits the agent's
  reasoning).
- **Quote-awareness**: segment splitting and class matching ignore
  quoted spans (commit messages, PR prose). Deliberate trade-off: a
  payload hidden inside quotes (`bash -c "..."`) is not classified —
  the operator exec path is the sanctioned wrapper for deliberate
  long work, and prose false-positives were blocking real authoring.
- **Operator timers**: every task result appends to
  `.generated-temp/operator/task-durations.jsonl` and gate receipts
  carry per-task `duration_seconds` — the evidence base for refining
  the class split (e.g. re-allowing short `qiven run` tasks) by an
  owner-recorded registry change, not guesswork.
