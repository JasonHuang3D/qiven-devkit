# WR-2 Report — Shadow Resolution Against the Existing Build (2026-09-25)

Status: delivered under the owner's WR-2 start instruction (v27 turn 3,
long-running mode, delegated per-batch H2). Budget: exactly 2 devkit PRs
/ 1 working session (the sealed ceiling; PR E = shadow preflight +
comparator, PR F = Profile B permanent regression + candidate
validation + this report). The next owner decision point per the sealed
budget: **authorize the first class cutover (WR-3 Foundation) as the
Profile J pilot.**

## Deliverables

| Artifact | What it seals |
| --- | --- |
| `tools/workspace_shadow.py` (+ self-test SH1-SH7, gate task `workspace-shadow-tests`) | shadow preflight + legacy-pin comparator with per-class typed verdicts |
| `tools/workspace_profile_b_fixture.json` + `tools/workspace_profile_b_test.py` (gate task `workspace-profile-b-tests`) | the sealed Profile B fixture wired as the PERMANENT regression (outcomes 1-5 + K complement) |
| `workspace_resolver.py candidate` subcommand | minimal candidate-declaration validation (sealed outcome 5 / Profile K counterexample; the WR-2 form of the architecture §5.1 overlay — full per-node revision overlays arrive with WR-3) |
| live shadow report | `<workspace>/.generated-temp/workspace-shadow/2026-09-24T172330Z-shadow/report.json` (generation `sha256:0a9047be…`) |

## Live per-class verdicts (real workspace, 2026-09-25)

| Class (provider) | Legacy selections found | Locked | Verdict | Disposition |
| --- | --- | --- | --- | --- |
| qiven-foundation | cmake-pins runtime `f28b86b`, draft `f28b86b`, math `f28b86b` | `f28b86b` | **equality** | **cutover-eligible at WR-3** |
| qiven-context-draft | cmake-pin runtime `ea9af72` | `ea9af72` | **equality** | cutover-eligible at WR-4 |
| qiven-third-party-win | cmake-pin runtime `3184538` | `3184538` | **equality** | cutover-eligible at WR-5 |
| qiven-devkit | context devkit-pin `d1d2a3a`; managed snapshots (runtime/foundation/math/draft, no pin field) | `3c638b5` (lock snapshot; devkit main advanced during WR-2) | **shadow-conflict** | fails ONLY this class's gate; WR-6 reconciliation target |
| qiven-context, qiven-runtime, qiven-math, qiven-docs, qiven-toolchain-win | none (no consumer-local pin points at these nodes; toolchain is discovery-only) | — | no-legacy-selection | mechanism replaced at the named stage (WR-3/5/6/7) |

Every census node's declaration carries `provider_authored_guarantee:
false`, its replacement stage (WR-3..WR-7) and the hard WR-8 removal
gate in `temporary_records`. The CA-1 comparison clause is recorded as
not applicable (no CA-1 source lock exists yet), not silently skipped.

## Exit-criteria mapping (doc 02 WR-2 Exit)

1. *C++ gates pass with the shadow preflight reporting per-class
   equality or typed discrepancy* — WR-2 changed ZERO files in the C++
   repositories (legacy root+pin logic untouched, still the valid
   mechanism per ADR-0052 decision 1); their gates stand green at their
   published heads; a fresh corroborating `qiven-math` gate run rides
   this batch's session evidence. The shadow preflight reports exactly
   the per-class table above.
2. *Each class proposed for cutover has exact equality; known
   not-yet-migrated classes remain explicit discrepancies with named
   dispositions* — Foundation (the WR-3 proposal) shows equality across
   all three consumers; the Devkit class is an explicit shadow
   discrepancy with a WR-6 disposition; no global equivalence is
   claimed.
3. *No census provision mistaken for a provider guarantee; temporary
   records carry replacements + WR-8 gate* — `temporary_records` in the
   live report.
4. *Synthetic conflict fixture proves detection independent of CMake
   target order* — the permanent regression asserts sealed outcomes 1-4
   (typed DependencyConflict naming edge+node, pre-configure by
   construction — the resolver never invokes CMake, order-independence
   both ways) plus outcome 5 (candidate adding an absent provider fails
   while the clean base passes, with a candidate-specific receipt).

## Residuals and notes for the owner

- **WR-3 cutover decision** (the sealed budget's owner decision point 2):
  Foundation class equality is proven; the Profile J pilot measurement
  rides the cutover.
- **Routine-advance rule still pending** (turn-2 residual): the lock's
  devkit node records the WR-1-window snapshot `3c638b5` while devkit
  main advanced during WR-2 (PRs E/F); the first lock movement needs
  the owner-ratified advance rule or explicit re-admission. Shadow
  comparison is snapshot-based and unaffected.
- The lock's qiven-context node is likewise a WR-1-window snapshot
  (`8914cef`) while context main has since advanced (currently `9dea2f1`);
  same class of disclosure as the devkit node snapshot above — shadow
  comparison is snapshot-based and unaffected, and the next context lock
  movement falls under the same pending routine-advance rule (or explicit
  re-admission).
- The `[CONF]` console marker means "not equality" broadly; the
  `no-legacy-selection` verdict is a mechanism-replacement note, not a
  conflict (the JSON verdicts are authoritative).
- The `[EQ]`/`[CONF]` findings never gate the legacy build: the shadow
  tool exits 0 with conflicts because a mismatch fails only its own
  class's migration gate (SH7).
