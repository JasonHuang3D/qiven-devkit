# Implementation Standard

## Scope and contracts

Implement only the authorized feature. Preserve existing public contracts unless the specification explicitly changes them.
Treat unclear ownership, lifetime, ABI, failure, dependency, compiler, or platform semantics as an architectural question.

## Design

Prefer the smallest design that completely satisfies the contract. Make ownership, lifetime, failure behavior, runtime cost,
and invariants explicit. Avoid speculative abstractions and hidden work. Dependencies must point downward; additions require
explicit approval. Keep public headers self-contained and platform-neutral.

## Portability and build

Windows, Linux, and macOS are real targets. Do not infer portability from one host. Do not change the language standard,
compiler flags, exception/RTTI policy, sanitizers, top-level CMake design, or CI policy without authorization.

## Change quality

Use repository formatting tools, add only intentional files, preserve unrelated work, inspect the entire diff, and run
`git diff --check`. Comments explain non-obvious intent and invariants, not obvious syntax.
