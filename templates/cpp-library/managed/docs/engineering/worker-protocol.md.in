# Worker Protocol

## Start

Confirm the base branch/commit, clean-tree requirement, feature order, scope, stop conditions, and validation profile. Read the
mandatory engineering context and applicable architecture. Do not start when the specification leaves externally observable
semantics unresolved.

## Work

Use `jason-worker/<feature-name>` branches unless the current task explicitly authorizes another structure. Keep each feature a
coherent commit. Do not push, merge, create remotes/PRs, rewrite history, or change Git identity. Preserve unrelated changes.

## Stop

On an architecture or safety barrier, report `JASON-WORKER BLOCKER` with blocker type, current branch/commit state, exact
condition, evidence, working-tree state, and required decision. Do not guess.

After the complete authorized queue, report `JASON-WORKER HANDOFF` with repository, branch, full commit SHA, commit message,
architecture/implementation summary, tests, unchanged external repositories, remote operations, Git identity changes, final
tree state, and stop reason `AUTHORIZED_QUEUE_COMPLETED`.
