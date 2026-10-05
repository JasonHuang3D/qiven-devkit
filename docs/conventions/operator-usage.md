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
qiven [--json] [--verbose] [--no-color] {info,surface,records,gate,run,evidence-read,ci,exec} ...
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

## surface — O(1) gates/tasks/ci introspection (B6)

`qiven surface` — ONE call lists every declared gate (with its task
sequence; the default gate is marked), every declared task (builtin or
argv), and every declared CI profile (the `ci` section: name + the
workflow file `qiven ci start <profile>` dispatches — the profile names
are the entry points, so guessing them or opening the config is the
DG-2 defect this closes) straight from `.qiven/operator.json`. Use it
BEFORE opening any config file or guessing task names — `qiven run` on
an unknown name returns alternatives, but `surface` answers the
question without a failing round trip. `--json` carries
`gates`/`tasks`/`ci_profiles`/`default_gate` machine-parsed (a repo
with no `ci` section lists `0 ci profile(s)` / an empty array).

## records — Common Record read-back (B6)

`qiven records` — the read-back surface for the operator's Common Records
(`.generated-temp/operator/records/`, `common-record-v1`; written by
every gate/run/ci/exec invocation). Canonical law carrier: qiven-context
`collaboration/generated-temp-convention.md` (ADR-0040/0042). Until B6
these were write-only: no stdout carrier named them.

```text
qiven records                list newest-first (name, kind, verdict, next)
qiven records NAME           one record's bounded model view
                             (the record_projection; QIVEN-RECORD v1)
```

The bounded view is the SAME projection that rides the gate/run FAIL
carriers (ADR-0060 D3 budgets 8192/2048/8/16384 — the view is bounded,
sorted, EOF-marked). Raw JSON bytes stay reachable through
`qiven evidence-read .generated-temp/operator/records/<name>`. An empty
records directory states itself (`records: none yet`); an unknown name is
a typed exit-2 error that points back at the listing.

## gate — the configured local validation

`qiven gate [NAME]`, default gate from `.qiven/operator.json`. A gate is a
fail-fast task sequence (strings serial, lists parallel); it stops at the
first failing stage and preserves the failing exit code. `--expect-head
SHA` pins validation to an exact commit (FULL 40-char sha — string
compare, not name resolution). A PASS writes a merge-proof receipt for
that exact head to `.generated-temp/operator/receipts/<gate>-<head>.json`
(required before any merge-class publication, pit P-53).

The final human summary line is ONE line carrying class + action +
reference (the selector law, ADR-0060 D3: `grep -E "FAIL|OK"`, `head`/`tail`
fragments of the summary keep all three):

```text
[FAIL] gate:local: FAIL - NEXT action: DIAGNOSE - <bounded correction> - evidence: <locator>
[ OK ] gate:local: PASS - receipt: .generated-temp/operator/receipts/<gate>-<head>.json
```

Machine `--json` mode carries no such line (JSON purity).

## run — declared tasks

`qiven run TASK...` (`--parallel` to run them concurrently). Unknown names
return the available alternatives.

## evidence-read — bounded read of retained evidence (ADR-0060 D6)

```text
qiven evidence-read PATH [--offset N] [--count N]     BYTE range; default 0..16384
```

A consumer utility for retained evidence/log artifacts (gate task
evidence, exec run logs, spilled machine payloads, common records). It is
registered in NO gate — it reads what producers already retained.

- **Addressing is BYTES** (`--offset`/`--count` are byte offsets, the only
  addressing an arbitrary captured artifact supports); output is byte-
  capped at 16384 (`BOUNDED_READ_MAX_BYTES`) per call, larger `--count`
  values are clamped, never enlarged — and a negative `--offset` or a
  `--count` below 1 is a typed usage error (exit 2), never a silently
  altered range. Each result carries an explicit EOF
  marker or a `continue:` cursor naming the exact next call, so a large
  artifact is walked incrementally and never loaded whole (D6).
- **Path boundary**: a RELATIVE path addresses the repository's
  `.generated-temp/` evidence roots (the leading `.generated-temp/` is
  optional); an ABSOLUTE path is accepted when it resolves under the
  repository root OR under the operator's retained-evidence area outside
  it (`<OS temp>/qiven-operator/`, where failed/oversized task evidence
  is retained — retained task evidence stays recoverable through this
  route) — anything else, `..` traversal included, is a typed error
  (exit 2), never a silent redirect.
- Missing (never-retained pointers), unreadable and directory paths are
  typed errors naming the resolved path. An EXPIRED artifact (gone, with
  a `<artifact>.expired` sibling marker left by the retention contract)
  answers with the typed `evidence expired` error naming the ORIGINAL
  locator plus the marker's bounded note — an expired pointer stays
  visible, it never justifies dropping the diagnostic; when artifact and
  marker both exist the bytes win (D6).
- `--json` returns the same facts machine-parsed (`bytes_returned`,
  `total_bytes`, `eof`, `next_offset`, `content`). Decoding is a view
  (UTF-8 with replacement): invalid captured bytes stay recoverable in
  the artifact itself.

## ci — explicit dispatch + observation-only watch

`qiven ci start PROFILE [--candidate SHA] [--workspace-ref REF]` verifies
the remote branch matches local HEAD, dispatches the declared workflow via
`gh`, and returns immediately. Qiven workflows are `workflow_dispatch`-only
— a push never triggers CI (`collaboration/session-ci-handoff-contract.md`).
Candidate law (2026-10-03 workflow redesign): the redesigned workflows
REQUIRE input `candidate` = the full 40-hex SHA of the repo commit under
test (typed failure by design without it). The tool selects it EXPLICITLY
(exact-head law, never a workflow-side fallback): `--candidate` overrides;
absent it defaults to the invoking repository's current HEAD, resolved and
recorded (ci-dispatch record `selected_revision` + materialized
invocation). A malformed candidate (not exactly 40 hex chars) or an
unresolvable HEAD is a typed local refusal (four-element carrier, exit 2)
— nothing is dispatched. Law home: qiven-context ADR-0060 (P0 producer
program); the owner-verbatim four-element statement is recorded in
qiven-context OBL-20261001T234500Z-B9C0D1 and
runtime/p0-producer-inventory.yaml. `--workspace-ref` passes through to
the optional workflow input when given and is omitted entirely when
absent.

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

## Workspace mechanisms — the lock, the resolver, the bootstrap (B6)

Motivating friction (named, v58): during the v58 workspace-advance the
lock-update entry point was discoverable only through the qiven-workspace
README, which no devkit/context doc chain advertised — the owner hit real
multi-call discovery friction for a Qiven-owned mechanism (the
register's DG-1 LIVE class). This section is the fix: every
workspace-mechanism entry point, exact invocation shapes, in the canonical
operator doc. The workspace-side view (locator vocabulary, trust policy,
WR history) stays canonical in the qiven-workspace `README.md`.

All examples assume `<devkit>` = the locked qiven-devkit checkout and
`<control>` = the qiven-workspace control checkout. The resolver is
`<devkit>/tools/workspace_resolver.py`; the bootstrap is
`<control>/bootstrap/qiven-bootstrap.py` (stdlib-only, runs without the
devkit). Every subcommand prints a receipt to
`<workspace-root>/.generated-temp/workspace-resolver/<stamp>-<op>/receipt.json`
(override with `--out`); machine mode is `--json`.

Resolver subcommands (common flags on all: `--control` required,
`--mode shadow|authoritative`, `--trust-policy` for authoritative):

```text
validate                                resolve + validate the whole graph
preflight  --devkit <devkit>            lock-subset validation + devkit identity-check
candidate  --manifest <file>            validate a candidate dependencies-v1 file
overlay    --overlay NODE=<checkout>    resolve with candidate nodes overlaid (repeatable)
adapter    --repo <id> --repo-checkout <path>
                                        emit the resolution adapter for one repo
lock-update --move NODE=<checkout> [--apply]
                                        move lock node(s) to a checkout's exact clean HEAD
golden-vectors                          run the frozen canonicalization vectors
```

Lock movement — the exact invocation shape (the v58 friction site):

```text
python <devkit>/tools/workspace_resolver.py lock-update \
    --control <control> --move NODE=<checkout> [--move NODE2=<checkout2>]
```

Validation-only by default (receipt only, no tree writes; shadow mode).
Authoritative movement adds `--mode authoritative --trust-policy
<qiven-context>/governance/workspace-control-trust-policy.json` and
`--apply`, which writes the new lock + declaration cache INTO the control
tree as one uncommitted transaction — the session then commits the
control repository (the receipt's `next_action` says exactly this).
Publication precedes lock advancement: the moved revisions must be
accepted (pushed/published) BEFORE the control repository is committed —
a committed lock never points at revisions other workspace consumers
cannot fetch.
`lock-update` is the lock's ONLY writer; `--move` targets must be clean
(at their exact HEAD) and identity-checked. Routine advance (WR-8): a
control commit whose diff from the closest admitted ancestor is limited
to node advancement auto-admits.

Bootstrap (the gate-configure path every configure rides, WR-5):

```text
python <control>/bootstrap/qiven-bootstrap.py preflight --control <control> --devkit <devkit>
python <control>/bootstrap/qiven-bootstrap.py gate-configure \
    --control <control> --devkit <devkit> --repo <name> --repo-root <path> \
    --preset <preset> [--mode authoritative --trust-policy <path>]
```

Preflight is the cheap workspace health probe (run it before blaming a
build); gate-configure is what `cmake --preset` must go through (a bare
configure fails typed on every repo under the WR-5 binding). Every typed
failure — preflight AND the gate-configure return-1 sites — emits the
`qiven-workspace-bootstrap-error-v1` envelope with a Common Record
(`rule_id` + `next_action`). The deploy path calls gate-configure itself
(`deploy_bundle.py`); you never configure by hand for a deploy.

Identity-skew qualification note (SG-5, register DG-5 — what a consumer
must know about invoking-repo checkout vs lock node drift): `qiven info`
reports `workspace_generation`, `devkit_node` (the lock's qiven-devkit
node), `devkit_head` (the checkout actually executing) and `devkit_drift`
— for the DEVKIT only. NO consumer validates the INVOKING repository's
own checkout against its lock node (the observed skew class: qiven-context
executing checkout 98639a8 ahead of its locked node 1329bcf). Until SG-5
closes, a consumer that needs that guarantee compares `git rev-parse HEAD`
in the invoking repo against its entry in `<control>/workspace.lock.json`
manually. Known residual in the same family: qiven-foundation's
`tools/toolchain.py` was converged to the devkit canonical byte-identically
at B6 (DG-5 closed, sha256 c22cdc03...); qiven-runtime's copy lagged one
revision until the v61 integral review adopted the same convergence
(the devkit revision guards git-unavailability with a typed `[FAIL]`
carrier). After v61 no carrying repo lags the canonical.

## Devkit tool surfaces (B6 discovery)

Two devkit tools are model-facing CLIs of their own (not operator
subcommands); both are O(1)-discoverable through their own `--help`:

```text
python <devkit>/tools/workspace_schemas.py --list
python <devkit>/tools/workspace_schemas.py --check <file> --schema docs/schemas/<name>.schema.json
python <devkit>/tools/deploy_bundle.py --repo <repo> [--profile <p>]
python <devkit>/tools/deploy_bundle.py --verify <bundle-dir>
```

Schema-check (`--check`/`--schema`, exit 0/1/2) validates workspace.json,
workspace.lock.json and `.qiven/dependencies.json` against the schema
documents in `docs/schemas/` (`--list` enumerates them). Strictness is
the contract: duplicate keys, floats and unknown fields are typed
rejections, never warnings (WR-1, ADR-0052). Deploy (`--repo`) enforces
the HOW of `.qiven/deploy.json` (schema `qiven-deploy-policy-v1`; the
policy shape rides the tool's `--help` epilog and
`docs/engineering/deployment.md`): clean exact head + gate receipt,
release build, digests, in-bundle smoke, atomic publish, append-only
deploy log. `--verify` checks a published bundle against its manifest.

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

Router denial carriers are the named legacy profile
`router-denial-legacy-v1` (P0 register rows; declared in
`tools/router_record_adapter.py` `ROUTER_PROFILE`). The owner-approved
public-carrier amendment makes the fixed control text ASCII; the current
denial bytes remain stable by ADR-0051 via ADR-0060 D7. Do not restyle
denial lines ad hoc.

Registration location (DG-4, B6): the hook is wired in the harness's
MACHINE-LOCAL, untracked config `D:\JasonWork\.zcode\config.json` (the
ZCode client's config at the workspace root — OUTSIDE every repository;
no tracked file can carry it verbatim, it names machine-local paths).
Live-verify: read that file, or run any build-class command raw (e.g. a
foreground `cmake --build ...`) and observe the `[qiven-hook]` denial —
the hook firing IS the registration proof. A fresh machine/workspace
needs the registration recreated there by hand.

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
