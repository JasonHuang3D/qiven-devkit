"""Self-test for tools/workspace_shadow.py (WR-2 shadow preflight).

Temp git fixtures only. Case ids ride in failure messages; each case
asserts one named WR-2 behavior (doc 02 section 2: per-class equality or
typed shadow conflict; a mismatch fails only its own class's migration
gate).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workspace_resolver as wr  # noqa: E402
import workspace_shadow as sh  # noqa: E402

DEVKIT_CONTRACT = "qiven-devkit-operator-v2"
FOUNDATION_V1 = "qiven-foundation-api-v1"


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"fixture git {args}: {result.stderr}")
    return result.stdout.strip()


def _record(repository: str, provides: list, dependencies: list) -> dict:
    return {
        "schema": "qiven-dependencies-v1",
        "repository": repository,
        "supported_platforms": ["windows"],
        "provides": provides,
        "dependencies": dependencies,
    }


def _fixture(root: Path, *, runtime_foundation_pin: str | None = None,
             context_devkit_pin: str | None = None,
             managed_snapshots: bool = True) -> Path:
    """Control repo + consumer repos with real legacy pin artifacts."""
    provider_repo, provider_commit, provider_tree = _make_repo(root, "qiven-foundation", {
        "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\n",
    })
    devkit_repo, devkit_commit, devkit_tree = _make_repo(root, "qiven-devkit", {
        "README.md": "fixture devkit\n",
    })

    pin_block = ""
    if runtime_foundation_pin == "LOCKED":
        pin_block = f'set(QIVEN_FOUNDATION_PINNED_SHA "{provider_commit}")\n'
    elif runtime_foundation_pin:
        pin_block = f'set(QIVEN_FOUNDATION_PINNED_SHA "{runtime_foundation_pin}")\n'
    _make_repo(root, "qiven-runtime", {
        "CMakeLists.txt": (
            "cmake_minimum_required(VERSION 3.20)\n"
            f"{pin_block}"
            'set(QIVEN_DRAFT_PINNED_SHA "' + "e" * 40 + '")\n'
        ),
    })
    runtime_entry = _record("qiven-runtime", [{"contract": "qiven-runtime-api-v1"}], [
        {"id": "qiven-foundation", "kind": "first-party-source", "contract": FOUNDATION_V1},
    ])
    if context_devkit_pin:
        _make_repo(root, "qiven-context", {
            ".qiven/operator.json": json.dumps({
                "schema_version": 1, "repository_name": "qiven-context",
                "devkit_pin": context_devkit_pin,
            }, indent=2) + "\n",
        })
    elif managed_snapshots:
        _make_repo(root, "qiven-context", {
            ".qiven/operator.json": json.dumps({
                "schema_version": 1, "repository_name": "qiven-context",
            }, indent=2) + "\n",
        })
        _make_repo(root, "qiven-math", {
            ".qiven/operator.json": json.dumps({
                "schema_version": 1, "repository_name": "qiven-math",
            }, indent=2) + "\n",
        })

    declarations = {"schema": "qiven-wr0-census-declarations-v1", "nodes": {
        "qiven-devkit": _record("qiven-devkit", [{"contract": DEVKIT_CONTRACT}], []),
        "qiven-foundation": _record("qiven-foundation", [{"contract": FOUNDATION_V1}], []),
        "qiven-runtime": runtime_entry,
    }}
    control = root / "control"
    (control / "census").mkdir(parents=True)
    manifest = {"schema": "qiven-workspace-v1", "workspace_id": "fixture-ws",
                "repositories": {n: {"url": f"https://github.com/O/{n}.git"}
                                  for n in declarations["nodes"]}}
    (control / "workspace.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (control / "census" / "wr0-declarations.json").write_text(
        json.dumps(declarations, indent=2) + "\n", encoding="utf-8", newline="\n")
    census_blob = _git(["hash-object", "census/wr0-declarations.json"], control)

    def node(commit: str, tree: str, record: dict) -> dict:
        return {"commit": commit, "tree": tree, "declaration": {
            "origin": "census-wr0", "path": "census/wr0-declarations.json",
            "blob": census_blob, "digest": wr.declaration_digest(record),
            "shadow_only": True}}

    lock_sg = {"schema": "qiven-workspace-lock-v1", "workspace_id": "fixture-ws",
               "nodes": {
                   "qiven-devkit": node(devkit_commit, devkit_tree, declarations["nodes"]["qiven-devkit"]),
                   "qiven-foundation": node(provider_commit, provider_tree, declarations["nodes"]["qiven-foundation"]),
                   "qiven-runtime": node("a" * 40, "b" * 40, runtime_entry),
               }}
    lock = dict(lock_sg)
    lock["generation"] = wr.generation_digest(manifest, lock_sg)
    (control / "workspace.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    _git(["init", "-q", "-b", "main"], control)
    _git(["add", "-A"], control)
    _git(["commit", "-q", "-m", "fixture control"], control)
    return control


def _make_repo(root: Path, name: str, files: dict[str, str]) -> tuple[Path, str, str]:
    repo = root / name
    repo.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "fixture"], repo)
    return repo, _git(["rev-parse", "HEAD"], repo), _git(["rev-parse", "HEAD^{tree}"], repo)


def _class(report: dict, name: str) -> dict:
    return next(c for c in report["classes"] if c["class"] == name)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)

        # SH1: equality — runtime pins the locked foundation commit (the
        # LOCKED sentinel binds the pin to the fixture provider commit).
        root2 = root / "sh1"
        root2.mkdir()
        control = _fixture(root2, runtime_foundation_pin="LOCKED",
                           context_devkit_pin=None, managed_snapshots=False)
        report = sh.build_report(control, root2)
        foundation = _class(report, "qiven-foundation")
        assert foundation["verdict"] == "equality" and foundation["cutover_eligible"] is True, (
            f"SH1: {foundation}"
        )
        assert report["equality_classes"] == ["qiven-foundation"], "SH1: equality set"

        # SH2: pin mismatch — typed shadow conflict for THAT class only,
        # the report itself still succeeds (rc-0 semantics).
        root3 = root / "sh2"
        root3.mkdir()
        control3 = _fixture(root3, runtime_foundation_pin="9" * 40,
                            context_devkit_pin=None, managed_snapshots=False)
        report3 = sh.build_report(control3, root3)
        conflict = _class(report3, "qiven-foundation")
        assert conflict["verdict"] == "shadow-conflict" and conflict["cutover_eligible"] is False, (
            f"SH2: {conflict}"
        )
        assert "fails this class's migration gate only" in conflict["disposition"], "SH2: scope"

        # SH3: context devkit_pin split — devkit class conflict with WR-6 disposition.
        root4 = root / "sh3"
        root4.mkdir()
        lock4_commit = None
        control4 = _fixture(root4, runtime_foundation_pin=None,
                            context_devkit_pin="7" * 40, managed_snapshots=False)
        report4 = sh.build_report(control4, root4)
        devkit = _class(report4, "qiven-devkit")
        assert devkit["verdict"] == "shadow-conflict" and "WR-6" in devkit["disposition"], (
            f"SH3: {devkit}"
        )

        # SH4: managed snapshots (no devkit_pin) — explicit shadow discrepancy, WR-6.
        root5 = root / "sh4"
        root5.mkdir()
        control5 = _fixture(root5, runtime_foundation_pin=None,
                            context_devkit_pin=None, managed_snapshots=True)
        report5 = sh.build_report(control5, root5)
        devkit5 = _class(report5, "qiven-devkit")
        assert devkit5["verdict"] == "shadow-discrepancy" and devkit5["cutover_eligible"] is False, (
            f"SH4: {devkit5}"
        )

        # SH5: unknown pin variable — typed extraction failure (never fake equality).
        root6 = root / "sh5"
        root6.mkdir()
        control6 = _fixture(root6, runtime_foundation_pin=None,
                            context_devkit_pin=None, managed_snapshots=False)
        runtime_cmake = root6 / "qiven-runtime" / "CMakeLists.txt"
        runtime_cmake.write_text(
            runtime_cmake.read_text(encoding="utf-8")
            + 'set(QIVEN_MYSTERY_PIN "' + "5" * 40 + '")\n',
            encoding="utf-8", newline="\n")
        try:
            sh.build_report(control6, root6)
        except sh.ShadowError as error:
            assert error.kind == "PinExtractionAmbiguous", f"SH5: {error.kind}"
        else:
            raise AssertionError("SH5: ambiguous pin accepted silently")

        # SH6: receipt shape — temporary records carry replacement stages +
        # WR-8 gate; census note; CA-1 recorded as N/A.
        report6 = sh.build_report(control, root2)
        records = report6["temporary_records"]
        assert records and all(r["wr8_removal_gate"] and not r["provider_authored_guarantee"]
                               for r in records), "SH6: temporary records"
        stages = {r["node"]: r["replacement_stage"] for r in records}
        assert stages["qiven-foundation"] == "WR-3" and stages["qiven-devkit"] == "WR-6", (
            f"SH6: stages {stages}"
        )
        assert "not applicable" in report6["ca1_note"], "SH6: CA-1 note"

        # SH7: CLI rc-0-with-conflicts and rc-1-on-typed-failure.
        rc_ok = sh.main(["--control", str(control3), "--workspace-root", str(root3), "--json"])
        assert rc_ok == 0, "SH7: shadow conflicts must not fail the run"
        rc_fail = sh.main(["--control", str(control6), "--workspace-root", str(root6), "--json"])
        assert rc_fail == 1, "SH7: typed extraction failure must fail"

    print("[ OK ] workspace-shadow self-test (SH1-SH7)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
