# Workspace Resolution — Devkit Design Landing

Status: accepted program (ADR-0052, qiven-context 2026-09-24); WR-0
DELIVERED and **owner-accepted 2026-09-25 with WR-1 authorized** (see
[`workspace-resolution/wr0-report.md`](workspace-resolution/wr0-report.md)).
WR-1 is landing: schema family + strict validator (PR #35), resolver
with golden vectors (this batch), bootstrap contract test, and the
qiven-workspace control repository in shadow mode. Authoritative use
stays gated on the owner-accepted control-repository trust policy
(doc 02 §2 WR-1 / §7.7). The normative program documents are the
single source of truth:

- qiven-docs `accepted/2026-09-24/00-qiven-workspace-dependency-resolution-program.md`
  (governance laws WG-1..WG-10)
- qiven-docs `accepted/2026-09-24/01-qiven-workspace-resolution-architecture.md`
  (control repo, WorkspaceGeneration, bootstrap boundary, failure taxonomy)
- qiven-docs `accepted/2026-09-24/02-qiven-workspace-resolution-migration-and-acceptance.md`
  (WR-0..WR-8, Profiles A-K, effort budget + stall trigger)
- qiven-context `decisions/ADR-0052.md` (canonical adoption and scoping rulings)

## What Devkit owns

ADR-0052 assigns Devkit the resolver implementation surface:

- the workspace/dependency schemas' engineering custody (schema content is
  specified by the accepted documents; landing happens in WR-1 and is
  owner-gated after WR-0's sealed outputs);
- the resolver command that validates the declaration graph and emits the
  full-graph and operation receipts;
- the generated CMake adapter mechanism (`qiven_workspace_require`) and the
  configure-preset integration through which CMake consumes the resolved
  graph (see the revised `../conventions/cross-repo-cmake.md`);
- the bootstrap identity check that loads the exact locked Devkit resolver
  before any Operator import, and the `UntrustedControlRevision` typed
  failure class;
- the static gate that prevents new governed root+pin/sibling-resolution
  patterns after migration (WR-8).

## What does NOT change until cutover

- The current shim-plus-pin / external-root pattern remains the VALID,
  in-force consumption mechanism for every repository until its dependency
  class passes its own WR cutover (`../conventions/cross-repo-cmake.md` is
  the operative convention meanwhile).
- ADR-0048 process custody, ADR-0049 H1-kit self-containment, and the
  long-command routing contract (ADR-0051, still proposed at landing time)
  bind whatever entrypoint lands; changed routed command forms are re-tested
  against the deployed hook router, and changed H1 launchers/packages are
  re-tested for self-containment, in the same batch as the change.
- CA-1 (TCA source lock) proceeds on its own bounded schedule; WR-0/WR-1
  run in parallel and add no CA-1 gate.

## Entry sequencing (owner-gated)

WR-0 only first: machine-readable resolver census (reusing the CA-0
inventory), the Profile B conflict fixture, the before-migration Profile J
baseline, and a sealed WR-1/WR-2 effort budget. The qiven-workspace control
repository, the schemas, the bootstrap, and the resolver are authorized only
after the owner reviews those outputs. Two missed stage exits or a budget
breach pause authority cutovers for an owner decision (continue-bounded /
re-scope / abandon); shadow diagnostics never count as closing the legacy
defect classes.
