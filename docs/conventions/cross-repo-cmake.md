# Cross-Repository CMake Conventions

How a `qiven-*` repository consumes targets defined OUTSIDE itself:
first-party sibling layers (foundation, draft), the third-party
singleton (`qiven-third-party-win`, engineering standard
`../engineering/third-party-dependencies.md`), and — recorded for
contrast — what is deliberately NOT allowed. Established 2026-09-23
(v19 review) to make every external-target reference uniform.

## 1. The one consumption pattern

External code enters a consumer build in exactly ONE way:

```cmake
# --- <name>: external root resolution (fail-closed, workspace-bounded)
set(QIVEN_<NAME>_ROOT "" CACHE PATH "Path to the <name> checkout")
if(NOT QIVEN_<NAME>_ROOT)
    set(QIVEN_<NAME>_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/../<name>")
    if(EXISTS "${QIVEN_<NAME>_DEFAULT}/CMakeLists.txt")
        set(QIVEN_<NAME>_ROOT "${QIVEN_<NAME>_DEFAULT}")
    endif()
endif()
if(NOT EXISTS "${QIVEN_<NAME>_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR "<name> checkout not found; set QIVEN_<NAME>_ROOT")
endif()

# --- pin (when the external tree is version-frozen for this consumer)
set(QIVEN_<NAME>_PINNED_SHA "<full sha>")
execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse HEAD
    WORKING_DIRECTORY "${QIVEN_<NAME>_ROOT}" ... )
# mismatch -> FATAL_ERROR naming both SHAs and the re-pin procedure

# --- consumption: source layers build INTO the consumer's build tree
add_subdirectory("${QIVEN_<NAME>_ROOT}" "${CMAKE_BINARY_DIR}/<name>")
target_link_libraries(<consumer-target> ... qiven::<name>)
```

Precedence: environment/cache override → sibling-layout default →
explicit failure. NEVER a system path, NEVER `CMAKE_PREFIX_PATH`
discovery for governed targets, NEVER an in-repo copy of the external
tree.

## 2. Rules that apply to every external target

1. **Namespaced targets only.** Consumers link `qiven::<layer>` /
   `qiven::tp::<package>`; they never reference the external project's
   internal target names, never add its include directories by hand,
   and never re-state its compile flags or definitions. Usage
   requirements travel ON the target.
2. **Build placement.** An external source tree is built under the
   CONSUMER's binary dir (`${CMAKE_BINARY_DIR}/<name>`) — the external
   checkout is never written to.
3. **No directory-level `EXCLUDE_FROM_ALL` on external
   `add_subdirectory`** consumed via link: the Visual Studio generator
   drops consuming ProjectReferences under it, leaving link-line-only
   references that fail LNK1104 (verified 2026-09-23, SQLite landing).
   External targets joining `all` is accepted cost.
4. **Flag isolation is the external tree's job.** First-party layers
   carry our full warning law; the third-party singleton carries its
   own scoped adaptation law (standard §4). The consumer's global
   flags never reach either.
5. **Pins are exact and validated at configure.** Version-frozen
   consumers (draft, third-party singleton) record the full SHA and
   FAIL on mismatch; co-developed first-party layers (foundation) are
   unpinned today — a recorded gap with a revisit trigger (standard
   §8), not a silent one.
6. **IMPORTED (prebuilt) externals** must be `GLOBAL` with per-config
   locations and explicit `MAP_IMPORTED_CONFIG_*` when configurations
   are a subset (standard §4.2) — a multi-config consumer linking a
   single-config import silently is a defect.

## 3. What is deliberately NOT allowed

- `FetchContent` / `ExternalProject` / any network at consumer
  configure time (hermeticity; acquisition happens once, in the
  singleton, via the operator).
- `find_package` for governed workspace or third-party targets (silent
  system-binding risk); `find_package` for genuine OS/vendor SDKs is
  judged case by case and recorded where used.
- Vendoring external code inside a consuming repository (the v1
  third_party model — forbidden since standard v2).
- Global-scope mutation from either side: `add_definitions`,
  `add_compile_options`, `link_libraries`, `include_directories`,
  `CMAKE_<LANG>_FLAGS` writes — in consumer OR external tree.

## 4. Current registry (kept current by the landing batch)

| External | Kind | Root var | Pin | Consumers |
| --- | --- | --- | --- | --- |
| `qiven-foundation` | first-party layer (source) | `QIVEN_FOUNDATION_ROOT` | none (recorded gap) | runtime, draft, others via their CMake |
| `qiven-context-draft` | frozen semantic library (source) | `QIVEN_DRAFT_ROOT` | exact SHA, configure-validated | runtime |
| `qiven-toolchain-win` | pinned executables (env layer) | `QIVEN_TOOLCHAIN_ROOT` | toolchain.py pins | all builds via check-toolchain |
| `qiven-third-party-win` | third-party singleton | `QIVEN_THIRD_PARTY_ROOT` | exact SHA per consumer | runtime (sqlite3) |
| `qiven-devkit` | tool/standards package | `QIVEN_DEVKIT_ROOT` | shim+pin where consumed (ADR-0046 D2) | context (operator shim), runtime (deploy shim) |

New externals append here in the same batch that adds them.
