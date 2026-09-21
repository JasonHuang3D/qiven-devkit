# Build Performance Policy (MSVC-first)

Canonical policy for keeping `qiven-*` C++ builds fast as the codebase
grows. Owner direction 2026-09-21: compile-stage TU discipline and linker
attention are engineering duties, not afterthoughts. This document is
normative for every managed C++ repository; per-repo measurements live in
the repository that measured them.

## 1. Measure first, always

No performance change lands without before/after wall-clock numbers from
the same machine (clean configure + build-debug + build-release, plus one
incremental single-TU rebuild). The operator's per-task durations in gate
receipts are the standing evidence source. Numbers are recorded in the
landing commit message.

Baseline on JasonPC (qiven-runtime @ MSVC 19.44, VS generator, 25 TUs
across runtime + pinned draft + foundation): clean configure 2.4s,
build-debug 14.2s, build-release 15.8s, incremental single-TU ~2.3s.

## 2. Compile-stage levers (ranked)

1. **Precompiled headers over the heavy stable include stack** — the
   biggest TU-cost factor in this ecosystem is the frozen draft monolith
   (`qiven/context/cognition.hpp` + `runtime.hpp`) plus the foundation
   vocabulary, re-parsed by every TU. Precompile that stack once per
   library and `REUSE_FROM` it in every test target. Measured:
   clean builds −9% at 25 TUs; the win grows linearly with TU count.
   **Mandatory exemption:** header self-containment check targets set
   `DISABLE_PRECOMPILE_HEADERS ON` — injected PCH includes would mask the
   exact defect that target exists to catch (never weaken the detector).
2. **`/MP`** (MSVC) on every multi-file target — parallel `cl` batches
   inside a project; composes with `cmake --build --parallel` across
   projects.
3. **Header discipline in public headers** — include what a header uses
   (self-containment law), nothing more; prefer forward declarations for
   member-pointer types. The header-check targets enforce the floor.
4. **Keep heavy template/value-tree types out of widely-included
   headers** — the draft monolith is frozen and exempt (consumed as a
   pinned semantic library), but NEW public headers must not grow new
   monoliths; a header that transitively parses the draft monolith is a
   cost decision, visible in review.

## 3. Link-stage levers

1. Static-library topology already follows semantic ownership
   (foundation / draft / runtime are separate archives) — the linker sees
   small inputs per executable; keep it that way.
2. `/DEBUG:FASTLINK` for Debug links when link time shows up in
   measurements (CMake `CMP0141` context); not applied yet — no measured
   link-time pain at current scale.
3. LTCG stays OFF in developer presets (slow links are the wrong trade
   for the inner loop); Release CI may revisit deliberately.
4. Dynamic-library splitting is a **boundary decision, not a build-speed
   knob** (layer contract §3.1: STATIC is the default; a dylib boundary
   needs an accepted concrete requirement). Never split for linker
   happiness alone.

## 4. Banned or deferred

- **Unity/jumbo builds**: banned for header-check targets (defeats
  self-containment) and not used elsewhere — diagnostic granularity and
  ODR-adjacent semantics are worth more than the win while PCH exists.
- **C++20 modules**: prohibited by ADR-0009/0039.
- **Compiler-cache layers** (ccache-class external tools): external
  dependency, needs an accepted justification before entering the pinned
  toolchain.
- **Ninja generator switch**: plausible incremental-build win on Windows;
  requires toolchain-pin work in `qiven-toolchain-win`; revisit when
  incremental pain is measured, not speculatively.

## 5. Revisit triggers

- Clean build-debug exceeding 60s, or incremental single-TU rebuild
  exceeding 5s (MSBuild overhead included) on JasonPC.
- Any repository crossing ~150 TUs.
- Link time becoming a visible line item in gate receipts.

Each trigger fires a measurement + lever review under this policy.
