# Third-Party Dependency Standard

This document is the SINGLE CANONICAL rule set for consuming third-party
open-source code in any `qiven-*` repository (ADR-0046: Devkit owns
engineering standards; repositories carry no copies). It exists to keep
every workspace build **hermetic, reproducible, auditable and clean**:
a fresh clone plus the workspace layout must build without global
package managers, system-wide installs, or any path outside the
workspace.

Owner constraints this standard enforces (2026-09-23 direction):
no workspace pollution; local builds MUST NOT depend on any path
outside the workspace; discovery, CMake consumption and compile-flag
adaptation must be specified completely; acquisition (download /
git clone) is a long-running command class routed through the Qiven
Operator (hang contract).

## 1. Decision rule: which consumption mode

| Mode | Mechanism | When allowed | Default? |
| --- | --- | --- | --- |
| M1 **vendored source** | pinned source tree committed under `third_party/<name>/` | always allowed | **YES** |
| M2 **fetched source** | CMake `FetchContent` with pinned URL + SHA-256 | only when M1 is impractical (huge trees) AND network-at-configure is acceptable for the repo's profile; the pin manifest still lives in-repo | no |
| M3 **prebuilt binary** | digest-pinned binary committed under `third_party/<name>/bin/` | only when source build is genuinely impractical (vendor toolchains, closed SDKs) — needs an explicit justification line in the provenance file | no |

Rules:

- M1 is the default for everything the MVP consumes (SQLite is M1).
- M2/M3 require a one-line justification in the provenance file AND a
  recorded fallback plan (how to switch to M1 when the network or the
  vendor disappears).
- **Style/whitespace gates exclude `third_party/`** (format-check,
  diff-check): upstream content is pristine under provenance digests and
  is never reformatted or style-gated; its integrity law is §4, not the
  first-party style gates. Repositories configure their gates with an
  explicit pathspec exclude (recorded in their operator policy).
- **Discovery hermeticism corollary**: `*.patch`/`*.lib`/`*.exe` global
  gitignore patterns MUST be negated for `third_party/**` where those
  file classes are vendored content (patches §6; prebuilt M3).
- **Discovery hermeticity (hard rule)**: governed third-party code is
  discovered ONLY inside the workspace. `find_package(<name>)` that can
  silently bind a system copy (vcpkg root, `CMAKE_PREFIX_PATH`,
  `PATH`-installed libraries, `C:/Program Files`, home directories) is
  FORBIDDEN for governed dependencies. If `find_package` is used at
  all, it must be called with an explicit `<name>_ROOT` cache variable
  that defaults to the in-repo `third_party/` location and
  `NO_DEFAULT_PATH`, so a system copy can never satisfy it silently.
  A build that depends on a path outside the workspace is a defect,
  not a convenience.
- OS-provided system libraries (Win32 API, CRT, DPAPI, WMI …) are NOT
  third-party dependencies; use them directly.

## 2. On-disk layout (M1/M3)

```text
third_party/<name>/
  README.md            what it is, why it is here, which repo slot uses it
  PROVENANCE.yaml      the pin record (§3) — machine-checked
  LICENSE              the upstream license text, verbatim
  include/ src/        the pinned source (amalgamations may be flat)
  patches/*.patch      unified diffs applied on top of the pinned source
                       (empty by default; see §6)
```

`third_party/` is committed source (NOT gitignored, NOT under
`.generated-temp/` — it is input, not generated output). Build outputs
from compiling it land in the normal `build/` tree, never inside
`third_party/`.

Repositories add `third_party/` only when they actually carry a
dependency; it is absent otherwise (filesystem conventions updated
accordingly).

## 3. PROVENANCE.yaml — the pin record (machine-checked)

```yaml
schema: qiven-third-party-provenance-v1
name: sqlite3
version: 3.50.4            # upstream version string
mode: vendored-source      # vendored-source | fetched-source | prebuilt
source_url: https://sqlite.org/2025/sqlite-amalgamation-3500400.zip
source_revision: ''        # git commit when cloned; '' for archive
acquired_at: '2026-09-23'
archive_digest:                 # the digest upstream PUBLISHES, with its algorithm
  algorithm: sha3-256           # (sqlite.org publishes SHA3-256; others may be sha256)
  value: <hex>
files:                     # sha256 of every committed file under the tree
  - path: sqlite3.c
    sha256: <...>
  - path: sqlite3.h
    sha256: <...>
patches: []                # list of patches/*.patch applied (§6)
justification: ''          # required for M2/M3; empty for M1
consumers: [qiven-runtime journal subsystem]
license: Public Domain (sqlite3) / <SPDX or verbatim name>
```

Rules:

- The `files` list covers every file except `PROVENANCE.yaml` itself,
  `patches/` (which carry their own digests inside the record) and the
  repo-owned `CMakeLists.txt` build glue (consumption law §5, not
  upstream content).
- Any edit to a vendored file (including re-vendoring a new version)
  MUST update `PROVENANCE.yaml` in the same commit — the verifier (§4)
  fails the gate otherwise. There is no such thing as an untracked
  local modification to a vendored tree.
- Upstream version bumps are their own batch: new archive digest, new
  file digests, changelog note in README.md, full gates.

## 4. Verification — `third-party-verify` gate task

Each repository carrying `third_party/` defines an operator task
`third-party-verify` (argv to a small repo-local or Devkit-provided
checker) that:

1. parses every `PROVENANCE.yaml`;
2. recomputes the SHA-256 of every listed file (constant-time compare);
3. verifies declared patches are present and apply cleanly to the
   recorded pre-image (patches list is authoritative);
4. exits non-zero on ANY mismatch, naming the file and expected digest.

The task is part of the repo's default gate (before configure), so a
tampered or accidentally-edited vendored file fails closed before any
build. Failing the verifier is never "comment out the digest" — it is
investigate, re-vendor deliberately, or restore.

## 5. CMake consumption law

1. **Namespace**: every third-party target is
   `qiven::tp::<name>` (e.g. `qiven::tp::sqlite3`) — never the
   upstream's own target name leaking into first-party CMake, never an
   un-namespaced `sqlite3` target.
2. **Scope**: `add_subdirectory(third_party/<name>)` WITHOUT
   directory-level `EXCLUDE_FROM_ALL`. Verified 2026-09-23 (SQLite
   landing): the Visual Studio generator drops the consuming
   ProjectReference under directory-level EXCLUDE_FROM_ALL, leaving a
   link-line-only reference that fails LNK1104 — so third-party targets
   joining the `all` build is the accepted, reliable cost (seconds),
   grouped under the `ThirdParty` solution folder. A not-linked
   third-party target (none today) may set the target-level
   EXCLUDE_FROM_ALL property.
3. **Interface hygiene**: usage requirements
   (`target_include_directories`/`target_compile_definitions` needed by
   consumers) are PUBLIC on the third-party target itself; everything
   else is PRIVATE. Consumers link the target and never add vendored
   include paths of their own.
4. **Compile-flag adaptation (contained, never global)**:
   - First-party warning laws (`/W4 /permissive- /utf-8`, or the GCC/
     Clang equivalents) DO NOT propagate into third-party targets —
     they are stripped by setting the third-party target's own options
     (`/W3` default; `/W0` permitted for amalgamations where upstream
     warnings are out of scope), applied on THAT target only.
   - Suppression defines the upstream requires (e.g.
     `_CRT_SECURE_NO_WARNINGS` for sqlite3) are set via
     `target_compile_definitions(<tp-target> PRIVATE …)` — PRIVATE,
     never directory-scope, never global.
   - Feature macros that change the ABI/behavior the repository depends
     on (e.g. `SQLITE_THREADSAFE=1`, `SQLITE_OMIT_LOAD_EXTENSION`) are
     PRIVATE on the third-party target and documented in its README.md.
   - Runtime-library selection (CRT `/MD` vs `/MT`), exception model
     and sanitizer flags MUST match first-party targets (they do by
     default: MSVC defaults are consistent per-configuration; do not
     override on one side only).
   - Precompiled headers are DISABLED on third-party targets
     (`DISABLE_PRECOMPILE_HEADERS ON`).
   - Forbidden mechanisms for adaptation: `add_definitions`,
     `add_compile_options`, `link_libraries`, `include_directories`,
     `CMAKE_CXX_FLAGS` mutation — all global-scope pollution.
5. **No network at configure** for M1 repositories: configure must
   succeed with networking disabled. (M2 repositories declare the
   opposite explicitly and are currently none.)
6. **Pinned tools are not third-party**: cmake/clang-format pins live
   in `qiven-toolchain-win` (environment layer, ADR-0046) and are out
   of scope here.

## 6. Patch policy

- Default: pristine vendored trees (`patches: []`).
- When a patch is unavoidable (upstream defect blocking a gate):
  1. the unified diff lives at `patches/<nn>-<slug>.patch`;
  2. `PROVENANCE.yaml` lists it with its sha256;
  3. README.md records why it exists and the upstream tracker link;
  4. every patch has a removal plan (upstream release that includes
     it); patches older than two upstream releases get re-reviewed.
- Amalgamation edits follow the same rule via `files` digests plus a
  `patches/` note describing the edit (the diff of the amalgamation
  itself is the committed file's digest change, documented in README).

## 7. License compliance

- The LICENSE file is vendored verbatim; `PROVENANCE.yaml` names it.
- Permissive licenses (MIT/BSD/Apache-2/Public Domain) are acceptable
- Copyleft (GPL/AGPL family) is FORBIDDEN for linked code in this
  workspace without an explicit owner decision recorded in an ADR.
- Deployment bundles must carry every third-party license (deployment
  standard references this file).

## 8. Acquisition procedure (long-command discipline)

Downloads, `git clone`, archive extraction and any acquisition command
are **long-class commands**: they are invoked through the Qiven
Operator (`qiven exec start --timeout <s> -- <cmd> …`, hang-contract
rule 5 — the hook router enforces this for raw invocations). The
acquisition session MUST:

1. record the upstream URL and archive digest in PROVENANCE.yaml;
2. extract into a scratch dir under `.generated-temp/`;
3. copy ONLY the needed source/license into `third_party/<name>/`
   (no docs bloat, no test suites of the dependency unless vendored
   deliberately);
4. generate the `files` digest list mechanically (never hand-typed);
5. run `third-party-verify` before committing.

## 9. Relation to other standards

- `implementation-standard.md` §dependency: this file is the
  operational expansion for third-party code; the minimal-abstraction
  rule still decides WHETHER to take a dependency at all.
- `deployment.md`: bundles ship `licenses/` from these provenance
  records.
- `design-first-workflow.md`: adding a dependency requires a design
  slot (e.g. the C++ design's third-party table) BEFORE the vendoring
  batch.

## Review record

Self-review 2026-09-23 (pre-publication):

1. M2 FetchContent currently unused — kept in the table with a
   network-at-configure disclaimer rather than banned: banning a mode
   we may need for huge trees would invite workaround; the default and
   the hermeticity rule carry the intent.
2. `find_package` not banned outright (some vendor SDKs only package
   that way) but hermetic-call shape pinned (explicit ROOT default to
   in-repo location + NO_DEFAULT_PATH).
3. Patch verification "applies cleanly to the recorded pre-image"
   requires storing pre-image digests implicitly via the patch's own
   sha256 + the current tree; kept simple (patch digest + apply-check)
   — full pre-image reconstruction is over-engineering for the current
   zero-patch state; revisited when the first patch lands.
4. Windows-only CRT/sanitizer wording kept general enough for the
   future Clang/GCC port while naming the MSVC specifics we use today.
