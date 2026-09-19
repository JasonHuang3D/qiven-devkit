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
| [cmake-usage.md](cmake-usage.md) | CMake usage law: presets as the only entry, toolchain pinning, forbidden invocations |

## Known deviations (tracked, not hidden)

The rules were codified 2026-09-20 after the fact; some existing code
predates them. Known deviations at codification time:

- `qiven-context-draft`: service methods use `PascalCase` (`Work`,
  `AcquireGrant`, `WriteToCognition`) while Foundation methods are
  `snake_case` (`take`, `remaining`). Target rule: Foundation style wins
  (`snake_case` methods). Remediation: scheduled rename in the draft, one
  mechanical commit, before Phase 4 closeout.
- `qiven-context-draft`: constants use the `k`-prefix (`kSerializationVersion`)
  while Foundation uses named constexpr without the prefix
  (`fnv1a64_offset_basis`). Target rule: no `k` prefix. Same remediation
  commit.

New code follows the rules immediately; the two renames above are the only
grandfathered deviations.
