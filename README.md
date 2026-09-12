# Qiven Devkit

Qiven Devkit defines how a Qiven repository is created and kept aligned with shared engineering conventions.

## Responsibility boundaries

- **qiven-toolchain-win** owns pinned executable build tools such as CMake and clang-format.
- **qiven-devkit** owns repository templates, shared engineering conventions, and explicit bootstrap/synchronization tooling.
- **qiven-workspace** may later own ecosystem version composition and multi-repository orchestration; it does not exist yet.
- Runtime repositories such as **qiven-foundation** own their APIs, implementation, tests, and domain architecture.

Devkit materializes an ordinary snapshot into each generated repository. Generated repositories contain their own scripts and
engineering protocol and never call back into a Devkit checkout. They remain independently usable after generation.

## Managed and bootstrap-only files

Managed files are shared conventions. `tools/sync-repo.cmd` can update them after an all-or-nothing hash preflight. The list is
stored in `templates/cpp-library/managed-files.cmake` and includes formatting/editor policy, presets, local developer tools,
`AGENTS.md`, and the engineering protocol.

Bootstrap-only files are starting points expected to diverge: `.gitignore`, `README.md`, `CMakeLists.txt`, and
`.github/workflows/ci.yml`. Synchronization never overwrites them.

## Generate a C++ library repository

On Windows:

```bat
tools\new-cpp-library.cmd D:\JasonWork\qiven-math qiven-math qiven-math qiven-math qiven::math qiven::math QIVEN_MATH_BUILD_TESTS qiven-math
```

Arguments are destination, repository name, CMake project name, CMake target name, CMake alias, C++ namespace, test option,
and optional Visual Studio solution name (defaults to the repository name). The destination must be absent or empty.

The platform-neutral core can also be called with CMake script mode; see `tools/test.cmake` for a complete invocation.

## Synchronize managed files

```bat
tools\sync-repo.cmd D:\JasonWork\qiven-math
```

Generation records state schema 2 in `.qiven/generated-state.cmake`: the complete managed path set plus a SHA-256 hash for
each generated path. Sync preflights the union of old and new managed paths, safely handling additions, removals, and renames
as well as content updates. It modifies nothing if any consumer/Devkit conflict exists. Bootstrap-only files are never
considered or changed. After success, `repo.json` and generated state report the same current template version. Successful
updates leave normal reviewable Git diffs. Schema changes require an explicit migration before sync accepts older state.

## Test

```bat
tools\test.cmd
```

Tests use disposable fixture directories only.
