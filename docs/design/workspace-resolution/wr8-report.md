# WR-8 report — Legacy removal and enforcement

Date: 2026-09-28 (v43 window, long-running mode, delegated per-batch H2).
Stage law: ADR-0052 decision 6; normative scope qiven-docs
`accepted/2026-09-24/02-*` §7 WR-8 (:222-238); ADR-0058 E7.4 carries the
propagation-measurement duty.

## Delivered

- **Census retirement**: the qiven-docs repository manifest
  (`.qiven/dependencies.json` at docs main `4b6f22f`) ends the LAST
  census-wr0 shadow binding — the lock graph carries ZERO shadow-only
  declarations (verified by node scan at control `c4dc4a9`). The
  `census/wr0-declarations.json` file was subsequently REMOVED at owner
  direction (2026-09-28, control `cfcd793`) once no tool read it and no
  lock declaration referenced it — git history retains the sealed WR-0
  record.
- **The forbidden resolver-pattern gate** (devkit
  `tools/check_resolver_patterns.py`, wired into gate:local as
  `resolver-patterns` + `resolver-patterns-tests`, gate PASS at each
  published head): R1 CMake sibling discovery (comment-aware incl.
  multi-level bracket comments, case-insensitive), R2 config-file
  workspace pins (CMake-comment-aware; prose and banning tests exempt),
  R3 unguarded devkit sibling references in Python (path/import
  machinery adjacency + the bootstrap identity-check marker exemption),
  R4 toolchain-without-lock co-occurrence, R5 vendored operator copies
  outside the two documented instances. The default scan covers all
  eight workspace repositories. P1-P6 self-test rows.
- **The forbidden class removed from the live tree** (found by the
  gate's first live run — the pre-WR-5 shapes had survived in the
  non-build repos): foundation's operator toolchain locator,
  math's and draft's `tools/toolchain.py` were raw sibling locators
  without the lock identity check — all three upgraded to the WR-5
  lock-bound shape with typed failures (foundation `b3d4225`, math
  `6410421`, draft `faf3688`; gates PASS).
- **The routine-advance rule MECHANIZED** in the resolver
  (`_routine_advance_admissible`): a control commit whose diff from the
  closest admitted ancestor touches only `workspace.lock.json` +
  `declarations/*.json`, with a SEMANTIC lock comparison (node set
  invariant; per node only commit/tree + declaration path/blob/digest
  may change; tree/declaration changes require that node's commit to
  move; all other fields identical; ≥1 node moved; top-level fields
  symmetric-invariant except generation) auto-admits with a truthful
  receipt note. The admitted-list chase (E7.4's first finding: policy
  recording structurally lags control advances because the policy file
  lives in qiven-context) is dead for pure advances — origin flips,
  cache swaps without node moves, foreign files, and malformed history
  all stay explicit-admission class. R23 suite rows (5 cases).
- **Review loop** (K=2/SL=2, qiven-fresh-review, canary
  V43-WR8-CANARY-T1 PASS, transcripts clean every round): round 1
  found 3×P2 + 6×P3 (the R3 computed-path gap, the line-filter
  auto-admission bypass, the vacuous origin-flip row — all genuine,
  all fixed and republished: devkit `1443ea7`, math `6410421`, draft
  `faf3688`, foundation `b3d4225`); round 2 found 8×P3 (zero P1/P2) —
  six fixed in the ceiling batch (devkit `2b4a7a7`), two recorded as
  residuals below. **The SL=2 ceiling FIRED (two consecutive
  revision-warranting rounds) — the default action executed: last
  findings fixed once, loop stopped, owner adjudication at closeout.**

## Exit-criteria mapping (doc 02 §WR-8 :234-238)

| Exit criterion | Evidence |
| --- | --- |
| A new repository cannot accidentally reintroduce the old architecture | the pattern gate runs in the devkit publication gate over all eight workspace repositories; every forbidden class has a typed rule + self-test row |
| No shadow-only census declaration remains in any authoritative graph | node scan at control c4dc4a9: zero shadow-only declarations; the census file is sealed history |
| One governed lock update selects a shared dependency only after provider compatibility + consumer gates | the lock-update transaction validates candidate content before commit (WR-3 law, unchanged); the auto-admission shape rule mechanically excludes non-advance graph edits |
| Active repository gates pass | gate:local PASS at every published head this batch (devkit 2b4a7a-lineage, foundation b3d4225, math 6410421, draft faf3688); the non-Windows CI question does not arise (the workspace CI units are Windows-bound; no authoritative non-Windows job exists to relabel) |

E7.4 propagation measurement (ADR-0058 d5, this window's data): 13
context/devkit publications produced 13 same-window lock advances
(e279fab→690f0d2 chain), minutes of latency each, ZERO manual owner
interventions; the admitted-list recording lag is now structurally
harmless (pure advances auto-admit mechanically). Formal measurement
continues if the owner directs more windows.

## Honest residuals

- **R3/R4 disarm-by-marker** (round-2 F5, intent-level): the identity
  marker and lock co-occurrence are file-level heuristics — a bare
  "bootstrap" comment or a `# see workspace.lock.json` comment disarms
  them; constructed-name path building (`"qiven-" + "devkit"`) evades
  R3/R4 entirely. The gate is a reintroduction tripwire, not a
  sandbox; the WR-6 launcher contract tests and the lock-bound
  toolchain checks carry the enforcement weight.
- **Move-plus-cache-swap** (round-2 F7, contract-sanctioned boundary):
  a single control commit that moves a node AND rewrites its
  declarations cache can change effective graph semantics under
  auto-admission when no checkout is materialized (with checkouts, the
  digest-vs-repo-manifest check fails closed — the real activation
  path always has checkouts). The class is bounded by the one-committer
  workspace reality; a future multi-committer regime should require
  checkouts for admission.
- **Kit-payload absolute locators**: h1_kit.py references the devkit
  router by absolute machine path in generated kit payloads —
  build-time pinned, not an import fallback; recorded as the kit
  consolidation question with the workspace-root launcher follow-up.
- **Operator-instance consolidation**: runtime/foundation carry full
  operator instances (documented R5 exceptions) — the workspace-root
  launcher consolidation remains the recorded post-window item
  (wr6-report residual, unchanged).
- Unreadable-file skip + UTF-16 blindness in the pattern scanner
  (round-2 note): low realism, recorded.
