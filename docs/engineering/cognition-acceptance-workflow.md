# Cognition Acceptance Workflow (CA-0 draft)

Status: DRAFT landed at CA-0 (ADR-0050 roadmap delivery map 6.2: "task/risk
taxonomy and acceptance workflow drafts"). Enforcement arrives with CA-2
(`qiven cognition prepare/show/explain/verify-receipt`); until then this is
the vocabulary and workflow authors design against.

## Task taxonomy (frozen vocabulary; schema: docs/schemas/engineering-task-v1.schema.json)

- **Phase**: `specify → design → implementation → review → acceptance`.
  Activation is reconsidered at every phase boundary (CG-2).
- **Risk**: R0 documentary / R1 ordinary bounded / R2 contract-bearing /
  R3 authority-or-production-boundary. Unknown classification defaults
  UPWARD, never downward. R2 requires protected activation + semantic-owner
  resolution + design-first evidence + an adversarial test spine +
  independent falsification before publication; R3 adds the typed owner
  handoffs (which an activation receipt never substitutes).
- **Boundary kinds**: ownership, lifetime, representation, serialization,
  ipc, persistence, concurrency, platform, external-contract, security,
  process-custody, filesystem, git, cognition, governance, tooling,
  human-interface. Boundary kinds a fixed normalizer cannot derive from
  task facts stay EMPTY (no curator enrichment for utility credit).

## Workflow (draft)

1. **Specify**: author the task envelope (schema above; only mechanical
   facts). The activation engine (CA-1) returns applicable scars,
   decisions, obligations, capabilities, and unresolved questions; a
   critical unresolved item blocks ReadyForDesign.
2. **Design (R2/R3)**: cognition compliance map — activated source →
   design consequence → named proof (not a prose restatement).
3. **Implementation**: design-evidence record binds the design digest to
   the activation receipt issued BEFORE the design; material selector
   changes invalidate and reactivate.
4. **Review (R2/R3)**: independent falsification per the acceptance
   protocol independence classes (`fresh-cognitive-same-family-isolated-context`
   for routine R2; orchestrated isolation for R3/Profile C/CA-5). The
   reviewer receives the task envelope, bundle, design, and diffs — never
   the author's reasoning trace — and is asked to disprove.
5. **Publication (CA-2 gate)**: valid activation receipt + delivery
   evidence + falsification receipt required at the declared gates;
   missing/stale/unresolved fail visibly without granting authority.

## Devkit-side artifacts this draft previews (CA-2 scope, not now)

`qiven cognition prepare|show|explain|verify-receipt`; the cognition
compliance map format; `qiven-cognitive-falsification-receipt-v1`; R2/R3
publication checks; the sealed fixture harness/scoring workflow.

## Relation to existing standards

This draft sits ABOVE the design-first workflow (design-first-workflow.md)
and the H1 kit standard (h1-kit.md): it does not replace them; CA-2 wires
the activation receipt into their gates. The execution protocol (branch/
batch/commit discipline) is unchanged.
