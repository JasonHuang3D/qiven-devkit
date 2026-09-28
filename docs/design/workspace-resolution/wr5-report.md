# WR-5 report — toolchain and third-party singleton migration

Date: 2026-09-28 (v42 session, long-running mode, delegated per-batch
H2). Stage law: ADR-0052 decision 6 (one dependency class at a time
behind dual-resolution shadow proof); stage assignment
`workspace_shadow._REPLACEMENT_STAGE`; normative scope qiven-docs
`accepted/2026-09-24/02-*` §7 WR-5.

## Batch budget (declared at start, WR-3 precedent)

1 devkit docs commit (this report + registry/law updates); 1 commit per
provider repository (repository-owned dependency manifests); 1 runtime
cutover commit (declaration edge + CMake adapter consumption +
verify/toolchain rework); 1 foundation commit (toolchain copy-pair
retirement); batch-internal lock shadow advances with receipts; the
batch-exit review loop (K=2/StandingLaw=2); publication bottom-up.
Stall law on failed exit.

## Delivered

- **Provider manifests**: qiven-third-party-win `e45361a` and
  qiven-toolchain-win `a62f7b9` each carry `.qiven/dependencies.json`
  (the census-sealed declaration content, now repository-owned); both
  lock nodes moved census-wr0 → repository-manifest origin through
  lock-update transactions (batch-internal shadow advances
  `e6d13bc`/`42d5597`/`556c6fa`).
- **Third-party cutover (runtime `86b790c`)**: the
  `third-party-singleton` edge is declared; CMake consumes the
  adapter-emitted provider root (selected once in the lock) with
  per-package consumption WITHOUT directory-level `EXCLUDE_FROM_ALL`
  (the LNK1104 law — the materialize() helper's provider shape is
  deliberately not applied to consumed externals). The consumer-local
  `QIVEN_THIRD_PARTY_ROOT` cache resolution and the exact-SHA
  `QIVEN_THIRD_PARTY_PIN` + configure rev-parse check are RETIRED.
  `third-party-verify` now verifies the singleton HEAD against the
  LOCKED node commit (control locator `QIVEN_WORKSPACE_CONTROL` or
  sibling) and keeps the provenance-digest half unchanged.
- **Toolchain from WorkspaceGeneration (runtime `86b790c`, foundation
  `dcabe78`)**: `tools/toolchain.py` and the operator's `_toolchain()`
  (gate-task `{cmake}`/`{ctest}` expansion) resolve the root as a
  LOCATOR (env `QIVEN_TOOLCHAIN_ROOT`/sibling) but take the selected
  REVISION from the locked `qiven-toolchain-win` node,
  identity-checked before any expansion; `toolchain.json` remains the
  authoritative executable inventory inside the selected node. The
  foundation copy-pair carries the identical rework (the duplicated
  sibling-root logic no longer selects a revision anywhere).
- **Docs**: cross-repo-cmake.md registry rows updated to the
  post-WR-3/4/5 shapes (foundation/draft rows were stale);
  third-party-dependencies.md §5 consumption law rewritten to the
  WR-5 shape (this commit).

## Gates (exact heads, receipts via gate:local PASS)

- qiven-runtime `86b790c`: gate:local PASS (check-toolchain and
  third-party-verify now ride the lock-identity paths; configure rides
  the adapter-emitted third-party root; all suites + h1-sim green).
- qiven-foundation `dcabe78`: gate:local PASS.
- qiven-third-party-win `e45361a`: gate.cmd PASS (provenance +
  configure-smoke).
- qiven-toolchain-win: no gate of its own (census note); consumer
  check-toolchain at the locked revision is the proof.

## Exit-criteria mapping (doc 02 §7 WR-5)

| Exit criterion | Evidence |
| --- | --- |
| Toolchain or third-party workspace location changes require no consumer source edit | roots come from the lock/adapter (third-party) and the locked node (toolchain); locator overrides remain optional paths, never revision selectors |
| No governed dependency resolves from PATH/system package discovery | find_package ban + adapter roots (third-party); toolchain revision identity-checked against the lock before expansion |
| Configure remains offline | adapter/lock reads are local JSON + git rev-parse; no network on any new path |
| Toolchain: remove duplicated sibling-root logic as the normal path | both copies (runtime + foundation) now take the revision from the lock |
| Toolchain: root from WorkspaceGeneration | `_toolchain()` / `toolchain_root()` read the locked node commit |
| Toolchain: toolchain.json stays the authoritative inventory | unchanged role, now inside the identity-checked selected node |
| Third-party: selected once in the workspace lock | the lock node is the only pin; no consumer-local SHA remains |
| Third-party: package provenance + CMake targets preserved | PROVENANCE digests verified by the singleton gate + consumer spot-verification; per-package add_subdirectory unchanged |
| Third-party: remove per-consumer singleton revision selection | the pin block and its configure check are retired |

## Honest residuals

- **CI toolchain**: the windows unit's bootstrap receives `--cmake cmake`
  (the RUNNER's cmake), not the locked toolchain-win executable set —
  a pre-existing CI-infrastructure shape, not a workspace-graph edge;
  a future batch may checkout toolchain-win in CI and pass its cmake.
  Recorded, not fixed here.
- **CI snapshot**: the ci.yml pinned control/node refs ride a
  self-consistent admitted snapshot; the WR-5 transaction makes them
  stale by design — the windows-unit refs are bumped in the publication
  step and the replacement proof remains an owner-dispatched run (the
  standing WR-3-era open row).
- **Devkit managed-repo operator copies** (math/draft template ripples)
  consume toolchain via the devkit template's own resolution — WR-6
  (operator migration) consolidates operator discovery; not reworked
  here.
- **The standing lock-devkit-node split** (lock node `bfdb4c1` vs devkit
  main) and the context→devkit pin BaselineConflict are unchanged WR-6
  targets. The devkit lock node cannot move to the schema-registration
  head (typed `MissingDeclaration`: no `.qiven/dependencies.json` in
  devkit) — the WR-6 disposition.
- **Trust-policy array currency** (R4): the policy file's admitted/
  routine arrays end at `046cbee`; the recording duty for later control
  revisions rides session checkpoints (v28-v42). Reconciling the file
  is an owner-visible governance write, deliberately not done inside
  this engineering batch.
