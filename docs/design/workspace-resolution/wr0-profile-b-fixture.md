# WR-0 Profile B Conflict Fixture (sealed definition)

Status: sealed 2026-09-24 (WR-0). Consumed by WR-1 (resolver) and
WR-2 (shadow gate). This is the PERMANENT regression target for the
`if(NOT TARGET qiven::foundation)` validation-suppression class
observed live at qiven-context-draft/CMakeLists.txt:30 and
qiven-math/CMakeLists.txt:22 (census edges draft-foundation,
math-foundation).

## Fixture graph

Two consumer declarations against one shared provider, plus the
control case:

~~~yaml
consumers:
  - id: fixture-runtime-like
    requires: {id: qiven-foundation, contract: qiven-foundation-api-v1}
    accepts: [qiven-foundation-api-v1]
  - id: fixture-draft-like
    requires: {id: qiven-foundation, contract: qiven-foundation-api-v2-incompatible}
    accepts: [qiven-foundation-api-v2-incompatible]
providers:
  - id: qiven-foundation
    revision: fixture-commit-A
    provides: [{contract: qiven-foundation-api-v1}]
    provides_note: does NOT provide v2-incompatible
control:
  - id: fixture-compatible-variant
    description: both consumers require api-v1 -> resolves clean
~~~

## Required outcomes (the contract WR-1 must satisfy)

1. Resolution returns the typed failure `DependencyConflict` naming
   BOTH the consumer edge and the conflicting node.
2. The failure occurs BEFORE any CMake configure/materialization.
3. The result is INDEPENDENT of consumer order, target materialization
   order, and whether one consumer would create `qiven::foundation`
   first (the exact suppression the current CMake pattern permits).
4. The compatible control variant resolves clean, proving the fixture
   fails on the conflict, not on fixture plumbing.
5. Counterexample K extension (sealed with this fixture): a clean
   candidate overlay that ADDS a required provider absent from the
   base lock fails full-graph validation even while the base graph
   still passes, with a candidate-specific full-graph receipt.

## Sealing

The fixture is data + expected-outcome only; no resolver code ships in
WR-0. WR-1 implements against this file verbatim; changing any
expected outcome requires a new sealed revision with a recorded reason.
