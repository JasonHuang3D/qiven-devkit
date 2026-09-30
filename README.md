# Qiven Devkit

Qiven Devkit defines how a Qiven repository is created, safely adopted, and kept aligned with shared engineering conventions.

## Responsibility boundaries

- **qiven-toolchain-win** owns pinned executable build tools such as CMake and clang-format.
- **qiven-devkit** owns repository templates, shared engineering conventions, explicit bootstrap/synchronization tooling, and the shared Qiven Operator runtime.
- **qiven-workspace** owns ecosystem version composition: the control repository (`JasonHuang3D/qiven-workspace`) is live, its generation-bound lock selects revisions, and the workspace resolver is the accepted dependency endpoint (ADR-0052; WR-0..WR-8 DELIVERED end to end 2026-09-28: every workspace repository declares its dependencies through a repository-owned manifest and the graph resolves authoritatively).
- Runtime repositories such as **qiven-foundation** own their APIs, implementation, tests, domain architecture, and repository-specific Operator policy.

Devkit materializes an ordinary snapshot into each generated repository. Generated repositories carry their own scripts and engineering
protocol, and invoke the shared Qiven Operator through the workspace: their launcher runs the bootstrap identity-check against the workspace lock and then imports the Devkit operator from the LOCKED devkit node (WR-6; the former vendored operator copies and the never-call-back model are retired). They remain independently usable after generation.

## Authority resolution

When instructions conflict, resolve by source class, not by file order:

1. **Canonical project cognition** (`JasonHuang3D/qiven-context`): collaboration contracts, ADRs, governance, typed handoffs — loaded at cold boot; nothing here overrides them.
2. **Devkit engineering law** (this repository: `docs/conventions/` + `docs/engineering/`) — the single canonical engineering protocol (ADR-0046).
3. **Repository architecture** (each repository's `docs/architecture/`) — domain contracts; may specialize, never contradict 1-2.
4. **Task specification** — may specialize ordinary implementation details for one feature; never silently override repository-wide architecture or safety rules.

(The root `AGENTS.md` is a self-hosting pointer and defines no precedence itself; this section is the operative resolution procedure.)

## Qiven Operator

Qiven Operator is the Python orchestration layer behind human-facing engineering commands. Windows CMD is intentionally a thin entry point; Python owns process execution, layout/color, buffered logs, heartbeat output, parallel task groups, fail-fast gates, exact Git validation, and asynchronous CI dispatch semantics.

A generated repository can run its default local gate with:

```bat
tools\qiven.cmd gate
```

An exact candidate gate can require the expected HEAD:

```bat
tools\qiven.cmd gate --expect-head <sha>
```

Machine consumers can request JSON by placing the global flag before the command:

```bat
tools\qiven.cmd --json gate --expect-head <sha>
```

Human output can retain the stable state layout while disabling ANSI color:

```bat
tools\qiven.cmd --no-color gate --expect-head <sha>
```

CI dispatch is explicitly asynchronous — `tools\qiven.cmd ci start full`
validates the local Git context, requires the named `origin` branch to
point at the exact local HEAD, dispatches the configured workflow through
`gh`, and returns immediately (no sleeps, no "latest"-run guessing).

Usage law — command surface, routing, custody, exit codes, `ci watch`
observation — has a single home:
[`docs/conventions/operator-usage.md`](docs/conventions/operator-usage.md).
Ownership/distribution states:
[`docs/operator-contract.md`](docs/operator-contract.md) (Phase-1 design
history: `docs/legacy/design/operator-phase1.md`). Shared mechanism is
managed by Devkit; repository policy lives in `.qiven/operator.json`.

## Managed and bootstrap-only files

Managed files are shared conventions. `python tools/sync_repo.py` can update them after an all-or-nothing hash preflight. The list is
stored in `templates/cpp-library/managed-files.cmake` and includes formatting/editor policy, presets, and local developer tools (engineering standards are Devkit-canonical per ADR-0046 — `docs/engineering/` here — and not part of the managed set),
plus `AGENTS.md`. The managed set carries no Qiven Operator (WR-6 retirement — see "Responsibility boundaries" above; grandfathered instances are a recorded wr6-report consolidation residual).

Bootstrap-only files are starting points expected to diverge: `.gitignore`, `README.md`, `CMakeLists.txt`, and
`.github/workflows/ci.yml`. Synchronization never overwrites them.

## Generate a C++ library repository

*(Entrypoints renamed 2026-09-19, commit `440f8bc`: the former
`new-cpp-library.cmd`/`adopt-cpp-library.cmd`/`sync-repo.cmd`/`test.cmd`
wrappers are gone; the Python tools below are the live surface.)*

On Windows:

```bat
python tools\new_cpp_library.py D:\JasonWork\qiven-math qiven-math qiven-math qiven-math qiven::math qiven::math QIVEN_MATH_BUILD_TESTS qiven-math
```

Arguments are destination, repository name, CMake project name, CMake target name, CMake alias, C++ namespace, test option,
and optional Visual Studio solution name (defaults to the repository name). The destination must be absent or empty.

The platform-neutral core can also be called with CMake script mode; see `tools/test.cmake` for a complete invocation.

## Adopt an existing C++ library repository

Adoption is an explicit two-phase operation. First inspect the complete deterministic plan without changing the target:

```bat
python tools\adopt_cpp_library.py check ^
  D:\JasonWork\qiven-foundation ^
  qiven-foundation ^
  qiven-foundation ^
  qiven-foundation ^
  qiven::foundation ^
  qiven ^
  QIVEN_BUILD_TESTS ^
  qiven-foundation
```

If the check reports no conflicts, apply the same plan:

```bat
python tools\adopt_cpp_library.py apply ^
  D:\JasonWork\qiven-foundation ^
  qiven-foundation ^
  qiven-foundation ^
  qiven-foundation ^
  qiven::foundation ^
  qiven ^
  QIVEN_BUILD_TESTS ^
  qiven-foundation
```

The target must be the clean root of an existing Git repository with a HEAD commit and no `.qiven` ownership state. `check`
is read-only with respect to the target. Both modes classify every managed path as `EXACT`, `MISSING`, or `CONFLICT`; any
conflict prevents application and leaves the repository untouched. A successful apply preserves exact files, creates only
missing managed files, and then writes `.qiven/repo.json` and `.qiven/generated-state.cmake`. Adoption never overwrites a
divergent managed file and never changes bootstrap-only or unrelated domain files. Once adopted, use `sync-repo` for updates.

## Synchronize managed files

```bat
python tools\sync_repo.py D:\JasonWork\qiven-math
```

Generation records state schema 2 in `.qiven/generated-state.cmake`: the complete managed path set plus a SHA-256 hash for
each generated path. Sync preflights the union of old and new managed paths, safely handling additions, removals, and renames
as well as content updates. It modifies nothing if any consumer/Devkit conflict exists. Bootstrap-only files are never
considered or changed. After success, `repo.json` and generated state report the same current template version. Successful
updates leave normal reviewable Git diffs. Schema changes require an explicit migration before sync accepts older state.

## Test

```bat
python tools\operator-test.py
```

Tests use disposable fixture directories only. The suite includes Operator generation, JSON/human output separation, heartbeat/no-color behavior, task environment and working-directory isolation, fail-fast sequencing, parallel execution, exact-HEAD validation, real clean-tree gates, and asynchronous CI exact-remote-head dispatch preconditions.
