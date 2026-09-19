# C++ Naming Conventions

Applies to every `qiven-*` C++ repository. Foundation is the reference
codebase: when in doubt, match what Foundation already does.

## Files and folders

- Public headers: `include/qiven/<topic>/<name>.hpp` — `snake_case`, one
  primary type per header when practical (`byte_cursor.hpp`, `hashing.hpp`).
- Domain subfolders under `include/qiven/` only for real semantic domains
  (`memory/`); never for accidental grouping.
- Sources mirror headers: `src/<topic>/<name>.cpp` alongside
  `src/<name>.cpp`.
- Tests: `tests/<name>.cpp` for the public contract of `<name>.hpp`; plus
  `tests/headers/<name>.cpp` for the self-containment check. Every public
  header has both.

## Types

- Structs and classes: `PascalCase` (`ByteCursor`, `LinearArena`,
  `Materialization`).
- Acronyms inside type names: keep uppercase only when the acronym is the
  established domain name and at most three letters (`LLM`, `LLMClientTool`,
  `H2Evidence`). Do not invent new all-caps runs longer than three letters.
- Type aliases: `snake_case` (`using usize = std::size_t;`,
  `using RevisionId`—no: `RevisionId` is a type, so PascalCase; the alias NAME
  follows type rules because it introduces a type).
- Enums: `enum class` only. The enum name is `PascalCase` (`WorkMode`,
  `QuarantineState`); enumerators are `PascalCase` (`SupervisedForeground`,
  `Isolated`). Enumerators are always fully qualified at use sites
  (`WorkMode::Unattended`).

## Functions and methods

- Free functions and methods: `snake_case`, verb-first where the type does not
  already carry the noun (`take`, `remaining`, `checked_align_up`,
  `encode_le_u32`).
- Converters/queries returning a value read as a noun (`to_hex_u64`,
  `remaining_bytes`).
- One-line exception: casts and contract-named primitives may read as the
  mathematical operation (`checked_integer_cast<To>(value)`).

## Variables and members

- Locals and parameters: `snake_case` (`byte_span`, `declared_digest`).
- Members: `snake_case`, no `m`/`_` prefix decoration; where a trailing
  underscore already exists in a file, keep that file's local convention —
  new files use the bare `snake_case`.
- Constants: `constexpr` named like variables, no prefix
  (`fnv1a64_offset_basis`, `kSerializationVersion` is a GRANDFATHERED
  deviation — new constants follow Foundation: `serialization_version`).

## Namespaces

- Root: `qiven::`. Never `qiven::foundation`.
- Domain sub-namespaces only where a real long-lived domain exists
  (`qiven::memory::`); `detail` for implementation internals; no new nested
  namespaces per file.

## Macros

- SCREAMING_SNAKE with the `QIVEN_` prefix (`QIVEN_ASSERT`, `QIVEN_VERIFY`).
- Macros are a last resort (see the engineering law: no convenience macros).

## Templates and concepts

- Concepts: `snake_case` adjectives (`checked_integer`), matching the
  standard library's style (`integral`).

## CMake and test names

- See [naming-cmake.md](naming-cmake.md). Test executables:
  `qiven-<repo>-<topic>`; CTest names: `qiven-<repo>.<topic>`.
