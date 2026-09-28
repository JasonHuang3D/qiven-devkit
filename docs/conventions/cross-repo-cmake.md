# Cross-Repository CMake Conventions

How a `qiven-*` repository consumes targets defined OUTSIDE itself:
first-party sibling layers (foundation, draft), the third-party
singleton (`qiven-third-party-win`, engineering standard
`../engineering/third-party-dependencies.md`), and — recorded for
contrast — what is deliberately NOT allowed. Established 2026-09-23
(v19 review) to make every external-target reference uniform.

> **Status under ADR-0052 (2026-09-24): this pattern is the MIGRATION
> STAGE, not the endpoint.** The accepted endpoint is the Workspace
> Resolution program: CMake consumes a generated, validated resolution
> (`qiven_workspace_require`) and performs no repository discovery or
> revision selection (WG-1/WG-4). Until a dependency class passes its
> own WR cutover, everything below remains the valid, in-force
> mechanism. After the WR-0 census begins, no NEW consumer-local
> resolver or pin may be added except as a recorded emergency
> compatibility exception with a removal trigger. Landing doc:
> `../design/workspace-resolution.md`; program documents: qiven-docs
> `accepted/2026-09-24/`.

## 1. The one consumption pattern

External code enters a consumer build in exactly ONE way:

```cmake
# --- <name>: workspace-resolved provider root (fail-closed, ADR-0052)
# configure runs through the workspace bootstrap (gate-configure), which
# sets QIVEN_RESOLUTION_FILE; the adapter emits the identity-checked
# provider roots. The consumer declares the edge in .qiven/dependencies.json
# (kind first-party-source or third-party-singleton) and never resolves
# siblings or pins SHAs itself.
if(NOT DEFINED ENV{QIVEN_RESOLUTION_FILE})
    message(FATAL_ERROR "configure through the workspace bootstrap, not a bare cmake invocation")
endif()
include("$ENV{QIVEN_RESOLUTION_FILE}")

# --- first-party source providers materialize through the adapter guard
qiven_workspace_materialize(<name>)
target_link_libraries(<consumer-target> ... qiven::<name>)

# --- consumed third-party packages: per-package add_subdirectory WITHOUT
# directory-level EXCLUDE_FROM_ALL (the LNK1104 law; never route these
# through the materialize() helper)
add_subdirectory("${QIVEN_WORKSPACE_PROVIDER_ROOT_<name>}/packages/<pkg>"
                 "${CMAKE_BINARY_DIR}/tp/<pkg>")
```

Precedence: the workspace lock node (selected once, advanced by a lock
transaction). NEVER a system path, NEVER `CMAKE_PREFIX_PATH` discovery
for governed targets, NEVER an in-repo copy of the external tree, NEVER
a consumer-local SHA pin (retired at WR-3/WR-4/WR-5).

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
5. **Pins are the workspace lock nodes (WR-3/WR-4/WR-5 shape).** Every
   governed external is selected once in the workspace lock and
   identity-checked at configure/consumption; consumer-local SHA pins
   are retired. Moving a node is a lock transaction with full gates.
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
| `qiven-foundation` | first-party layer (source) | `QIVEN_RESOLUTION_FILE` (workspace adapter, WR-3) | workspace lock node | runtime, draft, math |
| `qiven-context-draft` | frozen semantic library (source) | `QIVEN_RESOLUTION_FILE` (workspace adapter, WR-4) | workspace lock node | runtime |
| `qiven-toolchain-win` | pinned executables (env layer) | locator only (`QIVEN_TOOLCHAIN_ROOT`/sibling); revision from WorkspaceGeneration (WR-5) | workspace lock node, identity-checked at consumption | all builds via check-toolchain |
| `qiven-third-party-win` | third-party singleton | `QIVEN_RESOLUTION_FILE` (workspace adapter, WR-5) | workspace lock node, selected once | runtime (sqlite3) |
| `qiven-devkit` | tool/standards package | `QIVEN_DEVKIT_ROOT` | shim+pin where consumed (ADR-0046 D2; WR-6 target) | context (operator shim), runtime (deploy shim) |

New externals append here in the same batch that adds them.
