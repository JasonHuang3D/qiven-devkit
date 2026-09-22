# Design-First Workflow Standard

Single canonical gate rule (ADR-0046: Devkit-canonical): **production
code is written only after a merged detailed design document** (owner
direction 2026-09-23). This standard defines what qualifies as a design
document, where it lives, when it is required, and the enumerated
exceptions — so the rule is operational, not aspirational.

## 1. The rule

For any batch that adds or changes production code (library, app,
script with engineering semantics), the authoring session MUST have a
design document that (a) existed before implementation started, and
(b) was published (merged) before or in the same batch as the
implementation, with the implementation PR naming it.

"Design existed before implementation" is proven by the document's
review record: the design self-review is performed against the design
ALONE, before any implementation code exists in the branch. Writing
the design after the code and backdating is a process violation worse
than having no design — it forfeits the document's entire purpose
(finding design defects while they are still cheap).

## 2. Relationship to feature-spec

`feature-spec.md` defines WHAT implementation-ready work is (intent,
semantics, scope, validation profile). This document requires the HOW
for non-trivial code: modules, types, ownership, threading, failure
handling, test spine. A batch needs BOTH: the feature spec bounds the
work; the design doc makes the shape reviewable before it is cast into
code. Small batches may satisfy both in one document (a section each).

## 3. Required design-document content

1. **Basis**: the governing architecture sections and prior designs it
   implements; explicit supersession/conflict statements.
2. **Module map**: new/changed components, their files, and what stays
   out.
3. **Contracts**: key types and APIs with ownership/lifetime and
   failure-channel decisions (no undecided failure channels at design
   time — feature-spec §4 rule extended).
4. **Concurrency & lifecycle**: threads/queues/handles, startup and
   shutdown orders where applicable.
5. **Failure modes**: enumerated failure classes and the fail-closed
   behavior for each.
6. **Test spine**: named tests proving each MUST, mapped to exit-gate
   rows where a program defines them.
7. **Dependencies**: third-party slots consumed (per
   `third-party-dependencies.md`) and deployment impact (per
   `deployment.md`).
8. **Deferrals**: every deliberately deferred mechanism with an
   observable failure signal and a falsifiable revisit trigger
   (constitution §15 — a deferral without these is wishful thinking,
   not engineering).
9. **Review record**: the pre-publication self-review with its
   findings and how each was folded in.

Documents that are diagrams-without-failure-modes or
code-dumps-without-contracts do not qualify.

## 4. Location and naming

- Repository-level designs: `docs/design/<batch>-<topic>.md`
  (snake_case, batch prefix like `mvp1-journal`). Architecture-level
  designs that define multi-batch structure live in
  `docs/architecture/` and are named there.
- The design doc is versioned with the repository and updated in the
  same transaction as deliberate scope changes — a design that no
  longer matches the code is a defect in one of the two, fixed in the
  same batch that caused the divergence.

## 5. Review and publication

1. The authoring session writes the design and performs the
   self-review (§3.9) BEFORE implementation.
2. The design is published (PR/merge) before the implementation PR, or
   as the first commit of a batch PR whose remaining commits are the
   implementation — in both cases the PR body names the design
   document.
3. Review classes unchanged: owner H2 for merges per the active mode
   (delegated H2 in long-running mode); material design rounds with
   unresolved semantics escalate to the owner rather than being
   guessed.

## 6. Exceptions (enumerated, narrow, declared)

A batch may skip a standalone design document ONLY when it is entirely:

- **E1 documentation-only** (docs/markdown, no code semantics);
- **E2 test-only** (adds/fixes tests against existing contracts);
- **E3 mechanical** (renames, formatting, includes, dead-code removal
  with no semantic change);
- **E4 gate/tooling repair** (operator/CMake/CI mechanics with no
  product-code semantics);
- **E5 trivial fix** (typo-level, single-file, no contract change).

The PR body must state the exception class in one line ("design-first:
E3 mechanical"). A batch combining an exception class with new
production semantics is NOT excepted. Adding a component, a port, a
public type, a process, a file format, or a third-party dependency is
never excepted.

## 7. Exemplar

`qiven-runtime/docs/architecture/runtime-production-mvp-cpp-design.md`
(2026-09-23) is the reference shape for a program-level design: basis,
ground rules, topology+migration, per-subsystem design with failure
modes, test spine, dependency slots, deferrals with triggers,
compliance map, self-review record. Batch-level designs scale this
down; they do not omit sections silently — they mark them N/A.

## Review record

Self-review 2026-09-23: (1) The same-PR option (design as first commit)
was kept alongside design-first-PR to avoid forcing two PRs for small
batches — the invariant protected is ordering (review before code
exists), not PR count. (2) Exception E5 is deliberately narrow and
self-policed by PR declaration; a false E-claim is detectable in delta
review and treated as a process violation. (3) No automated detector
yet (e.g. a gate check that changed src/ files have a named design in
the PR body) — recorded as the first candidate when the rule's manual
phase shows drift (engineering README "protocol evolution" question 5).
