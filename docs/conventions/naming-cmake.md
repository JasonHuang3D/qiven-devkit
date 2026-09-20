# CMake Naming Conventions

Applies to every `qiven-*` C++ repository.

## Targets

- Library target: raw target `qiven-<name>` with a `qiven::<snake_name>`
  namespaced alias. The alias component uses snake_case, never dashes
  (`qiven::foundation` over `qiven-foundation`, `qiven::dcr_win` over
  `qiven-dcr-win`). (Corrected 2026-09-21: the earlier text required a bare
  unprefixed raw target, which no repository followed; the reference
  implementation, qiven-foundation, is normative.)
- Test executables: `qiven-<repo>-<topic>` (`qiven-foundation-byte-cursor`,
  `qiven-context-draft-persistence`).
- App executables: `qiven-<repo>` when the app is the repository's primary
  product (`qiven-host`), `qiven-<repo>-app` when an app ships beside a
  library (`qiven-dcr-win-app`). App aliases use `qiven::<name>_app`.

## CTest names

- `qiven-<repo>.<topic>` — a DOT between repository and topic, mirroring the
  executable (`qiven-foundation.hashing`, `qiven-context-draft.persistence`).

## Options and variables

- Options and cache variables: `QIVEN_` prefix, SCREAMING_SNAKE
  (`QIVEN_BUILD_TESTS`, `QIVEN_TOOLCHAIN_ROOT`).
- Local helper variables: lowercase or snake_case (`qiven_sources`).

## Functions and macros

- Helper functions: `qiven_<verb>_<object>` snake_case with the `qiven_`
  prefix (`qiven_enable_test_warnings`,
  `qiven_context_draft_enable_strong_warnings`).

## Files

- Root `CMakeLists.txt`; per-directory `CMakeLists.txt`; reusable modules as
  `snake_case.cmake` (`managed-files.cmake`).
- Generated files are named for what generates them and are never committed.

## Properties

- Every target sets `CXX_EXTENSIONS OFF`; test and app targets set the FOLDER
  property (`Tests` / `Apps`) and the debugger working directory where a
  runnable target exists.
