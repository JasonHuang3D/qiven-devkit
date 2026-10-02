# Qiven Conventions — Index

These documents are the SINGLE SOURCE OF TRUTH for naming and layout
conventions across every `qiven-*` repository. They live in the Devkit because
the Devkit owns the templates and the adoption machinery: a convention defined
here is rolled into every managed repository, so an LLM or human entering any
repo finds the rules through that repo's own `AGENTS.md` pointer — without
needing to have read a conversation or the canonical context repository.

## Why the rules live here and not in qiven-context

Rules that must hold inside a repository must be discoverable INSIDE
that repository (the 2026-09 observed failure: context-recorded rules
were never seen by sessions working elsewhere). Canonical text here;
pointer in every managed `AGENTS.md`.

## Documents

| Document | Scope |
| --- | --- |
| [naming-cpp.md](naming-cpp.md) | C++: files, folders, types, functions, variables, constants, enums, macros, namespaces, test names |
| [naming-filesystem.md](naming-filesystem.md) | Repository layout, folder purposes, file naming per language, branch naming |
| [naming-scripts.md](naming-scripts.md) | Batch (.cmd/.bat), shell (.sh), and Python tool scripts: files, flags, exit codes |
| [naming-cmake.md](naming-cmake.md) | CMake: targets, presets, options, functions, test registration |
| [cross-repo-cmake.md](cross-repo-cmake.md) | Consuming targets defined outside the consuming repository: the one consumption pattern, external-root registry, pin discipline, and what is deliberately not allowed (status banner in-file; landing shape: `../design/workspace-resolution.md`) |
| [cmake-usage.md](cmake-usage.md) | CMake usage law: presets as the only entry, toolchain pinning, forbidden invocations |
| [build-performance.md](build-performance.md) | Build-performance policy: measurement duty, PCH and /MP levers, linker notes, banned list, revisit triggers |
| [operator-usage.md](operator-usage.md) | Qiven Operator canonical usage: info/surface/records, gate/run/ci/exec, evidence-read, exit codes, hang-contract execution path, workspace mechanisms (lock-update/resolver/bootstrap, B6), devkit tool surfaces (schema-check/deploy) |
| [agent-entry.md](agent-entry.md) | AGENTS.md policy: pointer-only entry files, hard size limit, authority stays canonical |

## Known deviations (tracked, not hidden)

Rules codified 2026-09-20. Both codification-time deviations (draft
`k`-prefix constants; draft `PascalCase` service methods) were
remediated 2026-09-20; the last entry was struck 2026-10-01
(owner-recorded). No grandfathered deviations remain.
