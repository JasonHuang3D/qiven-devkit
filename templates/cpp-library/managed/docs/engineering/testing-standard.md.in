# Testing Standard

Tests must prove the feature's important semantics, not merely execute its happy path. Identify risks first, then cover relevant
boundaries, failures, ownership/lifetime transitions, invalid inputs, overflow/alignment, portability, and regression cases.

Tests must be deterministic, isolated, readable, and able to fail for the defect they protect against. Do not depend on test
order, developer-machine state, network availability, or unpinned external data. Use disposable fixtures for filesystem tests.

Never weaken assertions, warnings, sanitizers, diagnostics, or existing coverage to obtain a pass. Run the validation profile
specified by the feature; FULL is the default and includes required Debug and Release builds/tests, format checks, diff review,
and `git diff --check`.
