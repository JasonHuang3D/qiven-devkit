# Workspace Resolution — Devkit Design Landing

Status: accepted program (ADR-0052, qiven-context 2026-09-24);
**DELIVERED END TO END 2026-09-28 (WR-0..WR-8)** — every dependency
edge declares through repository-owned manifests (`.qiven/dependencies.json`;
zero census-origin/shadow-only declarations), the forbidden-resolver-
pattern gate is live in the publication gate across the workspace, the
routine-advance rule is MECHANIZED in the resolver (semantic diff-shape
auto-admission), the E7 cutover is accepted and executed (ADR-0058:
`index rebuild` requires `--workspace-lock`, fail-closed on
non-cutover-grade closures), and the workspace resolves the full graph
AUTHORITATIVELY (shadow_only=False). The former typed BaselineConflict
on the context devkit pin was RESOLVED by the WR-6 pin deletion. The
stage-by-stage history (WR-0 census, shadow-mode rollout, per-class
cutover equality, comparator receipts) lives in the wr-reports below.
The normative program documents are the single source of truth:

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

## What did NOT change across the migration (historical scope note)

> The two sections below describe the MIGRATION-STAGE rules that governed
> the program while it ran (2026-09-24..2026-09-28). They are retained as
> the record of how the transition was controlled; the delivered end
> state supersedes the first bullet — every dependency class HAS passed
> its WR cutover and `../conventions/cross-repo-cmake.md` now carries the
> delivered registry.

- During the migration, the shim-plus-pin / external-root pattern
  remained the valid, in-force consumption mechanism for every
  repository until its dependency class passed its own WR cutover
  (`../conventions/cross-repo-cmake.md` was the operative convention
  meanwhile).
- ADR-0048 process custody, ADR-0049 H1-kit self-containment, and the
  long-command routing contract (ADR-0051, accepted 2026-09-24) bind
  whatever entrypoint lands; changed routed command forms are re-tested
  against the deployed hook router, and changed H1 launchers/packages
  are re-tested for self-containment, in the same batch as the change.
  (Still in force.)
- CA-1 (TCA source lock) proceeded on its own bounded schedule;
  WR-0/WR-1 ran in parallel and added no CA-1 gate. (Historical; CA-1
  completed 2026-09-28.)

## Entry sequencing (owner-gated) — historical

> The sequencing gate below governed the program START (the WR-0
> sealed-outputs authorization). It executed as written and is closed;
> see the wr-reports for the delivered record.

WR-0 only first: machine-readable resolver census (reusing the CA-0
inventory), the Profile B conflict fixture, the before-migration Profile J
baseline, and a sealed WR-1/WR-2 effort budget. The qiven-workspace control
repository, the schemas, the bootstrap, and the resolver are authorized only
after the owner reviews those outputs. Two missed stage exits or a budget
breach pause authority cutovers for an owner decision (continue-bounded /
re-scope / abandon); shadow diagnostics never count as closing the legacy
defect classes.
