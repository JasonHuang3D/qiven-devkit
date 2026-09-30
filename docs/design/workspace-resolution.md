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
stage-by-stage history: the STANDING record (wr6 consolidation
residual, wr7/wr8 cutover + gate receipts) lives in the wr-reports
below; the closed early-stage records (WR-0 census/budgets/baselines,
WR-2 shadow migration, WR-3 pilot) are museum at
`docs/legacy/design/workspace-resolution/`.
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

## Migration-stage history (scope note)

> The rules below governed the program while it ran
> (2026-09-24..2026-09-28); the delivered end state supersedes the
> first bullet — every dependency class passed its WR cutover and
> `../conventions/cross-repo-cmake.md` carries the delivered registry.

- During migration, shim-plus-pin / external-root remained in force per
  repository until its dependency class passed its own WR cutover.
- **Still in force:** ADR-0048 process custody, ADR-0049 H1-kit
  self-containment, and the long-command routing contract (ADR-0051)
  bind whatever entrypoint lands; changed routed command forms and
  changed H1 launchers/packages are re-tested in the same batch as the
  change.
- Entry sequencing (historical, executed as written; delivered record
  in the wr-reports): WR-0 sealed-outputs first (census + Profile B
  fixture + Profile J baseline + sealed effort budget), owner-gated
  before the control repo/schemas/bootstrap/resolver were authorized;
  two missed stage exits or a budget breach paused authority cutovers
  for an owner decision; shadow diagnostics never closed legacy defect
  classes.
