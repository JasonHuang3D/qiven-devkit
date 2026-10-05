"""deploy_bundle.py — workspace-bounded continuous deployment (Devkit-owned).

Law: qiven-devkit docs/engineering/deployment.md (2026-09-23).
A repository declares WHAT to bundle in `.qiven/deploy.json`; this
script enforces the HOW: clean exact head + gate receipt, release
build, staged assembly with per-file digests, mandatory README +
licenses, in-bundle smoke validation, atomic publish, append-only
deploy log.

Usage:
  python deploy_bundle.py --repo <repo-path> [--profile release-x64]
  python deploy_bundle.py --verify <bundle-dir>

Exit codes: 0 success; 1 precondition/assembly/smoke failure; 2 usage.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

POLICY_SCHEMA = "qiven-deploy-policy-v1"
MANIFEST_SCHEMA = "qiven-deploy-manifest-v1"


def log(message: str) -> None:
    print(f"[deploy] " + message, flush=True)


def fail(message: str, next_action: str = "") -> int:
    """Typed deploy failure (B6: the four-element law - every FAIL carries
    WHAT/WHY/evidence in the message plus the NEXT action on the same
    selector-friendly line)."""
    suffix = f" - NEXT action: {next_action}" if next_action else ""
    print(f"[FAIL][deploy] {message}{suffix}", file=sys.stderr, flush=True)
    return 1


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: pathlib.Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env, check=False)


def git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], repo)


def inside_workspace(candidate: pathlib.Path, workspace: pathlib.Path) -> bool:
    try:
        candidate.resolve().relative_to(workspace.resolve())
        return True
    except ValueError:
        return False


def load_policy(repo: pathlib.Path) -> dict:
    policy_path = repo / ".qiven" / "deploy.json"
    if not policy_path.is_file():
        raise SystemExit(f"no deploy policy at {policy_path}")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema") != POLICY_SCHEMA:
        raise SystemExit(f"policy schema {policy.get('schema')!r} != {POLICY_SCHEMA!r}")
    return policy


def _locked_singleton_commit() -> str:
    """WR-5: the locked qiven-third-party-win node commit (typed fail)."""
    control = pathlib.Path(os.environ.get(
        "QIVEN_WORKSPACE_CONTROL",
        str(pathlib.Path(__file__).resolve().parent.parent.parent / "qiven-workspace"),
    )).resolve()
    lock_path = control / "workspace.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"workspace lock unreadable at {lock_path}: {exc} (WHY: the "
            "deploy bundle must identity-check the third-party singleton "
            "against the locked node - resolver adapter-generation; a lock that cannot be read "
            "fails closed) - NEXT action: DIAGNOSE - read the lock file at "
            "the path above; if it is missing/corrupt, re-run "
            "workspace_resolver.py lock-update to rebuild it, then re-run "
            "the deploy"
        )
    node = lock.get("nodes", {}).get("qiven-third-party-win")
    commit = node.get("commit") if isinstance(node, dict) else None
    if not isinstance(commit, str) or len(commit) != 40:
        raise SystemExit(
            "workspace lock has no qiven-third-party-win node commit "
            "(WHY: the deploy bundle must identity-check the third-party "
            "singleton against the locked node - resolver adapter-generation) - NEXT action: "
            "RECONCILE - a lock-update transaction "
            "(workspace_resolver.py lock-update --move "
            "qiven-third-party-win=<checkout>) is the lock's only writer; "
            "re-run the deploy after the node is recorded"
        )
    return commit


def resolve_singleton(repo: pathlib.Path) -> pathlib.Path | None:
    """Third-party singleton root (Devkit standard v2): env override ->
    sibling default -> None (no licenses to collect). The selected
    revision is identity-checked against the locked node (WR-5 shape,
    mirroring the runtime verify task)."""
    override = os.environ.get("QIVEN_THIRD_PARTY_ROOT")
    if override and (pathlib.Path(override) / "packages").is_dir():
        root = pathlib.Path(override)
    else:
        root = repo.parent / "qiven-third-party-win"
        if not (root / "packages").is_dir():
            return None
    locked = _locked_singleton_commit()
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    if head != locked:
        raise SystemExit(
            f"third-party singleton at {head[:12] or '<unreadable>'} != "
            f"locked node {locked[:12]}; advance the workspace lock deliberately"
            " - NEXT action: RECONCILE - a lock-update transaction"
            " (workspace_resolver.py lock-update --move"
            " qiven-third-party-win=<checkout>) is the lock's only"
            " writer; never re-point the singleton checkout")
    return root


def collect_provenance(repo: pathlib.Path) -> list[dict]:
    """Minimal PROVENANCE reader (name/version/license + LICENSE file) —
    the authoritative digests stay the singleton's verify task's job.
    Sources from the workspace singleton (standard v2; per-repo
    third_party/ no longer exists)."""
    singleton = resolve_singleton(repo)
    entries: list[dict] = []
    if singleton is None:
        return entries
    for provenance in sorted((singleton / "packages").glob("*/PROVENANCE.yaml")):
        name = provenance.parent.name
        version, license_name = "?", "?"
        for line in provenance.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip().strip("'\"")
            if line.startswith("license:"):
                license_name = line.split(":", 1)[1].strip().strip("'\"")
        license_file = provenance.parent / "LICENSE"
        entries.append(
            {
                "name": name,
                "version": version,
                "license": license_name,
                "license_file": str(license_file) if license_file.is_file() else "",
            }
        )
    return entries


def assemble(repo: pathlib.Path, policy: dict, staging: pathlib.Path, version: str, head: str) -> list[dict]:
    files: list[dict] = []
    for product in policy["products"]:
        src = repo / product["from"]
        dst = staging / product["to"]
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            raise SystemExit(
                f"declared product missing: {src}"
                " - NEXT action: FIX - build the product first or correct"
                " the products[].from mapping in .qiven/deploy.json"
            )
    # docs: rendered README + repo-provided extras
    template_path = repo / policy["docs"]["readme_template"]
    template = template_path.read_text(encoding="utf-8")
    readme = (
        template.replace("{{VERSION}}", version)
        .replace("{{HEAD}}", head)
        .replace("{{DATE}}", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
    )
    (staging / "docs" / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (staging / "docs" / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    for extra in policy["docs"].get("extras", []):
        src = repo / extra["from"]
        dst = staging / "docs" / extra["to"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # licenses: repo license + every vendored third-party license
    licenses = staging / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    repo_license = repo / policy["licenses"]["repo"]
    if repo_license.is_file():
        shutil.copy2(repo_license, licenses / f"{repo.name}-LICENSE")
    for entry in collect_provenance(repo):
        if entry["license_file"]:
            shutil.copy2(pathlib.Path(entry["license_file"]), licenses / f"{entry['name']}-LICENSE")
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(staging).as_posix(), "sha256": sha256_file(path)})
    return files


def smoke(staging: pathlib.Path, policy: dict) -> list[dict]:
    results = []
    for step in policy.get("smoke", []):
        cwd = staging / step.get("cwd", ".")
        command = list(step["command"])
        # Windows CreateProcess does not reliably resolve bare names against
        # the child cwd; resolve the executable against it explicitly.
        if "/" not in command[0] and "\\" not in command[0] and not pathlib.Path(command[0]).is_absolute():
            resolved = cwd / command[0]
            if resolved.is_file():
                command[0] = str(resolved)
        completed = run(command, cwd)
        results.append(
            {
                "command": " ".join(step["command"]),
                "exit": completed.returncode,
                "expected": step.get("expect_exit", 0),
                "note": step.get("note", ""),
            }
        )
        if completed.returncode != step.get("expect_exit", 0):
            print(completed.stdout[-2000:], file=sys.stderr)
            print(completed.stderr[-2000:], file=sys.stderr)
            raise SystemExit(
                f"smoke failed: {step['command']} -> {completed.returncode}"
                " - NEXT action: DIAGNOSE - the assembled bundle's own smoke"
                " step failed; classify from the bounded output above (the"
                " bundle was NOT published)"
            )
    return results


def deploy(repo_arg: str, profile_override: str | None) -> int:
    repo = pathlib.Path(repo_arg).resolve()
    if not (repo / ".git").exists():
        return fail(
            f"{repo} is not a git repository",
            "FIX - point --repo at a qiven repository checkout",
        )
    try:
        policy = load_policy(repo)
    except SystemExit as error:
        return fail(
            str(error),
            "FIX - declare the deploy policy .qiven/deploy.json"
            " (schema qiven-deploy-policy-v1: products/from-to, docs/"
            "readme_template+extras, licenses/repo, optional smoke steps;"
            " shape in --help and docs/engineering/deployment.md)",
        )
    profile = profile_override or policy.get("profile", "release-x64")

    # --- preconditions ----------------------------------------------------
    status = git(repo, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        return fail(
            "working tree not clean; deploy refuses",
            "FIX - commit or stash, then re-run (a clean exact head is a"
            " deploy precondition)",
        )
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    short = head[:8]
    gate_name = policy.get("gate", "local")
    receipt = repo / ".generated-temp" / "operator" / "receipts" / f"{gate_name}-{head}.json"
    if not receipt.is_file():
        return fail(
            f"no gate receipt {gate_name} at head {short}",
            f"run `qiven gate {gate_name} --expect-head {head}` at"
            " this exact head, then re-run the deploy",
        )

    # --- deploy root: workspace-bounded, fail closed ----------------------
    deploy_root = os.environ.get("QIVEN_DEPLOY_ROOT")
    if deploy_root:
        root = pathlib.Path(deploy_root)
    else:
        root = repo.parent / "deploy"  # sibling-layout workspace
    if not inside_workspace(root, repo.parent):
        return fail(
            f"deploy root {root} resolves outside the workspace ({repo.parent}); refusing",
            "FIX - set QIVEN_DEPLOY_ROOT to a path inside the workspace"
            " (or unset it for the sibling default)",
        )

    version = f"{policy['version']}-g{short}"
    final = root / repo.name / profile / version
    staging = root / f".staging-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.glob(".staging-*"):
        shutil.rmtree(stale, ignore_errors=True)  # crash cleanup, same-prefix sweep
    staging.mkdir(parents=True)
    log(f"staging {staging}")

    try:
        # --- build (release) ----------------------------------------------
        build = policy["build"]
        if not policy.get("skip_build", False):
            # WR-5 adapter-generation binding: configure must run through
            # the workspace bootstrap (gate-configure), which resolves the
            # locked providers and emits QIVEN_RESOLUTION_FILE; a bare
            # `cmake --preset` fails typed on every repo under the binding.
            # Defect found live 2026-09-29 (v48): the deploy path predated
            # the WR-5 cutover (last receipt 2026-09-22) and had never been
            # re-run; fixed here at the tooling owner instead of detouring.
            workspace = repo.parent
            control = pathlib.Path(os.environ.get(
                "QIVEN_WORKSPACE_CONTROL", str(workspace / "qiven-workspace")))
            devkit = pathlib.Path(__file__).resolve().parent.parent
            bootstrap = control / "bootstrap" / "qiven-bootstrap.py"
            if not bootstrap.is_file():
                return fail(
                    f"workspace bootstrap not found at {bootstrap}; the deploy "
                    "build requires the resolver adapter-generation resolution path (no bare configure)",
                    "FIX - point QIVEN_WORKSPACE_CONTROL at the control"
                    " checkout carrying bootstrap/qiven-bootstrap.py")
            configure = run(
                [sys.executable, str(bootstrap), "gate-configure",
                 "--control", str(control), "--devkit", str(devkit),
                 "--repo", repo.name, "--repo-root", str(repo),
                 "--preset", build.get("configure_preset", "vs2022-x64"),
                 "--cmake", "cmake"],
                repo)
            if configure.returncode != 0:
                return fail(
                    f"configure failed: {configure.stderr[-800:]}",
                    "DIAGNOSE - classify the bootstrap gate-configure failure"
                    " above (resolver adapter-generation: configure rides the workspace resolution"
                    " path; a bare `cmake --preset` is not an alternative)")
            built = run(
                ["cmake", "--build", str(repo / build["binary_dir"]), "--config", build["config"]], repo
            )
            if built.returncode != 0:
                return fail(
                    f"build failed: {built.stderr[-800:]}",
                    "DIAGNOSE - classify the build failure from the bounded"
                    " stderr tail above before any repair")

        # --- assemble + manifest -------------------------------------------
        files = assemble(repo, policy, staging, version, head)
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "repository": repo.name,
            "product": policy["product"],
            "profile": profile,
            "version": version,
            "head": head,
            "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "toolchain": {"cmake": run(["cmake", "--version"], repo).stdout.splitlines()[0].split()[-1]},
            "gate": {"name": gate_name, "head": head, "result": "PASS"},
            "files": files,
            "third_party": collect_provenance(repo),
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        manifest_digest = sha256_file(staging / "manifest.json")

        # --- validate IN the bundle ----------------------------------------
        results = smoke(staging, policy)
        manifest["smoke"] = results
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

        # --- publish (atomic) ----------------------------------------------
        if final.exists():
            shutil.rmtree(final)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
        log_line = {
            "at": manifest["built_at"],
            "repository": repo.name,
            "profile": profile,
            "version": version,
            "head": head,
            "manifest_sha256": manifest_digest,
            "files": len(files),
            "result": "PASS",
        }
        with (root / "deploy-log.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(log_line) + "\n")
        log(f"published {final}")
        log(f"files={len(files)} manifest_sha256={manifest_digest[:16]}...")
        return 0
    except SystemExit as error:
        # P3-20: the relay guarantees a vocabulary token on this FAIL
        # surface; a message that already states its own NEXT action keeps
        # it verbatim as the single recovery channel (never a second one).
        message = str(error)
        if "next action:" in message.casefold():
            return fail(message)
        return fail(
            message,
            "FIX - the deploy aborted at the precondition above; produce"
            " or repair the artifact it names, then re-run the deploy",
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def verify(bundle_arg: str) -> int:
    bundle = pathlib.Path(bundle_arg).resolve()
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        return fail(
            f"no manifest.json in {bundle}",
            "FIX - point --verify at a bundle directory produced by this"
            " tool (it contains manifest.json at its root)",
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        return fail(
            f"manifest schema {manifest.get('schema')!r} unrecognized",
            "FIX - verify a bundle built by this tool (its manifest"
            f" carries schema {MANIFEST_SCHEMA})",
        )
    failures = 0
    for entry in manifest.get("files", []):
        target = bundle / entry["path"]
        if not target.is_file():
            # P3-20: the per-file FAIL keeps its byte-stable prefix and
            # gains the vocabulary token (the file's four-element suffix
            # idiom) - the correction is mechanically known
            print(
                f"[FAIL] missing {entry['path']}"
                " - NEXT action: FIX - restore or produce the named"
                " artifact, then re-verify (re-running the deploy for the"
                " same head rebuilds a consistent bundle)"
            )
            failures += 1
            continue
        if sha256_file(target) != entry["sha256"]:
            print(
                f"[FAIL] digest mismatch {entry['path']}"
                " - NEXT action: FIX - restore the file from the published"
                " bundle, or re-run the deploy for the same head to rebuild"
                " it, then re-verify"
            )
            failures += 1
    if failures:
        return fail(
            f"{failures} file(s) failed verification",
            "re-run the deploy for the same head to rebuild a"
            " consistent bundle, or restore the missing/corrupt files from"
            " the published bundle",
        )
    print(f"[ OK ] deploy-verify: {len(manifest.get('files', []))} file(s) verified for {manifest.get('version')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="workspace-bounded deployment bundle builder (Devkit law: docs/engineering/deployment.md)",
        epilog=(
            "deploy policy shape (.qiven/deploy.json, schema"
            " qiven-deploy-policy-v1): {schema, product, version, profile,"
            " gate, build{configure_preset,binary_dir,config},"
            " products[{from,to}], docs{readme_template, extras[]},"
            " licenses{repo}, smoke[{cwd,command,expect_exit}]};"
            " the repository declares WHAT, this tool enforces HOW (clean"
            " exact head + gate receipt, release build, digests, atomic"
            " publish, append-only deploy log)"
        ),
    )
    parser.add_argument("--repo", help="repository checkout to deploy")
    parser.add_argument("--profile", help="override the policy profile")
    parser.add_argument("--verify", metavar="BUNDLE", help="verify a bundle against its manifest")
    args = parser.parse_args(argv)
    if args.verify:
        return verify(args.verify)
    if not args.repo:
        return fail(
            "--repo required (or --verify BUNDLE)",
            "FIX - python tools/deploy_bundle.py --repo <repo-path>"
            " [--profile P] | --verify <bundle-dir>",
        )
    return deploy(args.repo, args.profile)


if __name__ == "__main__":
    sys.exit(main())
