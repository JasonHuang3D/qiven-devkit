# WR-0 Sealed Effort Budget for WR-1/WR-2

Status: sealed 2026-09-24 (WR-0), for owner review per ADR-0052
decision 4 and doc 02 §7.7. A breach pauses authority cutovers for an
owner continue-bounded / re-scope / abandon decision.

## Scope priced (WR-1 — schema and bootstrap, resolver read-only)

| Item | Bound |
| --- | --- |
| qiven-workspace repository skeleton (README, workspace.json, bootstrap/, qiven.cmd) | 1 commit set, ≤ 200 lines total (control-plane data only, no product semantics) |
| qiven-dependencies-v1 + qiven-workspace-v1 + lock schemas (with strict-schema + duplicate-key rejection) | ≤ 2 devkit PRs |
| standard-library bootstrap (locate root, validate lock subset, identity-check locked Devkit, preflight-only resolver release) | ≤ 1 devkit PR |
| resolver command: validate graph, emit full-graph + operation receipts, typed failures incl. UntrustedControlRevision | ≤ 2 devkit PRs (self-test included) |
| canonicalization golden vectors (RFC 8785 + domain prefix + SHA-256; two independent implementations agree) | inside the resolver PRs; no separate batch |
| WR-0 census declarations sealed into the control tree (shadow-only labels) | 1 commit |

WR-1 budget ceiling: **6 devkit PRs / 2 working sessions**.

## Scope priced (WR-2 — shadow resolution against the existing build)

| Item | Bound |
| --- | --- |
| shadow preflight before legacy CMake resolution, per-class equality receipts | ≤ 2 devkit PRs |
| legacy pin <-> workspace projection comparator with typed shadow-conflict output | inside the same PRs |
| the Profile B fixture wired as the permanent regression (must fail pre-configure, order-independent) | inside the same PRs |

WR-2 budget ceiling: **2 devkit PRs / 1 working session**.

## Stall law (ADR-0052 decision 4, verbatim application)

- Any stage missing its declared exit twice -> pause authority
  cutovers; owner decides continue-bounded / re-scope / abandon.
- Any budget breach -> same pause. Costs, evidence and residual legacy
  defects are recorded; shadow diagnostics never count as closing the
  legacy defect classes; a permanent stop records the residual and
  never relabels shadow mode as completion.

## Owner decision points this budget feeds

1. Authorize qiven-workspace repository creation (WR-1 start) — or
   direct the cheaper subset (census + fixture + baseline as Devkit
   artifacts only, already landed by WR-0).
2. After WR-2 shadow equality: authorize the first class cutover
   (WR-3 Foundation) as the Profile J pilot.

## In-force constraints reminder

ADR-0048 custody and ADR-0049 kit self-containment bind every
entrypoint this work ships; changed routed command forms re-test
router classification (ADR-0051, accepted) in the same batch; CA-1
proceeds on its own schedule untouched.
