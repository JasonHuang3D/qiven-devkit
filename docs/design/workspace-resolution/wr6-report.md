# WR-6 report — Devkit Operator migration

Date: 2026-09-28 (v42 session, long-running mode, delegated per-batch
H2). Stage law: ADR-0052 decision 6; normative scope qiven-docs
`accepted/2026-09-24/02-*` §7 WR-6 (launcher rules :200-205; managed-
copy retirement precondition :207; exits :211-214).

## Delivered

- **Devkit repository manifest + operator reporting** (devkit
  `2992d8d`, gate:local PASS): `.qiven/dependencies.json` declares the
  operator-v2 and resolver-v1 contracts repository-owned — the
  census-wr0 shadow binding on the devkit node ENDS at this revision.
  Every operator `info` and `gate` payload now carries
  `workspace_generation`, `devkit_node` and `workspace_mode`
  (standalone labeled honestly when no workspace lock resolves at the
  control locator); reporting is evidence, revision enforcement stays
  in the launcher's bootstrap identity-check.
- **Lock transaction** (control `3f02af6`): the devkit node moved
  `bfdb4c1` → `2992d8d` binding the repository-manifest declaration —
  the standing lock-devkit-node split is reconciled. A consistency
  conform (`6503288`) then aligned the foundation/runtime/third-party/
  toolchain nodes to their published merge heads, and math/draft nodes
  advanced to their retirement heads (`18d9303`).
- **Context launcher** (context `22c8926`, gate:context-tools PASS
  THROUGH the launcher): `tools/qiven.py` identifies the repository
  (`QIVEN_TARGET_ROOT`) and the control checkout
  (`QIVEN_WORKSPACE_CONTROL` or the sibling locator), runs the
  bootstrap's preflight identity-check BEFORE any Devkit import, and
  contains no path fallback and no pin. The `QIVEN_DEVKIT_ROOT` →
  sibling → import chain and the consumer-local `devkit_pin`
  (`d1d2a3a` — the standing BaselineConflict's live half) are DELETED.
  A cold-boot contract test pins the launcher shape (bootstrap
  invocation, no fallback, no pin).
- **Managed-copy retirement** (math `a7227e8`, draft `6b9b756`; both
  gates PASS through their new launchers with the vendored operators
  DELETED): the drifted 1746-line operator copies are gone — the
  lock's devkit node is the single operator implementation.

## Exit-criteria mapping (doc 02 §WR-6)

| Exit criterion | Evidence |
| --- | --- |
| The Context-specific QIVEN_DEVKIT_ROOT → sibling → import path is no longer normal | the chain is deleted from context's launcher; the bootstrap identity-check (commit+tree vs the lock node) precedes every import |
| Every Operator invocation reports WorkspaceGeneration and exact Devkit node | EVERY payload-producing command reports (info, gate, run, ci start, exec start, exec status) — the fields are workspace_generation, devkit_node (the LOCK's selection), devkit_head (the checkout actually executing) and devkit_drift (explicit when they differ) |
| Wrong local Devkit revision fails before Operator code executes | the launcher runs the bootstrap preflight (identity-check) before `importlib.import_module`; evidence-live this window — twice the bootstrap rejected a moved devkit checkout with the typed `BootstrapDevkitMismatch` before any operator code ran; the launcher also SURFACES the preflight's bootstrap_notes (a dirty-devkit shadow label is printed, never swallowed) |
| Template version drift can no longer silently select an older Operator | the managed operator copies (math, draft — each silently running a 215-line-older operator) are RETIRED; the lock's devkit node is the single implementation those repositories execute; runtime/foundation carry their own operator instances (repository-owned tooling predating the managed-template class — recorded as the post-window consolidation question with the workspace-root launcher, not claimed retired here); devkit_drift makes checkout-vs-lock divergence explicit in every payload |

Launcher-rule compliance (:200-205): identifies repo + workspace ✓;
invokes bootstrap ✓; no Devkit path fallback ✓; no consumer-local
Devkit pin ✓ (the pin deletion also kills the live half of the
standing context→devkit BaselineConflict).

## Honest residuals

- **CI posture** (the :207 precondition "bootstrap path works in both
  local development and CI"): local proofs are fresh (every gate in
  this batch ran through a launcher or the bootstrap). CI does not
  invoke the operator layer at all — the runtime/math CI units call
  the workspace bootstrap directly for configure/build/test and have
  run green on that path since v29/v31; a fresh in-session-dispatched
  run at the WR-5-bumped snapshot closes the CI leg freshly (receipt
  recorded in the session checkpoint). The operator-layer entry point
  (launcher) is CI-unexercised because CI never runs operators —
  disclosed; the workspace-root launcher is the post-window
  consolidation point.
- **Lock-state currency**: this report cites lock transactions by their
  control commits (`3f02af6` devkit-node transaction, `6503288`
  published-head conform, `18d9303` math/draft advances, `7990ed2`
  devkit report-head advance) rather than by generation literals — the
  generation moves with every intra-batch transaction; the reviewed
  state is the control HEAD at review time.
- **The census-reported BaselineConflict note persists**: the context
  node's census-wr0 declaration still carries the legacy_consumer_pin
  note describing the (now-deleted) pin; the resolver reports the
  conflict until the context node gains a repository-manifest
  declaration — the WR-8 "no shadow-only census remains" class. The
  LIVE pin is gone; the recorded note is history the census keeps.
- **The context lock node stays stale-below main** (f16011b < the
  published main): moving it requires the same context
  repository-manifest (descoped to WR-8 with this record).
- **Launcher duplication**: context/math/draft each carry the ~60-line
  launcher (the compatibility-window shape the spec names); the
  workspace-root launcher (`qiven-workspace/qiven.cmd`) is the
  consolidation point post-window.
- The toolchain-root logic still exists in three near-copies (the
  WR-5 recorded residual) — the operator consolidation question is
  now single-implementation at the locked devkit, but the
  toolchain.py copy in runtime/foundation remains until their next
  respective batches.
