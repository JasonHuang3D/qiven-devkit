# Deployment Standard (workspace-bounded continuous deployment)

Single canonical rule set for producing and validating DEPLOYED
artifacts from any `qiven-*` repository (ADR-0046: Devkit-canonical;
repositories carry no copies). Owner constraints (2026-09-23):
deployment operates strictly inside the workspace; nothing may pollute
any directory outside it; a deployment is not just build output — it is
a self-contained bundle with usage documentation.

"Continuous" here means: every accepted batch on `main` can be turned
into a validated bundle by ONE command, with a deterministic layout and
machine-checkable manifest — not a server, not a service, not an
installer.

## 1. Hard boundaries

1. **Workspace-bounded**: every path a deployment writes or reads is
   inside the workspace (the sibling-repository layout root, or a path
   given by an explicit `QIVEN_DEPLOY_ROOT` environment override).
   Resolution order: `QIVEN_DEPLOY_ROOT` → `<workspace>/deploy/`
   where `<workspace>` is the parent of the repository checkout under
   the standard sibling layout. If neither resolves inside the
   workspace, deployment FAILS CLOSED with an explicit error — it never
   guesses a fallback location.
2. **No system mutation**: no installs into Program Files, no registry,
   no PATH registration, no services, no scheduled tasks. A bundle is a
   directory the user invokes from where it stands; the bundle's
   documentation says how.
3. **Repos stay clean**: bundles are written ONLY under the deploy
   root, never inside repository trees (a bundle inside a repo would be
   untracked noise or accidental git content). Exception: none.
4. **Never deploy a dirty or unvalidated tree**: the deploying session
   must be at a clean exact head whose full gate PASSed; the manifest
   records head + gate receipt reference. Deploying uncommitted work is
   forbidden.

## 2. Bundle layout

```text
<deploy-root>/<repo>/<profile>/<version>/
  manifest.json         identity + digests (§4)
  bin/                  executables (and required DLLs)
  lib/ + include/       library products (when the product is a library)
  docs/
    README.md           what this is, in one page (§5)
    RUNBOOK.md          operational notes when the product has any
    CHANGELOG.md        what changed since the previous bundle
  licenses/
    <repo>-LICENSE      the repository's own license
    <name>-LICENSE     every consumed third-party license, sourced from
                        the singleton's packages (standard v2:
                        qiven-third-party-win packages/*/LICENSE)
```

- `<profile>`: the build/validation profile that produced the bundle
  (initially `release-x64`).
- `<version>`: `<version>-g<short-sha>` where `<version>` is the
  repository's declared version (from its CMake/README, `0.x.y` during
  the MVP) and `<short-sha>` the exact deployed head. The triple
  `<repo>/<profile>/<version>` is unique; re-deploying the same
  identity OVERWRITES atomically (staged dir + rename) after
  re-validation, and the manifest keeps a `deployed_at` timestamp and
  previous-manifest digest.
- PDB files ship only when the profile says so (release default: no
  PDBs; a `debug` profile exists for diagnosis bundles).

## 3. Production procedure (one operator task: `deploy`)

Implemented by the Devkit-owned `tools/deploy_bundle.py`; repositories
declare task metadata (what to bundle) in `.qiven/operator.json` and a
thin transport shim may resolve the Devkit checkout (ADR-0046 hook
pattern: `QIVEN_DEVKIT_ROOT` → sibling layout → explicit failure).

Steps (the script enforces the order and fails closed at each):

1. **Preconditions**: clean tree at exact head; gate receipt for that
   head exists (the operator's receipt store) — otherwise refuse.
2. **Build**: Release configure + build at that head (idempotent).
3. **Assemble**: copy the declared products (bin/lib/include/docs/
   licenses) into a staging dir `<deploy-root>/.staging-<pid>/`;
   compute SHA-256 for every file; write `manifest.json`; bundle the
   docs (`README.md` is mandatory — a bundle without usage
   documentation fails the deploy, not a warning); collect licenses
   from the singleton packages (resolved via `QIVEN_THIRD_PARTY_ROOT` /
   sibling layout, standard v2) + the repo license.
4. **Validate in place**: from inside the bundle directory, run the
   product's declared smoke command(s) (per-repo policy metadata:
   executables with their expected exit contracts). The smoke run's
   working directory IS the bundle — proving the bundle is
   self-contained rather than accidentally depending on the build tree.
5. **Publish**: atomic rename staging → final path; write the deploy
   event line (repo, version, head, result) to
   `<deploy-root>/deploy-log.jsonl` (append-only).
6. **Report**: print the bundle path, file count, total digest, smoke
   results. The deploying session records the bundle identity in the
   batch PR / session checkpoint.

Long steps (builds) route through the operator's own supervision; the
deploy task itself runs under the normal gate-class discipline.

## 4. manifest.json

```json
{
  "schema": "qiven-deploy-manifest-v1",
  "repository": "qiven-runtime",
  "product": "qiven-runtime",
  "profile": "release-x64",
  "version": "0.1.0-gff4ee34",
  "head": "<full-sha>",
  "built_at": "<rfc3339>",
  "toolchain": {"cmake": "<version>", "generator": "VS2022"},
  "gate": {"name": "local", "head": "<full-sha>", "result": "PASS"},
  "files": [{"path": "bin/...", "sha256": "..."}],
  "third_party": [{"name": "sqlite3", "version": "...", "license": "..."}],
  "smoke": [{"command": "...", "exit": 0, "note": "..."}]
}
```

The manifest is the bundle's identity: tampering with any bundled file
breaks its recorded digest; `deploy_bundle.py --verify <bundle>`
re-checks a bundle in place (used by acceptance and by anyone receiving
a bundle).

## 5. Mandatory bundle README.md shape

One page, in this order: (1) what the product IS and IS NOT (one
paragraph, honest about MVP scope); (2) how to run each shipped
executable: invocation, arguments, exit codes, config/env variables;
(3) requirements (OS, toolchain at RUN time if any); (4) safety
boundaries (what the artifact deliberately does not do — e.g. the
runtime host does not push, does not write outside the workspace); (5)
verification (the manifest --verify command); (6) provenance (head,
gate, license pointers). The README is generated from the repository's
declared metadata plus a repo-owned template section, so it can never
drift from what the script actually bundles.

## 6. Validation of the mechanism itself

The deploy mechanism is validated by exercising it: every repository
adopting deployment performs at least one real bundle + smoke
validation per release-class batch, recorded in the session checkpoint.
The first such validation for `qiven-runtime` (MVP-0 products) is the
v18 acceptance record for this standard.

## 7. Out of scope (recorded, not silent)

No remote publication, no code signing, no auto-update, no delta
bundles. Each becomes its own standard if a real requirement appears;
until then the deploy task does not grow those features.

## Review record

Self-review 2026-09-23: (1) overwrite-same-identity rule chose atomic
redeploy over immutable versions+counter suffixes — workspace bundles
are regenerable artifacts, and unbounded unique directories would
accumulate forever inside the workspace; the manifest retains
`deployed_at` + previous digest for audit. (2) Smoke commands are
declared per-repo policy (metadata), not hardcoded in the Devkit
script — the repository owns what "works" means for its products.
(3) `.staging-<pid>` under the deploy root keeps staging inside the
boundary; a crash leaves a stale staging dir which the next deploy
cleans (same-prefix sweep) — noted in the script. (4) Bundle README
generation is template + metadata, preventing doc drift; the template
lives in the repository (repo-owned), assembled by the script.
