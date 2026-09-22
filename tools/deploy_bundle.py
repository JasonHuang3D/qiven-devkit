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
    print(f"[deploy] {message}", flush=True)


def fail(message: str) -> int:
    print(f"[FAIL][deploy] {message}", file=sys.stderr, flush=True)
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


def collect_provenance(repo: pathlib.Path) -> list[dict]:
    """Minimal PROVENANCE reader (name/version/license + LICENSE file) —
    the authoritative digests stay the third-party-verify task's job."""
    third_party = repo / "third_party"
    entries: list[dict] = []
    if not third_party.is_dir():
        return entries
    for provenance in sorted(third_party.glob("*/PROVENANCE.yaml")):
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
                "license_file": str(license_file.relative_to(repo)).replace("\\", "/") if license_file.is_file() else "",
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
            raise SystemExit(f"declared product missing: {src}")
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
        source = repo / entry["license_file"] if entry["license_file"] else repo / "third_party" / entry["name"] / "LICENSE"
        if source.is_file():
            shutil.copy2(source, licenses / f"{entry['name']}-LICENSE")
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
            raise SystemExit(f"smoke failed: {step['command']} -> {completed.returncode}")
    return results


def deploy(repo_arg: str, profile_override: str | None) -> int:
    repo = pathlib.Path(repo_arg).resolve()
    if not (repo / ".git").exists():
        return fail(f"{repo} is not a git repository")
    policy = load_policy(repo)
    profile = profile_override or policy.get("profile", "release-x64")

    # --- preconditions ----------------------------------------------------
    status = git(repo, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        return fail("working tree not clean; deploy refuses")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    short = head[:8]
    gate_name = policy.get("gate", "local")
    receipt = repo / ".generated-temp" / "operator" / "receipts" / f"{gate_name}-{head}.json"
    if not receipt.is_file():
        return fail(f"no gate receipt {gate_name} at head {short}; run the gate first")

    # --- deploy root: workspace-bounded, fail closed ----------------------
    deploy_root = os.environ.get("QIVEN_DEPLOY_ROOT")
    if deploy_root:
        root = pathlib.Path(deploy_root)
    else:
        root = repo.parent / "deploy"  # sibling-layout workspace
    if not inside_workspace(root, repo.parent):
        return fail(f"deploy root {root} resolves outside the workspace ({repo.parent}); refusing")

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
            configure = run(["cmake", "--preset", build.get("configure_preset", "vs2022-x64")], repo)
            if configure.returncode != 0:
                return fail(f"configure failed: {configure.stderr[-800:]}")
            built = run(
                ["cmake", "--build", str(repo / build["binary_dir"]), "--config", build["config"]], repo
            )
            if built.returncode != 0:
                return fail(f"build failed: {built.stderr[-800:]}")

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
        return fail(str(error))
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def verify(bundle_arg: str) -> int:
    bundle = pathlib.Path(bundle_arg).resolve()
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        return fail(f"no manifest.json in {bundle}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        return fail(f"manifest schema {manifest.get('schema')!r} unrecognized")
    failures = 0
    for entry in manifest.get("files", []):
        target = bundle / entry["path"]
        if not target.is_file():
            print(f"[FAIL] missing {entry['path']}")
            failures += 1
            continue
        if sha256_file(target) != entry["sha256"]:
            print(f"[FAIL] digest mismatch {entry['path']}")
            failures += 1
    if failures:
        return fail(f"{failures} file(s) failed verification")
    print(f"[ OK ] deploy-verify: {len(manifest.get('files', []))} file(s) verified for {manifest.get('version')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="workspace-bounded deployment bundle builder (Devkit law: docs/engineering/deployment.md)")
    parser.add_argument("--repo", help="repository checkout to deploy")
    parser.add_argument("--profile", help="override the policy profile")
    parser.add_argument("--verify", metavar="BUNDLE", help="verify a bundle against its manifest")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify)
    if not args.repo:
        return fail("--repo required (or --verify BUNDLE)")
    return deploy(args.repo, args.profile)


if __name__ == "__main__":
    sys.exit(main())
