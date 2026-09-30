# WR-0 Profile J Baseline (sealed before-migration measurement)

Status: sealed 2026-09-24 (WR-0). The BEFORE half of Profile J
(cognitive-burden reduction). The AFTER half is measured only on a
controlled cutover/pilot (doc 02 §7.7; target: the WR-3 Foundation
class pilot) — never claimed from shadow mode.

## Measured baseline facts (evidence-backed)

1. **Mechanical pin-ripple cost of ONE compatible upstream movement**
   (foundation -> f28b86b, template 0.1.9 custody roll, v25 session
   2026-09-24): foundation PR #20 + math PR #12 (re-pin) + draft PR #40
   (re-pin + byte-identical operator.json customs re-application) +
   runtime PR #59 (re-pins BOTH foundation and draft; its gate FAILED
   TWICE mid-batch until both upstream re-pins landed). Four published
   PRs with four gate receipts for a movement whose semantics did not
   change. Baseline counters: 4 lock-equivalent updates, 4 mechanical
   peer-pin edit sets, 2 wasted gate runs, 0 owner interventions
   (delegated mode), elapsed ~2h10m wall (05:44-07:06 local commits).
2. **Distinct resolver implementations a participant must currently
   hold in mind**: 4 CMake resolvers (runtime, draft, math, foundation
   leaf) + 2 toolchain.py copies (runtime, foundation) + 1 context
   shim (tools/qiven.py discovery + operator.json pin) = 7 resolver
   surfaces across 8 nodes (census).
3. **Known silent-suppression hazards**: 2 active edges gate their
   provider validation behind target existence (draft:30, math:22) —
   configure can succeed with incompatible declarations depending on
   add order (census defect_class).
4. **Implementation split to reconcile before any single-Devkit
   claim** (WR-6): context executes devkit d1d2a3a via shim+pin; C++
   repositories execute template-0.1.9 managed snapshots; devkit main
   94ee01e (census baseline_splits).
5. **Entrypoint/environment tax** (adjacent evidence, recorded for
   scope honesty): the 2026-09-24 H1 kit pre-flight incident cost one
   owner trial + one sealed incident record; its class is ADR-0049
   jurisdiction, counted here only as context-reconstruction burden
   (which checkout supplies what, in which environment).

## Counters to re-measure on the WR-3 pilot (identical method)

- files read solely to reconstruct dependency location/version;
- mechanical peer-pin edits per accepted compatible movement (target
  after: 0; one lock transaction instead);
- workspace lock updates + owner interventions + elapsed time from an
  accepted Context-eligible source change to new-task eligibility;
- distinct resolver implementations (target after WR-6: 1);
- dependency-topology explanation tokens in one sealed cross-repo task;
- dependency-resolution mistakes found in review (baseline class #3
  above is the live example).

## Validity note

Counter 1 and 5 need a sealed task executed twice (before/after) under
the accepted Cognitive Effectiveness protocol; counters 2-4 are
machine-checkable from the census. This file fixes the method so the
after-measurement cannot drift.
