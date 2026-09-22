# Qiven Conventions — Index

These documents are the SINGLE SOURCE OF TRUTH for naming and layout
conventions across every `qiven-*` repository. They live in the Devkit because
the Devkit owns the templates and the adoption machinery: a convention defined
here is rolled into every managed repository, so an LLM or human entering any
repo finds the rules through that repo's own `AGENTS.md` pointer — without
needing to have read a conversation or the canonical context repository.

## Why the rules live here and not in qiven-context

The canonical context repository records decisions and history, but it is read
only at cold boot of that one repository. The failure mode observed repeatedly
in 2026-09: conventions recorded in context were not seen by sessions working
in other repositories. Rules that must hold inside a repository have to be
discoverable INSIDE that repository — hence: canonical text here, pointer in
every managed `AGENTS.md` (the one document an LLM is required to read before
working).

## Documents

| Document | Scope |
| --- | --- |
| [naming-cpp.md](naming-cpp.md) | C++: files, folders, types, functions, variables, constants, enums, macros, namespaces, test names |
| [naming-filesystem.md](naming-filesystem.md) | Repository layout, folder purposes, file naming per language, branch naming |
| [naming-scripts.md](naming-scripts.md) | Batch (.cmd/.bat), shell (.sh), and Python tool scripts: files, flags, exit codes |
| [naming-cmake.md](naming-cmake.md) | CMake: targets, presets, options, functions, test registration |
| [cross-repo-cmake.md](cross-repo-cmake.md) | Consuming targets defined outside the consuming repository: the one consumption pattern, external-root registry, pin discipline, and what is deliberately not allowed (2026-09-23) |
| [cmake-usage.md](cmake-usage.md) | CMake usage law: presets as the only entry, toolchain pinning, forbidden invocations |
| [build-performance.md](build-performance.md) | Build-performance policy: measurement duty, PCH//MP levers, linker notes, banned list, revisit triggers |
| [operator-usage.md](operator-usage.md) | Qiven Operator canonical usage: gate/run/ci/exec, exit codes, hang-contract execution path |
| [agent-entry.md](agent-entry.md) | AGENTS.md policy: pointer-only entry files, hard size limit, authority stays canonical |

## Known deviations (tracked, not hidden)

The rules were codified 2026-09-20 after the fact; some existing code
predates them. Known deviations at codification time:

- `qiven-context-draft`: ~~constants use the `k`-prefix~~ — remediated
  2026-09-20 (V-4 rename; no `k`-prefixed constants remain).
- `qiven-context-draft`: service methods used `PascalCase` (`Work`,
  `BuildBundle`, ...) while Foundation methods are `snake_case`. Target rule:
  Foundation style wins. Remediation landed 2026-09-20 as branch
  `jason-extended-cognition/naming-remediation` (mechanical rename, draft
  local gate PASS); remove this entry once that branch is merged.

New code follows the rules immediately; the two renames above are the only
grandfathered deviations.
