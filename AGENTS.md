# qiven-devkit Agent Contract

The Devkit is the shared native development kit: templates, adoption
machinery, the Operator runtime, and the canonical engineering conventions.

## Conventions

- Naming, layout and script conventions are canonical in
  `docs/conventions/` (index: README.md there; includes the agent-entry
  rule, `agent-entry.md`) and apply to THIS repository (the Devkit
  self-hosts its own rules). Read the index before creating files,
  folders, branches or targets.
- Engineering standards (implementation, testing, execution,
  specification) are ALSO canonical here: `docs/engineering/README.md`
  (ADR-0046; this pointer is the entry).
- Operator discovery surface (B6): `tools/qiven.py` (`--help` first);
  `qiven surface` lists gates/tasks, `qiven records` reads back records.
  Canonical usage incl. workspace mechanisms (lock-update, resolver,
  bootstrap): `docs/conventions/operator-usage.md`.

Roles, typed handoffs, execution authority and workflow are canonical in
`JasonHuang3D/qiven-context` (collaboration contracts, loaded at cold
boot). This file grants no authority and repeats no contracts.
