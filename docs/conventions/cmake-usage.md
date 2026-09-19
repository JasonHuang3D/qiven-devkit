# CMake Usage Law

How CMake is used across `qiven-*` repositories. The naming rules are in
[naming-cmake.md](naming-cmake.md); this document is about HOW to invoke and
structure the build.

## Presets are the only entry point

- Configure through a preset: `cmake --preset <name>` (for example
  `vs2022-x64`).
- Build through a preset: `cmake --build --preset vs2022-x64-debug`.
- Test through a preset: `ctest --preset vs2022-x64-debug`.

Hand-rolled `cmake -D...` invocations without a preset are forbidden: the
presets exist so that every developer and every agent configures identically.
If a configuration is missing, add a preset — do not improvise one-off flags.

## Toolchain pinning

- Compilers and tools come from `qiven-toolchain-win` via the toolchain
  manifest; the host PATH is not the source of truth for tool versions.
- Set `QIVEN_TOOLCHAIN_ROOT` only when the toolchain checkout is not a
  sibling of the repository.

## In-source builds are forbidden

- Everything generates under `build/` (gitignored). If a generator writes
  outside `build/`, fix the generator, not the ignore file.

## Structure law

- The root `CMakeLists.txt` defines the project, includes presets, and adds
  subdirectories; it does not carry target logic that belongs in a
  subdirectory.
- Test executables are registered under `tests/` with their own
  `CMakeLists.txt` and `add_test` entries; every public header has a
  self-containment compilation unit.
- Options gate optional builds (`QIVEN_BUILD_TESTS`) and default sensibly
  when the repository is consumed as a subproject.

## Gates

- A repository's Operator gate (`.qiven/operator.json`) is the only blessed
  validation sequence; ad-hoc CMake invocations do not replace it.
- Batch-final validation is FULL (configure + build Debug + Release + tests +
  format + diff-check + clean-tree) unless the task specification explicitly
  defines a focused scope.
