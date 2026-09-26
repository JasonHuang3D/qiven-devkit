# Script Naming and Structure Conventions (Batch / Shell / Python)

Applies to tool scripts in every `qiven-*` repository (`tools/`, `scripts/`).

## Python (`tools/*.py`)

- Files: `snake_case.py`; one tool per file; the filename is the verb phrase
  (`check_toolchain.py`, `format_sources.py`, `apply_patch.py`).
- Entrypoint: `if __name__ == "__main__": raise SystemExit(main())`; `main()`
  returns the exit code as an int (0 pass, non-zero fail — the code itself is
  the contract).
- Flags: `--check` / `--fix` pairs for verify-vs-mutate tools; no positional
  flag soup; `argparse` for anything with more than one flag.
- Output: staged, machine-greppable markers when the tool is a gate
  (`[ RUN]` / `[ OK ]` / `[FAIL]`), observable state only.
- Bytecode is never committed (`__pycache__/`, `*.pyc` are gitignored).

## Batch (`.cmd` / `.bat`)

- Files: lowercase, short verb phrases (`bootstrap.cmd`, `test.cmd`,
  `qiven.cmd`).
- Every batch script: `setlocal`, explicit `exit /b %errorlevel%` semantics,
  and it MUST return a non-zero code on failure — a batch script that prints
  a failure but exits 0 is a defect.
- Chaining: batch scripts used inside `&&`/`||` chains are invoked with
  `call` (the canonical operating contract documents this).
- Batch is a thin transport wrapper: orchestration logic belongs to Python or
  CMake, not to growing `.cmd` files.

## Shell (`.sh`)

- Same rules as batch, POSIX-compatible; `set -euo pipefail` unless there is
  a documented reason; lowercase filenames.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | pass |
| 1 | the check/task itself failed |
| 2 | the environment is wrong (missing tool, bad usage, missing config) |

A gate that cannot run MUST fail (non-zero), never pass silently, and never
hang waiting for human input (the modal-dialog rule: contract violations and
environment failures terminate fast with the reason on stderr).

## Where scripts live

- Repository tools live in that repository's `tools/`.
- Scripts shared across repositories belong to the Devkit operator layer and
  are rolled out as managed snapshots — never copied ad hoc.
