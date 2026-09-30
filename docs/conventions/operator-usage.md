# Qiven Operator Usage (canonical reference)

The Qiven Operator is the repository-local engineering CLI every managed
repository carries. This document is its single usage reference; sessions
and repositories point here instead of restating it. The pointer chain:
each repository's `AGENTS.md` → `docs/conventions/README.md` (index)
→ here, and `collaboration/operating-contract.md` rule 5 names this file
for the hang-contract execution path.

## Output discipline and failure guidance

Human output is state-based (`[ RUN]` / `[WAIT]` / `[ OK ]` / `[FAIL]`
markers, flushed); progress reports observable state only. On FAILURE
surfaces (a failing gate/run task, an exact-head mismatch, exec
expired/error/indeterminate) the FIRST lines the consumer sees are a
`[qiven]` GUIDANCE banner — the known wrong-response pattern for the
class (do-not-weaken/do-not-bypass), the lawful first action, and the
exact procedure pointer — followed by the failure detail UNMODIFIED
(evidence law: failure text is never rewritten). The banner fires once
per surface kind per invocation; `--json` mode omits it (machine
consumers key on the payload). Hook-router DENIALS are a different
surface: instruction-first by design (the denial IS the guidance), with
a panic-guard line on the detour-prone templates (interactive,
unbounded sweep). Law origin: owner direction 2026-10-01 (GLM
first-consumer output; the aggressive-bugfix bias on seeing FAIL).
Regression pins: operator-test G1b; router-tests guidance-guard block.

## Entry and discovery

Two entries: `tools\qiven.cmd` (Windows) and `tools/qiven.py` (everywhere,
including POSIX shells). ALWAYS start a session's
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
SHA` pins validation to an exact commit (FULL 40-char sha — string
compare, not name resolution). A PASS writes a merge-proof receipt for
that exact head to `.generated-temp/operator/receipts/<gate>-<head>.json`
(required before any merge-class publication, pit P-53).

## run — declared tasks

`qiven run TASK...` (`--parallel` to run them concurrently). Unknown names
return the available alternatives.

## ci — explicit dispatch + observation-only watch

`qiven ci start PROFILE` verifies the remote branch matches local HEAD,
dispatches the declared workflow via `gh`, and returns immediately. Qiven
workflows are `workflow_dispatch`-only — a push never triggers CI
(`collaboration/session-ci-handoff-contract.md`).

`qiven ci watch PROFILE [--timeout MINUTES] [--receipt]` (2026-09-26,
OBL-F1A2B3 owner design) observes an ALREADY-DISPATCHED run to its
terminal state. It never dispatches anything. The watched run is
identity-bound: it must match local HEAD == origin/branch (same guard as
start), resolved through `gh run list` by exact head SHA — never
"latest". Same-head re-dispatch: a live (non-terminal) run is preferred
immediately; a terminal run is accepted only after it stays the newest
match across three consecutive polls (~30 s stabilization), so a stale
run's verdict is never reported in the canonical start→watch flow. gh
JSON is parsed from stdout only; three consecutive gh failures abort
with a typed error. Designed to run under the harness's
`run_in_background` re-call: the process polls gh internally every 10 s
(zero token cost while running; the harness notifies once on
completion), output stays clean (markers + errors only, no per-poll
chatter), and it is inherently terminating (internal timeout, default
60 min, validated finite/positive; discovery window shares the budget).
Exit codes: 0 run concluded success; 1 failure/cancelled/poll-timeout;
2 environment/usage error (including no run found for the head within
the budget). `--receipt` prints one JSON receipt line (run id, url,
conclusion, head, durations); `--json` mode prints only the receipt.

Routing: `qiven ci ...` — including `watch` — is gate-class at the
hook router: raw foreground calls are denied with the standard
background re-call + `MSBUILDDISABLENODEREUSE` guard (class-mandated
but inert for watch, which never builds); the guarded background
re-call passes — backgrounding IS the designed shape. It does NOT
route through `qiven exec` (ADR-0051: exec is local custody classes; a
watch observes a REMOTE run — losing a watcher at session end is
harmless, the run lives on GitHub).

## exec — supervised detached execution under bounded custody (the custody path)

ADR-0051 (2026-09-24) scopes exec to CUSTODY classes: filesystem tree
sweeps (lease-bounded ghost-process class), runs that must survive the
session (durable receipts, cross-session work), owner-run kits/H1
packages, work past the harness Bash timeout ceiling (~10 min), and
unknown-duration work pending measurement. Ordinary in-session long
work (builds, tests, gates whose consumer is this session) does NOT
detour through exec: the hook router denies the raw call and instructs
a `run_in_background: true` re-call — one call, one completion
notification, zero polling (the deny → exec → status-poll loop is the
retired anti-pattern; so is foreground sleep+tail).

```text
qiven exec start [--timeout S] [--max-lifetime M] -- CMD ARGS...
                                                 supervise; default 120s / 3600s
qiven exec status ID [--tail N]                 re-attach: state + custody + log tail
qiven exec stop ID                              terminate the process tree
qiven exec list                                 inventory known runs with lease
qiven exec sweep                                terminate expired runs, finalize stale
```

Semantics that matter to a caller:

- **Bounded process custody (v2, ADR-0048; invariants live in ONE
  place: `docs/design/exec-custody.md` §2/§4 — watchdog custodian +
  `KILL_ON_JOB_CLOSE` Job-Object tree lifetime, lease clamped
  [10, 86400], completion reap, `CREATE_NO_WINDOW` children — never
  `DETACHED_PROCESS` — and the batch `cmd.exe /d /c call` boundary;
  governing precedent: the 2026-09-23 orphaned-process incident).**
  Regression case map: C1-C3, C5-C10 literal ids in the operator-tests
  suite; C4/C11-C16 fold into the G2 semantics checks (exec-custody
  §5).
- The child runs detached with stdout/stderr to a durable log under
  `.generated-temp/operator/exec/<id>.log`; the run record (`<id>.json`)
  carries the custody identity: `pid`, `watchdog_pid`, `job_name`,
  `deadline_utc`, live `heartbeat_utc`, `max_lifetime_seconds`.
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
  code is genuinely unknown, and `indeterminate` ALSO returns 124 (it
  shares the still-running code): on a 124, key on the payload's
  `status` field (`still-running` vs `indeterminate`), never the exit
  code alone.
- **Sweep insurance**: every operator invocation piggybacks a sweep that
  terminates runs past their lease and finalizes stale records; `qiven
  exec sweep` runs it explicitly. Dead runs can be listed for postmortem
  via `exec list`.
- Typical exec loop (custody classes only): `exec start --timeout 60 --
  <command>` → if 124, `exec status ID` between other work (never a
  tight poll); the run continues under its lease — re-check when there
  is something else to do anyway, and read the log at done/expired/
  indeterminate. Runs you abandon are still bounded: the lease kills
  them without any caller.

## What NOT to do

- Do not pipe a machine-JSON stream through text filters; parse it or read
  the spilled `log_file`.
- Do not treat `git status --short` exit code as a cleanliness gate (the
  clean-tree builtin exists for that).
- Do not widen a gate, comment a test, or lower a warning to make a run
  pass (testing standard §11).
- Do not POLL supervision loops for ordinary long work: no
  `exec status` round-trips, no foreground `sleep && tail` — the
  backgrounded re-call notifies once on completion (ADR-0051).
- Do not re-call a build/gate-class command with `run_in_background`
  WITHOUT `MSBUILDDISABLENODEREUSE=1` (or `/nr:false`): worker nodes
  deliberately survive their primary and would strand past the
  completion notification (ADR-0048 §3 / ADR-0051 §3).
- Do not run UNBOUNDED sweep-class commands backgrounded: only the
  registry's v4.3 custody subclass (heavy/no-path/escaping sweeps)
  needs exec's lease custody — `git grep`/`git ls-files` run raw and
  repo-scoped bounded sweeps deny→background by design
  (long-command-registry v4.3, 2026-09-26; ADR-0051 decision 5's
  dated scope note).

## The hook router (backstop) — 2026-09-23 review, v4 semantics 2026-09-24 (v4.3 subclasses since 2026-09-26)

The PreToolUse Bash hook (`tools/hook_exec_router.py`, registered in the
workspace `.zcode/config.json`) denies RAW long-class and interactive
commands and instructs the ADR-0051 re-call. It is a backstop, never the
contract; it fails open on unparseable input and cannot catch indirection
(`BASE=<tool>; $BASE ...`). Its classification table is pinned by
`tools/hook_exec_router_test.py` (gate task `router-tests`).

Operative routing (the member lists, thresholds and per-class evidence
live in ONE place — `qiven-context collaboration/long-command-registry.md`,
owner-governed; the router implements it and the test table pins it —
do not restate members here):

- **build / gate-class / repo-tool / network classes, and repo-scoped
  bounded sweeps**: denied raw with the exact re-call instruction
  ("re-issue THIS EXACT command with run_in_background: true"). Build
  and gate classes additionally require the `MSBUILDDISABLENODEREUSE=1`
  env prefix (or `/nr:false`) on the re-call — the router denies again
  until the guard is present (ADR-0048 §3 / ADR-0051 §3).
- **Unbounded/heavy/escaping filesystem sweeps**: exec lease custody
  ONLY (the ghost-process class; a background task's session-end
  lifetime is uncharacterized) — see "What NOT to do" above.
- **Interactive class**: denied, NO exec form (interactivity is the
  denial itself, not a duration class).
- **git push/fetch/pull**: measured-transfer class, SUSPENDED since
  2026-09-24 (owner direction) — raw git-network commands currently
  pass this hook unprobed; the probe machinery is unchanged underneath
  and reinstatement is owner-only.
- **`qiven exec/info/status` stay raw**; `git grep`/`git ls-files` stay
  raw (tracked files only, v4.3).
- Classification is PER SEGMENT (an exec wrapper in one segment never
  launders a raw long command in another; post-`&&`/`;`/`|` segments
  are lstripped before classification, OBL-A7B8C9); quoted spans are
  ignored (prose false-positives were blocking real authoring — a
  payload hidden inside quotes is NOT classified).
- Every denial is prefixed `[qiven-hook]` with its evidence (owner
  direction: an unattributed denial splits the receiving agent's
  reasoning). Oversized foreground output is bounded natively by the
  harness (>~25-30KB auto-persists with a ~2KB preview + path).

Router/revision history: the canonical record is the registry +
ADR-0051 and git history; per-task duration evidence accrues to
`.generated-temp/operator/task-durations.jsonl`.
