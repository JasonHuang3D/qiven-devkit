# Third-Party Dependency Standard (v2 — workspace singleton)

This document is the SINGLE CANONICAL rule set for consuming third-party
open-source code anywhere in the Qiven workspace (ADR-0046: Devkit owns
engineering standards; repositories carry no copies). v2 (2026-09-23,
owner direction) replaces the per-repo `third_party/` model of v1 with a
**workspace singleton**: third-party code lives in exactly ONE place for
the whole workspace, because a dependency used by several repositories
must not be vendored once per repository (N copies, N provenance
records, N drift surfaces).

Goals, unchanged from v1: every build is **hermetic, reproducible,
auditable and clean** — a fresh clone plus the sibling workspace layout
builds offline, with no global package managers, no system-wide
installs, and no reliance on any path outside the workspace.

## 1. The singleton

- **Home**: the sibling repository `qiven-third-party-win`
  (`JasonHuang3D/qiven-third-party-win`). The `-win` suffix mirrors
  `qiven-toolchain-win`: class-P prebuilt artifacts are platform-bound;
  class-S source is portable but is pinned under the same
  platform-scoped umbrella. A future non-Windows workspace gets its own
  singleton.
- **One dependency, one copy, one provenance record, one CMake target**:
  `qiven::tp::<name>`, defined by the singleton's package CMakeLists
  (§4), consumed by every repository that needs it (§5).
- Per-repository `third_party/` directories are **FORBIDDEN** from v2
  on. The one v1 instance (qiven-runtime's SQLite) was migrated to the
  singleton in the same v2 landing.
- OS-provided system libraries (Win32 API, CRT, DPAPI, WMI …) are NOT
  third-party; use them directly. First-party workspace layers
  (foundation, devkit, toolchain, draft) are NOT third-party either —
  they follow the ADR-0046/0039 layer model and the cross-repo CMake
  conventions (`../conventions/cross-repo-cmake.md`); see §8 for the
  honest comparison the owner raised.

## 2. Dependency classes

Every package declares its class in PROVENANCE.yaml. The classes are
mechanically different; each has its own layout and CMake shape.

| Class | Name | Content | CMake target form |
| --- | --- | --- | --- |
| **S** | source-compiled | pristine upstream source | real compiled library target (§4.1) |
| **P** | prebuilt | upstream (or repackaged) binaries per configuration | `IMPORTED` library, `GLOBAL`, per-config locations (§4.2) |
| **H** | header-only | pristine headers | `INTERFACE` library (§4.3) |
| **F** | fetched-source | upstream archive fetched ONCE at acquisition into the singleton | becomes class S after landing (§3) |

Class F is an acquisition mode, not a steady state: network fetching
happens exactly once, INTO the singleton, at (re)vendoring time, via
the Qiven Operator (hang-contract rule 5). Consumer builds never touch
the network — `FetchContent`/`ExternalProject` at consumer configure
time is FORBIDDEN (a consumer configure must stay offline and
reproducible from the singleton checkout alone).

## 3. Package layout (singleton)

```text
qiven-third-party-win/
  README.md                     index: which packages, which classes
  AGENTS.md                     pointer pattern (Devkit standards)
  packages/
    <name>/
      PROVENANCE.yaml           the pin record (machine-checked)
      LICENSE                   upstream license text, verbatim
      README.md                 what/why/class/consumers/slot notes
      CMakeLists.txt            REQUIRED for every class (§4)
      src/                      class S: pristine source (flat ok for amalgamations)
      include/                  class P/H: headers
      prebuilt/x64/<Config>/    class P: .lib/.dll per configuration
      patches/*.patch           unified diffs on top of the pinned source
```

PROVENANCE.yaml (v2 schema) keeps: schema
(`qiven-third-party-provenance-v2`), name, class (S/P/H/F-record),
version, source_url, source_revision, acquired_at, archive_digest
(upstream-published digest WITH its algorithm — sqlite.org publishes
SHA3-256), per-file sha256 inventory (every committed file except
PROVENANCE.yaml and CMakeLists.txt), patches list, justification
(required for class P), consumers (repos + design slots), license.

Rules carried from v1 unchanged: any edit to a vendored file updates
PROVENANCE.yaml in the same commit; version bumps are their own batch
with full gates; licenses vendored verbatim (permissive only; copyleft
requires an owner-recorded ADR); patch policy (pristine default,
numbered unified diffs, removal plan, review after two upstream
releases).

## 4. Per-class CMake law (the package's own CMakeLists)

Every package carries a CMakeLists.txt — for EVERY class. A prebuilt
without one cannot link per-configuration; a header-only without one
cannot carry usage requirements. The file is workspace-owned glue
(exempt from the provenance digest inventory) and is the ONLY place the
target exists.

Common law for all classes: target name `qiven::tp::<name>` (real
target `qiven-tp-<name>` + ALIAS); no `add_definitions`/global-scope
pollution; usage requirements PUBLIC, everything else PRIVATE; PCH off.

### 4.1 Class S — source-compiled

```cmake
add_library(qiven-tp-<name> STATIC src/<...>.c)
set_target_properties(qiven-tp-<name> PROPERTIES LINKER_LANGUAGE C
    DISABLE_PRECOMPILE_HEADERS ON FOLDER "ThirdParty")
target_include_directories(qiven-tp-<name> PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>)
# flag adaptation scoped to THIS target only (upstream law, not ours):
if(MSVC)
    target_compile_options(qiven-tp-<name> PRIVATE /W3 /utf-8)
endif()
target_compile_definitions(qiven-tp-<name> PRIVATE _CRT_SECURE_NO_WARNINGS <upstream feature macros>)
```

- Upstream warning laws are NOT our laws: `/W4 /permissive-` never
  propagates into third-party targets; suppressions the upstream
  requires are PRIVATE on the target.
- Feature macros that change behavior we depend on are PRIVATE and
  documented in the package README.
- CRT/exception/sanitizer models must match first-party targets (MSVC
  per-configuration defaults do this; never override one side only).
- No directory-level `EXCLUDE_FROM_ALL` on the consuming
  `add_subdirectory` (the VS generator drops consuming
  ProjectReferences under it → LNK1104; verified in the v1 SQLite
  landing). Third-party targets joining the `all` build is accepted
  cost (seconds), grouped under a `ThirdParty` folder.

### 4.2 Class P — prebuilt

```cmake
add_library(qiven::tp::<name> STATIC IMPORTED GLOBAL)
set_target_properties(qiven::tp::<name> PROPERTIES
    IMPORTED_LOCATION_DEBUG          "${CMAKE_CURRENT_SOURCE_DIR}/prebuilt/x64/Debug/<name>.lib"
    IMPORTED_LOCATION_RELEASE        "${CMAKE_CURRENT_SOURCE_DIR}/prebuilt/x64/Release/<name>.lib"
    IMPORTED_LOCATION_MINSIZEREL     "${CMAKE_CURRENT_SOURCE_DIR}/prebuilt/x64/Release/<name>.lib"
    IMPORTED_LOCATION_RELWITHDEBINFO "${CMAKE_CURRENT_SOURCE_DIR}/prebuilt/x64/Release/<name>.lib"
    INTERFACE_INCLUDE_DIRECTORIES    "${CMAKE_CURRENT_SOURCE_DIR}/include")
# DLL form: IMPORTED_IMPLIB per config + the DLL ships beside consumers
# at deploy time (deployment standard carries it in the bundle).
# Config-subset prebuilts MUST map explicitly — a Debug consumer linking
# a Release-only .lib silently is forbidden:
#   set_target_properties(... MAP_IMPORTED_CONFIG_DEBUG Release)
```

- `GLOBAL` is REQUIRED: imported targets are directory-scoped, and
  consumers add the package from their own trees.
- Per-config locations are REQUIRED: a single `IMPORTED_LOCATION` for a
  multi-config generator is a defect (Debug/Release mixing).
- Provenance records the sha256 of every prebuilt binary; the
  justification line records why source build was impractical.
- Class-P packages MUST state their runtime-library expectation
  (/MD vs /MT) in the README; a CRT mismatch with consumers is a
  land-block, not a warning.

### 4.3 Class H — header-only

```cmake
add_library(qiven::tp::<name> INTERFACE)
target_include_directories(qiven::tp::<name> INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/include")
# header-only libraries needing compile definitions on consumers carry
# them as INTERFACE_COMPILE_DEFINITIONS here, never at consumer sites
```

## 5. Consumption law (every consuming repository)

1. **Root resolution** (fail-closed, no system discovery):
   `QIVEN_THIRD_PARTY_ROOT` env override → sibling default
   `<repo>/../qiven-third-party-win` → explicit failure with
   instructions. `find_package` for governed third-party code is
   forbidden (it can silently bind system/vcpkg/PATH copies);
   the build is hermetic to the workspace.
2. **Pin**: the consumer records the singleton's exact SHA
   (`QIVEN_THIRD_PARTY_PIN` in its CMakeLists, the same discipline as
   the draft pin) and configure FAILS when the checkout is at another
   SHA. Moving the pin is an explicit re-pin batch with full gates.
3. **Consumption**: `add_subdirectory("${QIVEN_THIRD_PARTY_ROOT}/packages/<name>"
   "${CMAKE_BINARY_DIR}/tp/<name>")` then link `qiven::tp::<name>`.
   Consumers never add third-party include paths of their own and never
   re-declare third-party flags.
4. **Spot verification (defense in depth)**: the singleton's own gate
   verifies every provenance; a consumer MAY additionally run the
   verifier against the singleton root in its gate (cheap; the
   runtime does).
5. **Style/whitespace gates** never apply to the singleton tree (it is
   not inside the consumer repository at all); v1's exclusions become
   moot, and the pinned formatter never touches upstream code.

## 6. Acquisition procedure (into the singleton, operator-mediated)

1. Resolve the exact upstream artifact + its PUBLISHED digest
   (algorithm named).
2. Download/clone via the Qiven Operator (`exec start` — the hook
   router enforces routing for raw transfer commands).
3. Extract under `.generated-temp/`, copy ONLY needed source/headers/
   binaries + LICENSE into `packages/<name>/`.
4. Generate the per-file digest list mechanically; write README +
   CMakeLists per class; register the consumer's design slot.
5. Run the singleton gate (provenance verify + configure smoke of every
   package CMakeLists).
6. Consumers re-pin to the new singleton SHA in the same batch when a
   new package or version lands for them.

## 7. Verification — the singleton gate

The singleton repo's gate: `verify-provenance` (every package, every
file, plus present-on-disk-but-unlisted detection, plus CMakeLists
presence per package) and `configure-smoke` (every package CMakeLists
configures standalone). Failing the verifier is never "comment out the
digest" — investigate, re-vendor deliberately, or restore.

## 8. First-party layers are not third-party (the owner's question)

"If our own foundation were a third-party library cloned from GitHub —
would the current CMake consumption be right?" Answered honestly:

- Foundation/draft consumption today = sibling source checkout +
  in-consumer `add_subdirectory` build + (for the draft) an exact-SHA
  pin validated at configure. For CO-DEVELOPED first-party layers this
  is a valid mode ("layer model", ADR-0039/0046): you want the local
  source, and the layer evolves with its consumers.
- It is NOT the right model for third-party code: no per-repo
  vendoring (that is what v2 removes), no network at configure, no
  per-repo flag adaptation, and binary reuse questions do not arise
  because classes S/H compile once per consumer build tree by design.
- Recorded gap (first-party, deliberate): foundation consumption has NO
  exact-SHA pin (the draft does). Acceptable while layers are
  co-developed on one workspace; revisit trigger = the first
  cross-repo semantic-drift incident or any release-class build that
  must be reproducible from recorded refs alone (then foundation gets
  the same pin as the draft and the third-party pin).

## Review record

Self-review 2026-09-23 (v2, pre-publication):

1. Singleton naming: `-win` follows toolchain-win precedent; a
   portable-source-only future can split without consumer changes
   (the target name and root resolution stay stable).
2. Class P `MAP_IMPORTED_CONFIG_*` rule: the example maps Debug→Release
   only as the documented shape for config-subset prebuilts; a
   full-config prebuilt ships all four configurations instead.
   Decided: require all four where upstream provides them, explicit
   mapping where not.
3. Consumer spot-verification kept OPTIONAL (the singleton gate is the
   authority; mandatory double-checks in every consumer gate multiply
   keys for marginal assurance) — the runtime keeps its task as the
   exemplar.
4. The v1 migration (runtime's `third_party/` removal) rides the same
   batch as the standard so no state ever satisfies both versions.
