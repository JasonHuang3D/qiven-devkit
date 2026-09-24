# WR-0 Report — Resolver Census Delivered (2026-09-24)

Status: delivered for owner review. WR-0 is complete when the owner
accepts these sealed outputs; WR-1 (qiven-workspace creation) remains
gated on that review per ADR-0052 decision 4.

## Deliverables in this batch

| Artifact | What it seals |
| --- | --- |
| `wr0-census.yaml` | every active resolver-shaped mechanism with live file:line evidence, node HEADs vs canonical main, the pin table, baseline splits, entrypoint integration surfaces |
| `wr0-profile-b-fixture.md` | the permanent conflict fixture for the target-presence validation-suppression class (+ Profile K counterexample) |
| `wr0-profile-j-baseline.md` | the sealed BEFORE measurement and the fixed after-method |
| `wr0-effort-budget.md` | WR-1 ceiling 6 devkit PRs / 2 sessions; WR-2 ceiling 2 PRs / 1 session; stall law application; the two owner decision points |

## Exit-criteria mapping (doc 02 WR-0 Exit)

1. *Every active cross-repository edge and provided contract
   represented, with a recorded supported-platform/CI claim* — census
   `edges` (9 edges incl. the cognition closure) + `ci_claim` on the
   windows-only sqlite3 edge inside the tri-platform matrix.
2. *No unresolved "probably sibling" edge* — every edge carries
   file:line evidence verified 2026-09-24; no inferred edges.
3. *Graph digest reproducible twice from the same inputs* —
   sha256(wr0-census.yaml) computed by two independent
   implementations, agreeing:
   `7f3fea88ade4504d2f98f2ce57fe23fac730c7481710081ac314bf4c627ccdc3`
   (python hashlib; certutil). Recompute on any future checkout with
   the same two tools; a mismatch means the census changed, not the
   digest algorithm.
4. *Profile B fixture + Profile J baseline + effort budget recorded* —
   the three sibling files.
5. *CA-1 inventory and bounded schedule unchanged* — this batch
   touched no CA record; the census references CA-0 outputs read-only.

## Findings worth the owner's attention (from the census itself)

- All five CMake/devkit pins equal canonical main EXCEPT the
  qiven-context devkit pin (d1d2a3a vs devkit main 94ee01e) — the
  workspace's only stale pin, recorded as the WR-6 reconciliation
  target rather than silently bumped.
- The validation-suppression pattern is live in exactly two consumers
  (draft, math); the Profile B fixture now pins its permanent
  regression semantics before any resolver exists.
- Seven resolver surfaces across eight nodes (4 CMake + 2 toolchain
  copies + 1 context shim) — the Profile J counter-2 baseline.

## What WR-0 deliberately did NOT do

No qiven-workspace repository, no schemas, no resolver code, no
authority change, no CA-0 reopening, no new dependency edges from the
H1-kit/router integration surfaces (recorded as surfaces per the
accepted §1 reclassification).
