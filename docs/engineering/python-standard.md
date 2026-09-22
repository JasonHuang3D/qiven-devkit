# Python Engineering Standard

This document is the SINGLE CANONICAL quality law for Python in every
`qiven-*` repository (ADR-0046: Devkit owns engineering standards;
repositories carry no copies). It exists because Python code in this
workspace executes REAL work on a REAL machine — builds, tests, process
custody, publication gates — and its defects are not lint noise: the
2026-09-23 post-session incident (dozens of orphaned msbuild/cmd
processes and a ghost find.exe holding ~70% CPU until an OS restart)
was caused by a Python tool whose survival semantics were unbounded and
whose cleanup was behavioral instead of mechanical. Sloppy Python is an
operational hazard here, not a style problem.

This standard applies to `tools/*.py`, the Operator runtime, hook
scripts, and any Python the repositories ship. It binds humans and AI
sessions identically. Where `implementation-standard.md` states a
general law, this document specializes it for Python.

## 1. Hard rules (violations are defects, not preferences)

1. **Every subprocess is custodied and bounded.** Spawning a process
   means owning its whole tree until it demonstrably ends. On Windows
   that means a Job Object (`KILL_ON_JOB_CLOSE`) or the operator's exec
   custody; "fire and forget", "the parent exited so someone else will
   reap it", and `start_new_session`-without-a-reaper are all defects.
   Every wait has an explicit timeout; a timeout is a classification
   event, never a verdict and never a silent-retry trigger.
2. **Never spawn children that outlive their purpose.** If a tool's
   legitimate work ends when its primary command ends, the tree dies
   with it (completion reap). Anything that must survive a caller must
   carry an explicit bounded lease and a named custodian
   (`qiven exec` is the ONLY sanctioned mechanism).
3. **Fail closed.** If a custody primitive, timeout, or precondition
   cannot be established, do NOT proceed with degraded custody. A run
   that cannot start under custody does not start (exit 2 with the
   reason), never starts uncustodied.
4. **Standard library only** for the Operator runtime and gate tools
   (stdlib + `ctypes` on Windows). Third-party Python dependencies
   require an explicit owner-recorded decision; scripts never acquire a
   `pip install` bootstrap implicitly.
5. **No silent detours** (owner direction, MEM-20260923T211500Z-C3D4E5):
   a failing owned tool is root-caused or escalated, never routed
   around via a sibling script or alternate entry point.
6. **Files are authored through native file tools, never shell
   heredocs / echo-redirects / embedded content** (contract law;
   enforced mechanically by the hook router).
7. **Bytecode is never committed**; `__pycache__/` and `*.pyc` are
   gitignored everywhere.

## 2. Windows process law (the scar tissue)

These rules exist because each one was an observed incident. They are
mandatory for any code that spawns processes on Windows:

1. `CREATE_NO_WINDOW`, never `DETACHED_PROCESS`, for hidden children:
   a detached child has NO console, so console descendants allocate
   VISIBLE popups, lose their redirected stdio (empty-log symptom), and
   can fail console-DLL init outright (`0xC0000142`).
2. `bInheritHandles=TRUE` inherits EVERY inheritable handle, not just
   the std trio. De-inherit your own stdio (or use an explicit handle
   list) before spawning, or a supervisor's pipe stays open until the
   entire descendant tree exits (observed: a 1 s supervision budget
   blocked 13.8 s).
3. `STARTUPINFO.hStd*` fields carry HANDLES, not fd numbers. Convert
   with `msvcrt.get_osfhandle`; an fd number there silently loses the
   child's redirected output.
4. Pass environments as mappings to `_winapi.CreateProcess`/`Popen(env=...)`.
   Hand-rolled environment blocks marshaled through raw `CreateProcessW`
   calls fail with `WinError 87` for no diagnosable reason; the stdlib
   path is battle-tested — use it.
5. Task children get `CREATE_SUSPENDED` → `AssignProcessToJobObject` →
   `ResumeThread` (zero-race custody); children that must NOT escape a
   job are never spawned with `CREATE_BREAKAWAY_FROM_JOB`.
6. Liveness is wait-based (`WaitForSingleObject`), never
   `GetExitCodeProcess == STILL_ACTIVE` (a genuine exit code 259
   misreports as alive; PID reuse compounds it).
7. Atomic file replace (`os.replace`) collides with concurrent readers
   on Windows (readers cannot request `FILE_SHARE_DELETE`): writers
   retry `PermissionError` briefly; readers retry it briefly too. A
   record writer must never crash its process on a transient collision.
8. `.cmd`/`.bat` targets are invoked through an explicit
   `cmd.exe /d /c call <absolute path>`; a path-like argv[0] resolves
   against the intended child cwd/root BEFORE spawning.
9. MSBuild-invoking children run with `MSBUILDDISABLENODEREUSE=1`
   (node reuse is the observed leak amplifier even under custody).

## 3. Process and structure

1. One tool per file, `snake_case.py`; the filename is the verb phrase.
   Entrypoint: `if __name__ == "__main__": raise SystemExit(main())`;
   `main(argv=None) -> int` and the int IS the contract
   (0 pass / 1 task failure / 2 environment or usage error).
2. `from __future__ import annotations` at the top of every module;
   full type annotations on public functions; `Any` only at genuine
   JSON/dynamic boundaries, never as a laziness escape.
3. No module-level side effects beyond constant definitions and pure
   path resolution. Module import never spawns processes, opens
   sessions, or mutates state that a test must then undo.
4. Shared mutable module state is a defect unless the module documents
   the ownership (the kernel32 prototype cache is the pattern: lazily
   initialized, append-only, no re-entrancy).
5. The Operator runtime stays a SINGLE FILE (a managed snapshot rolled
   into every repository). Multi-file refactors of it are forbidden
   without an owner decision: the distribution constraint is
   load-bearing. Internal structure compensates: section banners,
   one-concern-per-block, no dead code, no leftover scaffolding.
6. Dead code, unused constants, commented-out experiments, and
   "temporarily" disabled checks are removed before commit — the diff
   tells one story (implementation-standard §14).

## 4. Error handling and honesty

1. Distinguish failure classes: usage/environment errors (exit 2),
   task failures (exit 1 or the child's code), and internal invariant
   violations (a loud traceback — never a swallowed `except: pass`).
2. `except Exception: pass` is permitted ONLY at documented
   never-must-gate boundaries (e.g. duration logging), with the
   exception class named in a comment saying WHY it cannot gate.
3. Never guess unknowns into facts: unobserved exits are
   `indeterminate`, not 0; missing measurements are absent, not 0.0;
   absent config is an error, not a default that happens to work.
4. Failure messages carry the evidence needed to act (paths, pids,
   winerrors, the exact command) — "could not start process" alone is a
   defect of the message, not just the process.
5. Logging/diagnostics must never block or kill the primary function:
   a watchdog that crashes writing a heartbeat has failed at BOTH jobs.

## 5. Concurrency

1. State the concurrency contract before adding threads: who owns what,
   which channels cross threads, and the shutdown order. Undocumented
   `threading` is a defect even when it "works".
2. Bounded resources only: bounded pools, bounded queues, bounded
   retry counts with explicit budgets. No unbounded accumulation of
   processes, records, or files without a compaction/rotation rule.
3. Shared-console output goes through one lock; interleaved markers are
   unreadable and lose their diagnostic value.
4. Races on Windows file semantics (rename vs reader) are handled at
   BOTH ends (writer retry, reader retry) — one-sided fixes fail
   intermittently and erode trust in the tool.

## 6. Output discipline

1. Human-facing output is state-based: `[ RUN]` / `[WAIT]` /
   `[ OK ]` / `[FAIL]` markers, flushed; progress reports observable
   state only — no invented percentages, ETAs, or decorative animation.
2. `--json` emits ONE stable, sorted, machine-parseable document on
   stdout; large payloads spill to a durable file with the path carried
   in the envelope. Human prose never contaminates the JSON stream.
3. `print` belongs to CLI tools only; library code raises or returns.
4. All file I/O names `encoding="utf-8"` explicitly (and
   `errors="replace"` where lossy display is intended); relying on
   locale defaults is a portability defect. `newline="\n"` explicit on
   authored text.

## 7. Time and determinism

1. Durations and deadlines use `time.monotonic()`; wall-clock stamps
   (UTC, RFC3339) are for records and display only. Never compute a
   timeout from `time.time()`.
2. Tests do not depend on wall-clock timing beyond explicit budgets;
   sleeps in tests are bounded waits with predicates (`wait_until`
   pattern), and a missed predicate is a failure, not a re-roll.
3. A flake is a defect candidate (testing-standard §16): diagnose or
   record it; consecutive-clean-run requirements apply before any
   stability claim.

## 8. Testing law for Python tools

1. Every tool with engineering semantics carries a self-test that a
   gate task executes (the operator-tests / router-tests pattern), and
   every fixed defect adds its regression case to that suite — the
   2026-09-23 incident's custody laws each have a named case (C1-C10).
2. Tests generate their own disposable fixtures (temp trees), assert
   cleanup where custody is the contract (a leaked test process is a
   failed test, not a green one), and never touch the developer's
   repositories or global state.
3. Test helpers assert ONE named concern per check with the case id in
   the failure message — a failure must identify the law that broke.
4. Monkeypatching module internals is acceptable for boundary seams
   (`_run_capture`, `shutil.which`), never to bypass the code under
   test's own semantics.

## 9. Review record

Self-review 2026-09-23 (pre-publication):

1. Single-file operator constraint kept despite size pressure — the
   managed-snapshot distribution model is the reason the operator
   exists per repository at all; internal section discipline is the
   compensating control.
2. §2's rules are deliberately incident-derived rather than exhaustive
   Windows guidance; generic platform knowledge lives in
   implementation-standard §9, this file records what WE burned
   ourselves on and must never repeat.
3. The stdlib-only rule (§1.4) does not forbid vendoring Python
   dependencies under the third-party standard's class model; it
   forbids IMPLICIT dependency acquisition. An explicit
   PROVENANCE-recorded Python package follows the third-party law
   instead.
4. No automated detector yet for §1.1/§1.2 (e.g. a lint that rejects
   `subprocess.Popen` outside custody helpers) — recorded as the first
   candidate if manual review shows drift (engineering README
   "protocol evolution" question 5).
