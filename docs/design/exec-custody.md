# Design: Bounded Process Custody for the Qiven Operator (exec v2)

Status: design for the 2026-09-23 emergency stabilization batch
(owner direction: full review of devkit tooling after the v19 post-session
process-leak incident; design-first law applies — this document precedes
the implementation commits in the same batch).

## 1. Basis and incident

Governing contracts:

- `collaboration/operating-contract.md` (qiven-context): hang-classification
  rules 1-5 — every invocation bounded, timeout = classification, heartbeat
  = liveness discriminator, no modal UI, operator-mediated execution for
  long/unknown-duration commands.
- `MEM-20260921T114000Z-A3F8B5`: exec = detached supervised execution so
  LLM-shell death cannot kill real commands.
- `MEM-20260923T212000Z-D4E5F6`: CREATE_NO_WINDOW window discipline.
- `docs/conventions/operator-usage.md`: the exec usage contract.

Incident (2026-09-23, v19 session aftermath): after ~90 minutes of
gate-driven work the machine retained dozens of `msbuild`/`cmd` processes
plus one Git-for-Windows `find.exe` at >20% CPU; total ~70% CPU after the
session ended; exiting ZCode did not reclaim them; an OS restart was
required.

Root causes established from the exec record store (139 runs in
qiven-runtime alone during the window) and code review:

1. **No custody object.** exec spawned children with creation flags only
   (`CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP |
   CREATE_BREAKAWAY_FROM_JOB`) and never created a Job Object. The tree
   had no kernel-enforced lifetime bound and no owner.
2. **Descendant survival past the primary.** `cmake --build` (VS
   generator) leaves MSBuild worker nodes alive after the build primary
   exits (node reuse `/nr:true` default). The operator observed the
   primary exit, recorded `done`, and the nodes leaked — invisible
   (hidden console), unbounded, accumulating per build invocation.
3. **Unbounded "child continues".** At the operator supervision timeout
   (exit 124) the child continues with no deadline; the only stop path is
   an explicit `exec stop` by an agent that may already be gone. Session
   death therefore leaks every still-running run, permanently.
4. **Breakaway made them unreclaimable.** Because the children broke away
   of any ancestor job, exiting the IDE (job-tree kill) could not reach
   them.
5. **Raw-shell tree sweeps were unclassified.** `find <root>` (Git Bash's
   find.exe scanning the workspace) is minutes-class but absent from the
   hook-router long-class table, so it ran raw in the session shell and
   survived session exit (observed: the ghost find.exe at 20% CPU).

The architectural flaw, named: the survival property ("the child outlives
the caller's shell") was implemented as an UNBOUNDED property whose
cleanup was BEHAVIORAL (the agent is expected to call `exec stop`).
Production custody must be MECHANICAL: the OS bounds every tree's
lifetime, and no agent memory is load-bearing for reclamation.

## 2. Invariants (the contract this design enforces)

- **I1 — bounded lifetime.** Every process tree the Operator spawns (exec
  runs AND gate/run task children) dies no later than its declared
  deadline, enforced by the OS kernel, never by agent behavior.
- **I2 — custody on custodian death.** If a run's custodian (watchdog)
  dies for any reason, its tree dies immediately with it (Job Object
  `KILL_ON_JOB_CLOSE`; the watchdog is a job member and holds the job
  handle). A tree may never outlive its custodian.
- **I3 — caller death survival, bounded.** Death of the invoking shell or
  session does not kill a run before its deadline (the original exec
  requirement) — unless the environment kills the watchdog itself, in
  which case I2 fires and the tree dies immediately. Either way the
  post-session CPU footprint is bounded: zero, or at most one deadline
  window.
- **I4 — tree completeness.** The whole tree — primary, wrappers, MSBuild
  nodes, grandchildren — is ONE custody unit. Nothing escapes: children
  are created inside the job (zero-race: suspended create → assign →
  resume for task children; job membership by birth for watchdog-spawned
  children), the job forbids breakaway, and no child is spawned with
  `CREATE_BREAKAWAY_FROM_JOB`.
- **I5 — completion reaps.** A run/task completes when its PRIMARY
  completes; surviving tree members are terminated after a short output
  grace (1.5 s). Deliberate background survivors are not a supported
  semantic (the no-daemon law); they are exactly the leak class being
  eliminated.
- **I6 — observable custody.** Every run record carries its custody
  identity: `job_name`, `watchdog_pid`, `deadline_utc`, live
  `heartbeat_utc`. `exec status` reports them; `exec list` shows
  deadlines; an automatic sweep on every operator invocation terminates
  and marks runs past their deadline.
- **I7 — fail-closed start.** If the job object or the watchdog cannot be
  created, the run does NOT start. Never spawn uncustodied children.
- **I8 — exit semantics preserved.** Child exit code when observed; 124
  still-running at the front-end supervision budget; `indeterminate` for
  exits no living supervisor observed; 2 operator error. New terminal
  state `expired` = killed by its own lease (deadline), business exit
  code never guessed.

## 3. Architecture

```text
qiven exec start --timeout S --max-lifetime M -- CMD
  |
  front-end (returns at S with 124 while run continues)
  |  1. build run record: id, argv, deadline = now + M, log, job name
  |  2. spawn WATCHDOG: python qiven_operator.py --exec-watchdog <record>
  |     flags: CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
  |            | CREATE_BREAKAWAY_FROM_JOB (best-effort, honest retry)
  |  3. monitor record+log with heartbeats until S
  |
  watchdog (the custodian; detached from the caller, bounded by deadline)
  |  1. create Job Object: named, KILL_ON_JOB_CLOSE, ACTIVE_PROCESS cap
  |  2. assign ITSELF to the job (members' children are born inside it;
  |     the watchdog dying therefore always kills the whole tree)
  |  3. spawn the child: CREATE_SUSPENDED | CREATE_NO_WINDOW
  |            | CREATE_NEW_PROCESS_GROUP  -> assign is implicit-by-birth
  |     stdout=stderr=log handle, stdin=NUL
  |  4. loop: wait(primary, 100ms); heartbeat-rewrite record every 5 s;
  |     at deadline: pre-write record(status=expired) -> TerminateJobObject
  |  5. on primary exit: read exit code; pre-write record(done, code);
  |     wait grace 1.5 s; TerminateJobObject(job, code)  (kills leftovers
  |     AND the watchdog; the watchdog exit code mirrors the child's)
```

Gate/run task children get the same custody inline (no watchdog — the
operator process supervises tasks directly): per-task Job Object with
`KILL_ON_JOB_CLOSE` held by the operator; child created suspended,
assigned, resumed; on primary exit the job is terminated after the output
grace. Operator death mid-task closes the handle and kills the tree. The
spawned-with-suspension assignment closes the classic Popen→Assign race
(no grandchild can be born before membership).

`exec stop` from any later process: open the job BY NAME
(`OpenJobObject`) and `TerminateJobObject`. If the open fails the job no
longer exists — all handles closed — so the tree is already dead
(KILL_ON_JOB_CLOSE); stop then only finalizes the record.

`exec sweep` (also piggybacked on every operator invocation): scan run
records lacking a terminal state; runs past their deadline are terminated
via their named job and marked `expired`; runs whose watchdog and pid are
dead with a stale heartbeat are finalized `indeterminate` so they stop
rescanning.

### Command surface changes

- `exec start` gains `--max-lifetime SECONDS` (default 3600, clamped to
  [10, 86400]); `--timeout` remains the front-end supervision budget
  (default 120, exit 124) and is clamped to the max lifetime.
- `exec status` output gains `deadline_utc`, `watchdog_pid`,
  `heartbeat_age_seconds`.
- `exec sweep` is a new read-mostly subcommand (terminates expired
  runs; never touches healthy ones).
- All operator children (tasks and exec) run with
  `MSBUILDDISABLENODEREUSE=1` in addition to job custody (defense in
  depth against node lingering even where custody is unavailable).

### Platform scope (honest)

Windows is the governed platform and gets the full kernel guarantee
(I1/I2 by Job Object). On POSIX the watchdog still enforces deadlines
and reaps at completion via process-group signals, but watchdog death by
SIGKILL cannot kernel-kill the tree — custody there is
watchdog-alive-only, recorded as a platform gap, not silently claimed.

## 4. Failure modes

| Failure | Behavior |
| --- | --- |
| Job Object creation fails | run refuses to start (I7), exit 2 with the reason |
| Watchdog spawn fails | run refuses to start; no child exists |
| Watchdog dies mid-run | kernel kills tree instantly (I2); record later finalized `indeterminate` |
| Front-end dies mid-supervision | watchdog unaffected; run bounded by deadline (I3) |
| Deadline reached | record pre-written `expired`; job terminated; exit code not guessed |
| `exec stop` on dead job | job-gone means tree-dead; record finalized `stopped` |
| Record write fails mid-run | last durable record wins; status degrades to `indeterminate`, never invention |
| Primary spawns recursive tree | ACTIVE_PROCESS job cap (512) starves it; leak-free by construction |
| Quoted/batch argv hardening | unchanged from the 2026-09-23 window-discipline fix (`cmd /d /c call`, ROOT resolution, spawn_argv recording) |

## 5. Test spine

Named regression classes (each maps to a numbered case group in
`tools/operator-test.py`):

- C1 node-reuse leak: a primary that exits while a grandchild lingers ->
  after grace, grandchild is DEAD (the msbuild class).
- C2 deadline lease: sleeping child with tiny `--max-lifetime` ->
  `expired`, tree dead, without any caller action.
- C3 custodian death: kill the watchdog -> child dies within seconds
  (kill-on-close).
- C4 front-end 124 preserved; child continues; and later dies by lease
  with no further caller.
- C5 stop kills job-orphaned members (members whose parent already
  exited).
- C6 task custody: gate task spawning a lingering grandchild -> task
  completes, grandchild dead.
- C7 sweep terminates expired runs and finalizes stale records.
- C8 record rewrites are atomic (concurrent readers never see corrupt
  JSON).
- C9 records carry the custody identity fields.
- C10 heartbeat freshness is observable in status while running.
- C11 exit-code mirroring and indeterminate semantics unchanged.
- C12-C16 the 2026-09-23 window/capture regression suite unchanged
  (batch chains, UTF-8, 1 MB+ output, stdin EOF, `.cmd` wrapping).
- Router: chained exec after `&&` classifies (leading whitespace
  tolerance, closing OBL-20260923T224500Z-A7B8C9); tree-sweep commands
  (`find /root`, `dir /s`, `grep -r`) are long-class; `find "literal"
  file` (filter form) stays allowed.

## 6. Dependencies and rollout

Standard library only (ctypes on Windows). The operator runtime stays a
single-file managed snapshot; `templates/.../qiven_operator.py.in` stays
byte-identical to `tools/qiven_operator.py`; the template version bumps
so consumer repositories re-sync deliberately. Devkit + qiven-context
roll in this batch (context is the heaviest exec consumer); the
remaining sibling repositories roll on their next touching batch
(recorded obligation with explicit trigger — visible, not silent).

## 7. Deferrals

- POSIX kernel-grade custody (process subreaper / PR_SET_PDEATHSIG):
  deferred; failure signal = a POSIX session leaking a run past its
  deadline; revisit trigger = a POSIX agent runtime joining the program.
- Cross-repo central reaper service: deliberately NOT built (no-daemon
  law); the per-run watchdog + invocation piggyback sweep covers the
  requirement without a service.
- Job UI restrictions / CPU rate limits: not required by any incident;
  revisit if a runaway-CPU class appears that the ACTIVE_PROCESS cap
  does not cover.

## 8. Review record

Self-review (pre-implementation, 2026-09-23):

1. Watchdog-in-job vs watchdog-outside: in-job chosen — it converts
   "watchdog dies" from a leak into an immediate kernel tree-kill, at
   the cost that an outer-job kill takes the run with it. That cost is
   exactly the post-session behavior the incident demands (bounded to
   zero when the IDE reclaims its tree).
2. TerminateJobObject self-kill of the watchdog requires the final
   record to be durable BEFORE termination — the design writes the
   terminal record first everywhere (deadline path, completion path).
3. The 1.5 s grace before reaping trades a bounded late-flush window
   against killing a writer mid-line; stderr/stdout share one handle so
   no offset interleaving hazard exists.
4. `--max-lifetime` defaults to 1 h, not infinity: the incident's
   "still burning after the session" becomes impossible by construction;
   callers wanting longer pass an explicit value and own it.
5. Exit-code mirroring via TerminateJobObject keeps `exec start`
   observability identical to v1 for the common in-budget case.
