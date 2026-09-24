"""Bootstrap contract test (WR-1; the budget's "standard-library bootstrap"
devkit PR).

Exercises the REAL qiven-workspace bootstrap script end to end against
temp git fixtures: lock-subset validation, Devkit identity check BEFORE
any resolver import, preflight-only execution, and the typed failure
classes (BootstrapDevkitMismatch, RevisionUnavailable, DuplicateKey,
UntrustedControlRevision). Also asserts the WG-5 launcher laws on the
script text (no sibling discovery, preflight-only resolver execution)
and re-classifies the new workspace launcher command forms against the
deployed hook router (census entrypoint-integration duty, same batch).

The real bootstrap lives in the qiven-workspace control repository, not
in devkit (it must be loadable before Devkit exists). It is located via
QIVEN_WORKSPACE_BOOTSTRAP or the workspace sibling path; when absent
(managed snapshots, standalone devkit checkouts) the cross-repo legs
SKIP visibly and the router leg still runs, keeping the gate honest
without coupling devkit self-containment to an untracked sibling.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_exec_router as router  # noqa: E402
import workspace_resolver as wr  # noqa: E402
import workspace_schemas as ws  # noqa: E402

_DEVKIT_ROOT = Path(__file__).resolve().parent.parent
_BOOTSTRAP_CANDIDATES = [
    Path(os.environ["QIVEN_WORKSPACE_BOOTSTRAP"]) if os.environ.get("QIVEN_WORKSPACE_BOOTSTRAP") else None,
    _DEVKIT_ROOT.parent / "qiven-workspace" / "bootstrap" / "qiven-bootstrap.py",
]
BOOTSTRAP = next((p for p in _BOOTSTRAP_CANDIDATES if p and p.is_file()), None)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"fixture git {args}: {result.stderr}")
    return result.stdout.strip()


def _fixture(root: Path) -> tuple[Path, Path, dict]:
    """Control checkout + locked devkit checkout carrying the resolver."""
    devkit = root / "qiven-devkit"
    (devkit / "tools").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], devkit)
    (devkit / "README.md").write_text("fixture devkit\n", encoding="utf-8", newline="\n")
    for name in ("workspace_resolver.py", "workspace_schemas.py"):
        (devkit / "tools" / name).write_text(
            (_DEVKIT_ROOT / "tools" / name).read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n")
    schemas_dst = devkit / "docs" / "schemas"
    schemas_dst.mkdir(parents=True)
    for name in ("qiven-workspace-v1.schema.json", "qiven-workspace-lock-v1.schema.json",
                 "qiven-dependencies-v1.schema.json", "workspace-generation-golden-vectors.json"):
        (schemas_dst / name).write_text(
            (ws.SCHEMA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    _git(["add", "-A"], devkit)
    _git(["commit", "-q", "-m", "fixture devkit"], devkit)

    record = {
        "schema": "qiven-dependencies-v1",
        "repository": "qiven-devkit",
        "supported_platforms": ["windows"],
        "provides": [{"contract": "qiven-devkit-operator-v2"}],
        "dependencies": [],
    }
    declarations = {"schema": "qiven-wr0-census-declarations-v1",
                    "nodes": {"qiven-devkit": record}}
    control = root / "control"
    (control / "census").mkdir(parents=True)
    manifest = {"schema": "qiven-workspace-v1", "workspace_id": "fixture-ws",
                "repositories": {"qiven-devkit": {"url": "https://github.com/O/qiven-devkit.git"}}}
    (control / "workspace.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (control / "census" / "wr0-declarations.json").write_text(
        json.dumps(declarations, indent=2) + "\n", encoding="utf-8", newline="\n")
    census_blob = _git(["hash-object", "census/wr0-declarations.json"], control)
    lock_sg = {
        "schema": "qiven-workspace-lock-v1",
        "workspace_id": "fixture-ws",
        "nodes": {"qiven-devkit": {
            "commit": _git(["rev-parse", "HEAD"], devkit),
            "tree": _git(["rev-parse", "HEAD^{tree}"], devkit),
            "declaration": {"origin": "census-wr0", "path": "census/wr0-declarations.json",
                            "blob": census_blob, "digest": wr.declaration_digest(record),
                            "shadow_only": True},
        }},
    }
    lock = dict(lock_sg)
    lock["generation"] = wr.generation_digest(manifest, lock_sg)
    (control / "workspace.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    _git(["init", "-q", "-b", "main"], control)
    _git(["add", "-A"], control)
    _git(["commit", "-q", "-m", "fixture control"], control)
    return control, devkit, lock


def _run_bootstrap(control: Path, devkit: Path | None, *extra: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(BOOTSTRAP), "--control", str(control)]
    if devkit is not None:
        argv += ["--devkit", str(devkit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          timeout=180, encoding="utf-8", errors="replace")


def _error_type(result: subprocess.CompletedProcess) -> str:
    try:
        return json.loads(result.stdout)["error"]["type"]
    except (json.JSONDecodeError, KeyError):
        return f"<unparsed: rc={result.returncode} out={result.stdout[:200]} err={result.stderr[:200]}>"


def _router_leg() -> None:
    # census entrypoint-integration duty: the new workspace launcher forms
    # are short validation commands and must classify allow; the relative
    # devkit gate spelling must stay gate-class. FINDING recorded in the
    # WR-1 session (2026-09-25): path-prefixed qiven.cmd gate spellings
    # (absolute or nested) escape gate-class today - a pre-existing v4.1
    # scope limit surfaced by this re-test, routed as a follow-up batch,
    # not silently changed here.
    benign = [
        r'qiven-workspace\qiven.cmd --devkit D:\ws\qiven-devkit',
        r'python D:\ws\qiven-workspace\bootstrap\qiven-bootstrap.py --control D:\ws\qiven-workspace',
        r'python tools\workspace_resolver.py validate --control . --mode shadow',
    ]
    for command in benign:
        kind = router.classify(command)
        assert kind == "allow", f"B7: {command!r} classified {kind}, expected allow"
    assert router.classify(r'tools\qiven.cmd gate local') == "gate-class", (
        "B7: relative devkit gate spelling must stay gate-class"
    )
    assert router.classify(r'qiven.cmd gate local') == "gate-class", (
        "B7: bare devkit gate spelling must stay gate-class"
    )


def main() -> int:
    _router_leg()
    print("[ OK ] B7 router classification of workspace launcher forms")

    if BOOTSTRAP is None:
        print(f"[SKIP] B1-B6: real bootstrap not found (QIVEN_WORKSPACE_BOOTSTRAP unset, "
              f"no sibling qiven-workspace) - cross-repo legs not run")
        return 0

    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "workspace_resolver.py" in text and "preflight" in text, "B7a: bootstrap must be preflight-only"
    for forbidden in ("listdir", "glob(", "iterdir"):
        assert forbidden not in text, f"B7a: bootstrap performs sibling discovery ({forbidden})"

    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        control, devkit, lock = _fixture(root)

        # B1: end-to-end release through the real bootstrap.
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 0, f"B1: rc={result.returncode} out={result.stdout} err={result.stderr}"
        receipt = json.loads(result.stdout)
        assert receipt["workspace_generation"] == lock["generation"], "B1: generation"
        assert receipt["released"] is True and receipt["shadow_only"] is True, "B1: release flags"

        # B2: wrong Devkit identity fails typed BEFORE any resolver import.
        (devkit / "README.md").write_text("advanced\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], devkit)
        _git(["commit", "-q", "-m", "advance"], devkit)
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1 and _error_type(result) == "BootstrapDevkitMismatch", (
            f"B2: {_error_type(result)}"
        )
        _git(["reset", "-q", "--hard", "HEAD~1"], devkit)

        # B3: no Devkit locator at all fails typed.
        result = _run_bootstrap(control, None)
        assert result.returncode == 1 and _error_type(result) == "RevisionUnavailable", (
            f"B3: {_error_type(result)}"
        )

        # B4: duplicate lock keys fail typed at the bootstrap subset stage.
        lock_text = (control / "workspace.lock.json").read_text(encoding="utf-8")
        (control / "workspace.lock.json").write_text(
            lock_text.replace('"workspace_id": "fixture-ws",',
                              '"workspace_id": "fixture-ws", "workspace_id": "fixture-ws",'),
            encoding="utf-8", newline="\n")
        _git(["add", "-A"], control)
        _git(["commit", "-q", "-m", "dup"], control)
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1 and _error_type(result) == "DuplicateKey", (
            f"B4: {_error_type(result)}"
        )
        _git(["reset", "-q", "--hard", "HEAD~1"], control)

        # B5: authoritative bootstrap without an admitting policy is refused.
        result = _run_bootstrap(control, devkit, "--mode", "authoritative")
        assert result.returncode == 1 and _error_type(result) == "UntrustedControlRevision", (
            f"B5: {_error_type(result)}"
        )

        # B6: the checkout-mapping file substitutes for --devkit.
        (control / ".qiven-workspace.local.json").write_text(
            json.dumps({"checkouts": {"qiven-devkit": str(devkit)}}),
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, None)
        assert result.returncode == 0 and json.loads(result.stdout)["released"] is True, "B6: mapping leg"

    print("[ OK ] workspace-bootstrap contract test (B1-B7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
