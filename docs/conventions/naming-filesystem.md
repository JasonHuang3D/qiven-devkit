# Filesystem and Repository Layout Conventions

Applies to every `qiven-*` repository unless its architecture document says
otherwise. Deviation requires an architecture document in the deviating repo.

## Repository root

| Entry | Purpose |
| --- | --- |
| `README.md` | what the repository is, build entry points, status |
| `AGENTS.md` | the mandatory preflight contract for LLM agents (Devkit-managed) |
| `CMakeLists.txt` + `CMakePresets.json` | CMake repositories only (see cmake-usage.md) |
| `.clang-format` | the formatting law (Devkit-managed) |
| `.gitignore` | generated products and local state only |
| `.qiven/` | operator config (`operator.json`), repo metadata |
| `docs/` | `architecture/` for durable design, `engineering/` for process (Devkit-managed) |
| `include/`, `src/`, `tests/`, `apps/`, `tools/` | C++ repositories (see naming-cpp.md) |

## Folder naming

- Always lowercase; words separated by hyphens only in file NAMES, never in
  folder names (`docs/architecture`, not `docs/Architecture`).
- Folder names are singular semantic domains (`memory`, `docs`, `tools`), not
  plural grab-bags (`stuff`, `misc`, `common` are forbidden).

## File naming per language

| Language | Rule | Examples |
| --- | --- | --- |
| C/C++ headers | `snake_case.hpp` | `byte_cursor.hpp`, `hashing.hpp` |
| C/C++ sources | `snake_case.cpp` mirroring the header | `byte_cursor.cpp` |
| Python | `snake_case.py` | `check_toolchain.py`, `format_sources.py` |
| Batch | lowercase, hyphens allowed, no spaces | `bootstrap.cmd`, `gen-vs2022-x64.cmd` |
| Shell | lowercase, `.sh`, hyphens allowed | `bootstrap.sh` |
| CMake modules | `snake_case.cmake` or `CMakeLists.txt` | `managed-files.cmake` |
| Markdown docs | `snake_case.md` or the established `PascalCase` for top-level specs | `foundation.md`, `pit-regression-map.md` |

## Branch naming

- `<designation>/<kebab-topic>` where the designation is the acting role or
  owner-granted session name: `jason-brother/*`, `jason-worker/*`,
  `zcode/*`, `jason-extended-cognition/*`.
- The branch name is convenience; the commit message trailer carries the
  binding identity (see the canonical operating contract, "Commit identity
  attribution").

## Commit messages

- `type(scope): subject` — type one of feat/fix/chore/docs/test/refactor;
  scope is the repository topic (operator, contracts, templates...).
- Subject line states the engineering change; attribution rides in the
  trailers (role/LLM), never in the subject.

## Generated and local artifacts

- `build/` and anything regenerated is ignored, never committed.
- Bytecode (`__pycache__/`, `*.pyc`) is ignored in every repository (pit:
  a tracked `.pyc` churned under a gate run).
- Scratch files used during a working session are deleted before the commit
  that closes the session; if they carry durable value they are renamed into
  `docs/` or a test.
