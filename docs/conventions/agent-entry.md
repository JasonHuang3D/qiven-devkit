# Agent Entry Contract (AGENTS.md)

Every managed repository carries exactly one root `AGENTS.md`, and it is a
**pointer, not a contract body**.

## Why pointer-only

- `AGENTS.md` is the one document an entering LLM agent reliably reads. It is
  the discovery mechanism, so it must exist in every repository — but that is
  its whole job.
- Roles, typed handoffs, execution authority and workflow are canonical in
  `JasonHuang3D/qiven-context` (collaboration contracts, loaded at cold
  boot; ADR-0035 role bindings, ADR-0036 typed handoffs). Duplicating them
  per-repo produced six near-identical ~8.5 KB contract copies that every
  repo entry paid for again in tokens, without any repo being able to change
  them correctly alone (2026-09-21 decision).
- Engineering law lives in this conventions tree and in the Devkit's
  `docs/engineering/` (single canonical copy, ADR-0046 2026-09-22 —
  repositories carry only the AGENTS.md pointer; the former per-repo
  copies are retired); architecture lives in each repository's
  `docs/architecture/`.

## Required shape (managed template)

1. One identity line: what this repository is (or a pointer to its README).
2. Pointer to the Devkit conventions index (`docs/conventions/README.md`)
   — to be read before creating files, folders, branches or targets.
3. Pointer to the repository's own `docs/engineering/` index and, where
  present, `docs/architecture/`.
4. One authority line: canonical roles/handoffs/authority live in
   qiven-context collaboration contracts; this file grants none.

Hard limit: `AGENTS.md` stays small (target 20 lines or fewer). Anything
longer belongs in `docs/` of this repository or in canonical context —
not in the entry file.
