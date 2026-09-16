# Generic Qiven Operator Component

Qiven Operator is a repository-local orchestration runtime, not a C++-library-only feature. The generic component under `components/operator/` contains only the shared runtime launchers and Python implementation. Repository-specific policy remains owned by each repository in `.qiven/operator.json`.

## Materialize into a non-C++ repository

The target repository must already contain its own `.qiven/operator.json`, have a HEAD commit, and be clean. Inspect the plan first:

```text
cmake -DDEVKIT_ROOT=<qiven-devkit> -DMODE=check -DREPOSITORY=<repo> -P cmake/QivenOperatorMaterialize.cmake
```

Then apply the same plan with `MODE=apply`.

Materialization is conflict-atomic: runtime paths are classified as `EXACT`, `MISSING`, or `CONFLICT`; any conflict prevents all writes. Apply creates only missing runtime files and never overwrites repository policy or divergent runtime files.

The component currently vendors `tools/qiven.cmd`, `tools/qiven.sh`, `tools/qiven.py`, and `tools/qiven_operator.py`. Platform launchers are adapters; Operator semantics remain in the Python runtime and repository policy.

This first generic packaging checkpoint deliberately does not change the mature `cpp-library` template lifecycle. Non-C++ adoption is proven independently before the existing C++ managed-template source is physically deduplicated onto this component.
