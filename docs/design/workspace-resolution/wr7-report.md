# WR-7 report — TCA source-selector migration

Date: 2026-09-28 (v42 engineering leg + v43 completion window, long-running
mode, delegated per-batch H2). Stage law: ADR-0052 decision 3; normative
scope qiven-docs `accepted/2026-09-24/02-*` §7 WR-7 (:208-220); the
governance amendment vehicle is qiven-context `decisions/ADR-0058.md`.

## The cutover EXECUTED (H1#2 accepted 2026-09-28)

The owner accepted the cutover (AskUserQuestion, "接受+立即切换（推荐）")
on the green receipt at generation `28b0a163`. The runtime cutover batch
landed and published (runtime main `085c58d` through `0d4f286`/`bdc428f`/
`c4b0c95`; gate:local PASS at each substantive head):

- **The selector gate**: `index rebuild` now REQUIRES `--workspace-lock`
  and fails closed unless the freshly built closure is cutover-grade
  equal to the workspace selection (tier-1 + tier-2, no shadow-only
  node). Live-proven BOTH ways at the published head: the stale-lock
  fixture (context node reverted to f16011b — the v42 RED class)
  reproduces the typed failure (StaleNode + FilterSetMismatch rows,
  exit 1); the real lock passes the gate AND completes the first full
  live index build through it (ActivationGeneration
  `2b41f1ce…`, 367 sources, 19 rules, exit 0).
- **Provenance (ADR-0058 d6)**: the parent WorkspaceGeneration rides a
  per-generation sidecar `workspace-provenance.json` (written on build,
  refreshed on content-identical reuse) — NEVER in index-manifest.json
  (byte-finality untouched, verified 0 occurrences) and never in any
  digest (ActivationGeneration unchanged by provenance, test-pinned).
  `cognition activate` validates the axis against the sidecar; receipts
  carry it in the envelope (journal column lazily migrated; legacy loads
  read honest empty).
- **A real design-contract defect found and fixed by the live proof**:
  the canonical policy's P4-on-demand rule (qiven-docs deliberation
  reference) could never satisfy the closure-containment law — the CA-1
  design says P4 records "enter ONLY when a P4 rule references them;
  the path filter stays closed", i.e. out-of-closure BY DESIGN. The
  containment law now binds P0-P3 only; a P4 out-of-closure source is an
  on-demand reference riding the digest-bound policy table, never a
  fabricated closure row (regression row in tests/activation_index.cpp).
- **Diagnostics law**: `index rebuild` names the failing rule source /
  duplicate rule id before the typed fault (the lock-update
  failing-repository probe's sibling).

Terminal state: comparator green at generation `9364bdff` (context
`465402c` / devkit `ae3b470` / foundation `6906ea1` / runtime `085c58d`,
all repository-manifest); control chain e279fab → 9662cde → 51c6ec8 →
32b0326 → 35b2edd → 5e937bd → 9142074 → fac899e (the E7.1 same-window
cadence exercised live: every publication → one lock advance, minutes of
latency, zero manual interventions; the admitted-list chase is batched
per the ratified auto-admission rule — the WR-8 mechanization
candidate).

## Delivered

- **The TCA shadow comparator** (v42, runtime main `6b884a0` / head
  `9a0149e`): `runtimectl index shadow-compare --core <cognition-core.yaml>
  --request <bindings> --workspace-lock <workspace.lock.json>` builds the
  TCA source closure fresh through the CA-1 builder (same fail-closed
  laws: exact pinned refs, clean trees, no network) and compares it
  against the WorkspaceGeneration — tier-1 per-repo (commit, root tree)
  equality, tier-2 the corpus path-filter table re-read at the workspace
  node's context (carrier) revision. Typed divergences: StaleNode /
  NodeMissing / FilterSetMismatch / ContentIdentityConflict; the
  ShadowOnlyNode annotation blocks cutover-grade on non-authoritative
  nodes; malformed/missing declarations fail closed to shadow. The
  receipt (`qiven-tca-shadow-compare-v1`) is pure and envelope-only: the
  workspace generation rides as PROVENANCE, never as an input to the
  source lock or ActivationGeneration. 10 test rows (v42 review rounds
  hardening: filter dimension, \uXXXX fail-closed JSON rejection, the
  unknown-authority cutover block).
- **The v43 completion prerequisites** (the v42 deferral record's list):
  the qiven-context repository-owned manifest
  (`.qiven/dependencies.json` at context main `2ff0b6a` — the census-wr0
  shadow binding's replacement; the declarations cache verified
  byte-equal), the context lock-node conversion (control `e279fab`,
  node -> `2ff0b6a` then routine-advanced to `976c6d7` at control
  `9662cde`), the runtime node's merge-head advance (`9a0149e` ->
  `6b884a0`), the owner-adjudicated control admission (v43 popup:
  e279fab + the 046cbee..5b606f0 v41/v42 backfill segment —
  authoritative-mode validate typed-blocked before the record, PASSED
  after), and ADR-0058 (the governance amendment + E7 cutover policy,
  proposed pending the owner H1).
- **The GREEN cutover-grade receipt** (2026-09-28, runtime checkout
  `6b884a0` built through the workspace bootstrap at generation
  `16635fbe`): `all_equal=true`, `cutover_grade=true`, all four corpus
  rows divergence=none with shadow_only_node=false —
  context `976c6d7` / devkit `3052bf3` / foundation `6906ea1` /
  runtime `6b884a0`, external_source_lock_sha256
  `b22b6320…`. Receipt archived at
  `qiven-runtime .generated-temp/wr7/receipt-green-v43.json` (bindings
  beside it; workspace log carries the run record). The v42 RED
  (context StaleNode 49-behind + shadow-only; devkit/foundation
  FilterSetMismatch) is fully resolved STRUCTURALLY — the corpus table
  exists at the carrier revision and the context node is
  repository-manifest bound.

## Exit-criteria mapping (doc 02 §WR-7 :212-220)

| Exit criterion | Evidence |
| --- | --- |
| Provenance naming (generation + tool projection as provenance; source lock + projection as content inputs) | the comparator receipt's envelope design; ADR-0058 decision 6 carries the post-cutover semantics; the runtime cutover batch (on H1 acceptance) wires `workspace_generation` into receipt envelopes |
| Movement inside the selected closure changes ActivationGeneration; outside does not | unchanged CA-1 law (source-lock digest binding); the comparator adds no digest path (envelope-only, proven by construction + the 10-row suite) |
| Old-generation rebuild/rollback without a mutable current pointer | the source lock stays self-contained (per-file digests at exact commits); ADR-0058 E7.2 |
| No TCA code reads a dirty sibling checkout as authoritative | the CA-1 builder's DirtyCheckout typed failure governs both paths; the comparator reuses the builder |
| Capability lookup binds to exact selected revisions/digests | corpus table + capability pointers at the pinned carrier revision; tier-2 proves the filters equal at the node revision |
| CA-1/CA-2 evidence and the bounded-batch stall trigger remain valid | untouched; CA-2 stays frozen (MVP-5 gate) |
| The owner-accepted cutover policy | ADR-0058 E7.1-E7.4 (drafted; H1#1 adjudicates) |

## Honest residuals

- **The admission-list chase (E7.4's first measured finding)**: the
  trust-policy admitted list lives in qiven-context, so every
  policy-recording publication moves context main, requiring another lock
  advance the stale list mechanically blocks — authoritative mode can
  only be exercised at batched catch-up points (this window: PASS at
  `e279fab`; the routine advances `9662cde`+ ride the ratified
  auto-admission rule with batched recording). The ratified rule IS the
  authority for routine-advance class; the mechanical list is a lagging
  mirror. WR-8 improvement candidate: the resolver learns the
  routine-advance diff-shape check and auto-admits mechanically.
- **Same-window lock-entry cadence**: two context publications this
  window each produced one control advance (e279fab conversion +
  9662cde routine) — minutes of latency, zero manual interventions;
  formal measurement continues through the WR-8 window (E7.4).
- **qiven-docs remains a census shadow-only node** (graph-level
  shadow_only=True) — outside the TCA corpus, no effect on the
  cutover-grade receipt; its repository manifest is the WR-8 census
  retirement item.
- The comparator run used the shadow-mode bootstrap build (the
  authoritative gate at the current control head awaits the policy
  catch-up — the chase above); the receipt itself is mode-independent
  (it reads the lock file, not the trust state), and the admission
  chain is evidenced by the e279fab authoritative probe.
- ADR-0058 remains PROPOSED until the owner H1#1; nothing in the
  selector has switched (no ACTIVE pointer moved — the comparator is
  non-mutating by law).
