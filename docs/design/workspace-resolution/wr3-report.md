# WR-3 Report — Foundation Graph Migration (batch 1, shadow transition)

Status: delivered under the owner's WR-3 start instruction (v28,
2026-09-25, long-running mode, delegated per-batch H2). Batch budget
(declared at start, this file): ≤3 devkit PRs / ≤2 commits per C++
repository / 1 control lock transaction (+batch-consistency advances)
/ 1 session. Delivered: 1 devkit PR series (branch, 6 commits
(5 code + report)),
1 commit per C++ repository (+1 runtime companion draft re-pin), 1
lock transaction + 5 batch-consistency control commits. Within budget.

## What landed

| Where | What |
| --- | --- |
| qiven-devkit `tools/workspace_resolver.py` (+tests R16-R21) | per-node revision overlays (§5.1 WR-3 form: distinct effective generation, order-independent, identity-preserving no-op overlays); `adapter` operation (deterministic CMake resolution file; materialize-once guard; anti-spoof target check; operation-closure-only materialization); `lock-update` (cutover transaction helper; digest+blob-bound control-side declaration cache — full-graph validation with no checkout of every node, Profile A/I) |
| qiven-workspace `bootstrap/qiven-bootstrap.py` | `gate-configure`: identity-check locked Devkit → resolver adapter → `cmake --preset` with QIVEN_RESOLUTION_FILE (architecture §4: CMake receives resolved roots; preflight CLI form unchanged, B1-B6 contract intact) |
| qiven-foundation | `.qiven/dependencies.json` (provides `qiven-foundation-v1` → `qiven::foundation`) |
| qiven-runtime / qiven-context-draft / qiven-math | repository-owned manifests; CMake Foundation blocks (sibling discovery + consumer-local SHA pin + `if(NOT TARGET)` suppression guard) REPLACED by adapter include + `qiven_workspace_materialize`; gate configure tasks rerouted through the bootstrap |
| qiven-workspace control | lock transaction: the four nodes move to repository-manifest declarations (cache under `declarations/`); qiven-devkit node advances (census declaration, WR-1 precedent); generation `sha256:9d7cc02d…` at control HEAD `fcfede8` (transaction `f68ffcb` wrote `b5b22c5c…`; devkit-node batch advances followed) |

## Gate receipts (all PASS at exact branch heads)

- qiven-math `b00db8c` (PILOT: first workspace-resolved C++ build)
- qiven-foundation `4b66acc` (provider; plain gate)
- qiven-context-draft `a007837` (workspace adapter path)
- qiven-runtime `0b65600` (NESTED: foundation via adapter + draft via
  legacy pin a007837 + third-party via legacy pin — coexistence proof)
- qiven-devkit `bb582e8` (resolver + tests; gate:local PASS)

## Exit-criteria mapping (doc 02 WR-3)

1. *No active consumer-local Foundation SHA; migrated edges have no
   shadow-only census origin* — DELIVERED (grep-clean on the consumer
   CMake resolution surface only; repo-wide residue remains — qiven-math
   ci.yml raw `-DQIVEN_FOUNDATION_ROOT=` entries and a
   qiven-context-draft README reference — named in the CI open row;
   lock binds repository-manifest declarations with cache).
2. *Gates pass top-level and nested via Operator gate + approved
   presets; preflight supplies the adapter through the configure
   preset* — DELIVERED locally (receipts above). The CI raw-configure
   migration is OPEN for runtime's ci.yml AND qiven-math's ci.yml raw
   `-DQIVEN_FOUNDATION_ROOT=` entries (same migration class;
   explicit-dispatch-only CI; replacement proof needs an
   owner-dispatched run — declared for the continuation batch; the
   ci.yml circularity: each must pin the post-transaction control
   revision, resolved by the routine-advance decision); the
   qiven-context-draft README reference is a docs cleanup, not CI
   migration.
3. *No unrelated target can spoof qiven::foundation* — DELIVERED
   (adapter anti-spoof guard; the `if(NOT TARGET)` suppression class
   is mechanically dead in all three consumers).
4. *Moving a compatible Foundation revision requires no consumer
   re-pin commits* — mechanics DELIVERED (this batch moved four nodes
   with ZERO foundation re-pin edits; the live Profile E movement
   demonstration is bundled with the owner admission step, next
   batch).

## Live defects found and fixed during the pilot (all by the pilot gates)

1. Adapter path materialized ALL sibling checkouts (context at main+
   tripped RevisionMismatch from OUTSIDE the closure) → graph
   validation materializes nothing beyond explicit checkouts (doc 01
   §5); providers verified exactly inside the projection.
2. Zero-delta overlays rebuilt lock nodes in a different shape →
   generation mismatch at the exact locked head → identity-preserving
   no-op overlays (already-locked checkouts keep the locked node).
3. Windows backslashes inside quoted CMake strings (`\J` invalid
   escape) → provider roots emit as posix paths.
4. Nested CMake variable names: set-side underscore ids vs
   function-side hyphenated ids expanded EMPTY → `add_subdirectory("")`
   added the CALLER into the provider binary dir → the guard function
   sanitizes internally and hard-fails on an unresolvable root.

Plus one stale-state non-defect (LNK1103 PDB corruption on the first
runtime run; clean-tree re-run green — recorded, not a code change).

## Profile J pilot measurement (sealed baseline method)

| Counter | Baseline (WR-0) | After WR-3 batch 1 |
| --- | --- | --- |
| files read to reconstruct dependency location/version | 3 consumer CMake resolution blocks | 0 (manifest+adapter carry it; grep-verified no QIVEN_FOUNDATION_* remains on the consumer CMake surface) |
| mechanical peer-pin edits per compatible movement | 4 PRs / 4 pin-edit sets / 2 wasted gates | foundation class: 0 (one lock transaction); the REMAINING draft ripple: 1 edit (WR-4 class, honestly counted) |
| lock updates / owner interventions / elapsed | 4 lock-equivalent updates / 0 / ~2h10m | 6 control commits (1 transaction + 5 batch-internal devkit-version advances; collapse to 1-2 once the devkit branch merges + routine-advance rule lands) / 0 interventions / ~3h for the full four-repo pilot |
| distinct resolver implementations | 7 | 4 (3 CMake foundation resolvers deleted; bootstrap+resolver, 2 toolchain.py copies, context shim remain for WR-5/6) |
| dependency-topology explanation tokens in a task brief | n/a | ~0 for the math+draft implement brief (manifest paths + adapter semantics sufficed) — proxy observation |
| dependency-resolution mistakes found in review | baseline class #3 (target-presence suppression) | mechanically dead (anti-spoof guard + guards deleted) |

Counters 1 and 5 are proxy observations (a sealed before/after task
pair remains the acceptance-grade method); counters 2-4 and 6 are
machine-checkable and recorded above.

## Honest scope statements

- Shadow transition: all receipts are mode=shadow (labeled). The
  AUTHORITATIVE cutover claim awaits the owner admission of the new
  control revision (trust policy law clause 3) — the standing
  BaselineConflict (context devkit pin d1d2a3a vs lock 06cf75f) is the
  WR-6 reconciliation target and is reported, not resolved.
- The census file itself is untouched (WR-0 evidence; hard-removed at
  WR-8). "Retiring the shadow-only census records for these edges" is
  realized as: the lock no longer binds census declarations for the
  four migrated nodes.
- runtime's draft re-pin (ea9af72 → a007837) is a WR-4-class ripple
  that rode this batch out of necessity (the draft tree moved); it is
  the LAST foundation-adjacent ripple.
- The context lock node (8914cef) is stale against context main
  (5dadc57+) — disclosed; not needed by any gate in this batch; next
  control movement can advance it (WR-1 precedent class).
- Router classification of the new launcher forms: `qiven-bootstrap.py
  gate-configure` wraps a build-class command — sessions must not type
  it raw; classified-allow today (pre-existing v4.1 scope limit, same
  class as the recorded path-prefix finding; follow-up router batch).
