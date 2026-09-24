"""Self-test for tools/workspace_resolver.py (WR-1 resolver).

Temp git fixtures only (testing law). Case ids ride in failure messages;
each case asserts one named exit criterion of doc 02 WR-1.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workspace_resolver as wr  # noqa: E402
import workspace_schemas as ws  # noqa: E402

DEVKIT_CONTRACT = "qiven-devkit-operator-v2"
PROVIDER_V1 = "qiven-provider-api-v1"
PROVIDER_V2 = "qiven-provider-api-v2-incompatible"


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"fixture git {args}: {result.stderr}")
    return result.stdout.strip()


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


def _record(repository: str, provides: list, dependencies: list) -> dict:
    return {
        "schema": "qiven-dependencies-v1",
        "repository": repository,
        "supported_platforms": ["windows"],
        "provides": provides,
        "dependencies": dependencies,
    }


def _dep(provider: str, kind: str, contract: str | None = None, **extra) -> dict:
    payload = {"id": provider, "kind": kind}
    if contract:
        payload["contract"] = contract
    payload.update(extra)
    return payload


def _fixture_workspace(root: Path, *, b_contract: str = PROVIDER_V1,
                       legacy_pin: str | None = None,
                       reverse_census: bool = False) -> tuple[Path, dict]:
    """Build control + provider/devkit checkouts; return (control, lock)."""
    devkit_repo, devkit_commit, devkit_tree = _make_repo(root, "qiven-devkit", {
        "README.md": "fixture devkit\n",
    })
    provider_repo, provider_commit, provider_tree = _make_repo(root, "fixture-provider", {
        "README.md": "fixture provider\n",
    })
    a_deps = [
        _dep("fixture-provider", "first-party-source", PROVIDER_V1),
        _dep("qiven-devkit", "tooling", DEVKIT_CONTRACT),
    ]
    if legacy_pin:
        a_deps[1]["legacy_consumer_pin"] = {
            "sha": legacy_pin, "equals_lock_node": False,
            "note": "fixture legacy split",
        }
    declarations = {
        "schema": "qiven-wr0-census-declarations-v1",
        "nodes": {
            "qiven-devkit": _record("qiven-devkit",
                                      [{"contract": DEVKIT_CONTRACT}], []),
            "fixture-provider": _record("fixture-provider",
                                        [{"contract": PROVIDER_V1}], []),
            "fixture-a": _record("fixture-a", [{"contract": "qiven-a-api-v1"}], a_deps),
            "fixture-b": _record("fixture-b", [{"contract": "qiven-b-api-v1"}], [
                _dep("fixture-provider", "first-party-source", b_contract),
            ]),
        },
    }
    if reverse_census:
        declarations["nodes"] = {k: declarations["nodes"][k]
                                 for k in reversed(list(declarations["nodes"]))}
    control = root / "control"
    (control / "census").mkdir(parents=True)
    manifest = {
        "schema": "qiven-workspace-v1",
        "workspace_id": "fixture-ws",
        "repositories": {
            node: {"url": f"https://github.com/O/{node}.git"} for node in declarations["nodes"]
        },
    }
    (control / "workspace.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (control / "census" / "wr0-declarations.json").write_text(
        json.dumps(declarations, indent=2) + "\n", encoding="utf-8", newline="\n")
    census_blob = _git(["hash-object", "census/wr0-declarations.json"], control)

    def node_entry(commit: str, tree: str, record: dict) -> dict:
        return {
            "commit": commit,
            "tree": tree,
            "declaration": {
                "origin": "census-wr0",
                "path": "census/wr0-declarations.json",
                "blob": census_blob,
                "digest": wr.declaration_digest(record),
                "shadow_only": True,
            },
        }

    lock_sg = {
        "schema": "qiven-workspace-lock-v1",
        "workspace_id": "fixture-ws",
        "nodes": {
            "qiven-devkit": node_entry(devkit_commit, devkit_tree, declarations["nodes"]["qiven-devkit"]),
            "fixture-provider": node_entry(provider_commit, provider_tree, declarations["nodes"]["fixture-provider"]),
            "fixture-a": node_entry("a" * 40, "b" * 40, declarations["nodes"]["fixture-a"]),
            "fixture-b": node_entry("c" * 40, "d" * 40, declarations["nodes"]["fixture-b"]),
        },
    }
    lock = dict(lock_sg)
    lock["generation"] = wr.generation_digest(manifest, lock_sg)
    (control / "workspace.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    _git(["init", "-q", "-b", "main"], control)
    _git(["add", "-A"], control)
    _git(["commit", "-q", "-m", "fixture control"], control)
    return control, lock


def _resolve_typed(control: Path, **kwargs) -> wr.ResolutionError:
    try:
        wr.resolve(control, kwargs.get("checkouts", {}), None,
                   kwargs.get("mode", "shadow"), kwargs.get("trust_policy"))
    except wr.ResolutionError as error:
        return error
    raise AssertionError("expected a typed ResolutionError, got success")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)

        # R1: golden vectors hold.
        failures = wr.run_golden_vectors()
        assert not failures, f"R1: {failures}"

        # R2: shadow resolution of a compatible census graph.
        control, lock = _fixture_workspace(root)
        receipt = wr.resolve(control, {}, None, "shadow", None)
        assert receipt["workspace_generation"] == lock["generation"], "R2: generation mismatch"
        assert receipt["shadow_only"] is True, "R2: census graph must be shadow-only"
        assert all(edge["validated"] for edge in receipt["edges"]), "R2: unvalidated edge"
        assert len(receipt["edges"]) == 3, "R2: edge count"

        # R3: Profile B conflict, order-independent, with a clean control.
        conflict_root = root / "r3"
        conflict_root.mkdir()
        control_b, _ = _fixture_workspace(conflict_root, b_contract=PROVIDER_V2)
        error = _resolve_typed(control_b)
        assert error.kind == "DependencyConflict", f"R3: {error.kind}"
        assert error.consumer_edge == "fixture-b->fixture-provider", "R3: edge not named"
        assert error.node == "fixture-provider", "R3: node not named"
        # order independence: the same graph built with reversed census key order.
        swapped_root = root / "r3-swapped"
        swapped_root.mkdir()
        control_s, _ = _fixture_workspace(swapped_root, b_contract=PROVIDER_V2,
                                          reverse_census=True)
        error_s = _resolve_typed(control_s)
        assert error_s.kind == "DependencyConflict" and error_s.consumer_edge == error.consumer_edge, (
            "R3: order changed the verdict"
        )

        # R4: tampered lock content fails generation; moved checkout HEAD fails typed.
        tampered_root = root / "r4"
        tampered_root.mkdir()
        control_t, lock_t = _fixture_workspace(tampered_root)
        bad_lock = json.loads(json.dumps(lock_t))
        bad_lock["nodes"]["fixture-provider"]["commit"] = "e" * 40
        # keep the stored generation of the ORIGINAL content: any edit must fail
        (control_t / "workspace.lock.json").write_text(
            json.dumps(bad_lock, indent=2) + "\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], control_t)
        _git(["commit", "-q", "-m", "tamper"], control_t)
        error_t = _resolve_typed(control_t)
        assert error_t.kind == "GenerationMismatch", f"R4a: {error_t.kind}"

        moved_root = root / "r4b"
        moved_root.mkdir()
        control_m, lock_m = _fixture_workspace(moved_root)
        provider = moved_root / "fixture-provider"
        (provider / "README.md").write_text("advanced\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], provider)
        _git(["commit", "-q", "-m", "advance"], provider)
        error_m = _resolve_typed(
            control_m, checkouts={"fixture-provider": str(provider)})
        assert error_m.kind == "RevisionMismatch", f"R4b: {error_m.kind}"

        # R5: authoritative bootstrap without an admitting policy fails Untrusted.
        error_u = _resolve_typed(control, mode="authoritative")
        assert error_u.kind == "UntrustedControlRevision", f"R5a: {error_u.kind}"
        policy_path = root / "trust.json"
        control_head = _git(["rev-parse", "HEAD"], control)
        policy_path.write_text(json.dumps({
            "schema": "qiven-workspace-control-trust-v1",
            "permitted_control_repository": None,
            "admitted_control_revisions": [control_head],
        }), encoding="utf-8", newline="\n")
        receipt_a = wr.resolve(control, {}, None, "authoritative", policy_path)
        assert receipt_a["mode"] == "authoritative" and receipt_a["shadow_only"] is True, (
            "R5b: census origins keep the receipt shadow-only even in authoritative mode"
        )
        unadmitted = root / "trust-unadmitted.json"
        unadmitted.write_text(json.dumps({
            "schema": "qiven-workspace-control-trust-v1",
            "admitted_control_revisions": ["f" * 40],
        }), encoding="utf-8", newline="\n")
        error_un = _resolve_typed(control, mode="authoritative", trust_policy=unadmitted)
        assert error_un.kind == "UntrustedControlRevision", f"R5c: {error_un.kind}"

        # R6: a resolver running from a Devkit other than the locked one fails typed.
        error_d = None
        try:
            wr.preflight(control, root / "qiven-devkit", "shadow", None,
                         devkit_node_id="qiven-devkit")
        except wr.ResolutionError as caught:
            error_d = caught
        assert error_d is not None and error_d.kind == "BootstrapDevkitMismatch", (
            f"R6: {error_d.kind if error_d else 'no failure'}"
        )

        # R7: generation is independent of the control checkout's location.
        clone = root / "control-clone"
        subprocess.run(["git", "clone", "-q", str(control), str(clone)], check=True,
                       capture_output=True, text=True, timeout=30)
        receipt_clone = wr.resolve(clone, {}, None, "shadow", None)
        assert receipt_clone["workspace_generation"] == receipt["workspace_generation"], (
            "R7: generation is path-dependent"
        )

        # R8: duplicate keys in the lock are a typed parse failure.
        dup = root / "control-dup"
        subprocess.run(["git", "clone", "-q", str(control), str(dup)], check=True,
                       capture_output=True, text=True, timeout=30)
        lock_text = (dup / "workspace.lock.json").read_text(encoding="utf-8")
        (dup / "workspace.lock.json").write_text(
            lock_text.replace('"workspace_id": "fixture-ws",',
                              '"workspace_id": "fixture-ws", "workspace_id": "fixture-ws",'),
            encoding="utf-8", newline="\n")
        _git(["add", "-A"], dup)
        _git(["commit", "-q", "-m", "dup"], dup)
        error_dup = _resolve_typed(dup)
        assert error_dup.kind == "DuplicateKey", f"R8: {error_dup.kind}"

        # R9: legacy pin split is reported in shadow, fatal in authoritative.
        split_root = root / "r9"
        split_root.mkdir()
        control_split, _ = _fixture_workspace(split_root, legacy_pin="9" * 40)
        receipt_split = wr.resolve(control_split, {}, None, "shadow", None)
        conflicts = receipt_split["baseline_conflicts"]
        assert conflicts and conflicts[0]["consumer_edge"] == "fixture-a->qiven-devkit", (
            "R9a: split not reported"
        )
        split_head = _git(["rev-parse", "HEAD"], control_split)
        policy_split = root / "trust-split.json"
        policy_split.write_text(json.dumps({
            "schema": "qiven-workspace-control-trust-v1",
            "admitted_control_revisions": [split_head],
        }), encoding="utf-8", newline="\n")
        error_split = _resolve_typed(control_split, mode="authoritative", trust_policy=policy_split)
        assert error_split.kind == "BaselineConflict", f"R9b: {error_split.kind}"

        # R11: a directory without control data fails typed, not as a traceback.
        error_nf = _resolve_typed(root / "fixture-provider")
        assert error_nf.kind == "WorkspaceNotFound", f"R11: {error_nf.kind}"

        # R10: preflight end-to-end through the LOCKED devkit resolver binary.
        fixture_devkit = root / "qiven-devkit"
        (fixture_devkit / "tools").mkdir(exist_ok=True)
        for name in ("workspace_resolver.py", "workspace_schemas.py"):
            (fixture_devkit / "tools" / name).write_text(
                (Path(__file__).resolve().parent / name).read_text(encoding="utf-8"),
                encoding="utf-8", newline="\n")
        schemas_dst = fixture_devkit / "docs" / "schemas"
        schemas_dst.mkdir(parents=True)
        for name in ("qiven-workspace-v1.schema.json", "qiven-workspace-lock-v1.schema.json",
                     "qiven-dependencies-v1.schema.json", "workspace-generation-golden-vectors.json"):
            (schemas_dst / name).write_text(
                (ws.SCHEMA_DIR / name).read_text(encoding="utf-8"),
                encoding="utf-8", newline="\n")
        # Re-pin: the fixture lock must select the devkit commit WITH the resolver files.
        _git(["add", "-A"], fixture_devkit)
        _git(["commit", "-q", "-m", "carry resolver"], fixture_devkit)
        new_devkit_commit = _git(["rev-parse", "HEAD"], fixture_devkit)
        new_devkit_tree = _git(["rev-parse", "HEAD^{tree}"], fixture_devkit)
        lock_r10 = json.loads(json.dumps(lock))
        devkit_node = lock_r10["nodes"]["qiven-devkit"]
        devkit_node["commit"], devkit_node["tree"] = new_devkit_commit, new_devkit_tree
        manifest_r10 = json.loads((control / "workspace.json").read_text(encoding="utf-8"))
        lock_r10.pop("generation")
        lock_r10["generation"] = wr.generation_digest(
            manifest_r10, {k: v for k, v in lock_r10.items() if k != "generation"})
        (control / "workspace.lock.json").write_text(
            json.dumps(lock_r10, indent=2) + "\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], control)
        _git(["commit", "-q", "-m", "re-pin devkit node"], control)

        result = subprocess.run(
            [sys.executable, str(fixture_devkit / "tools" / "workspace_resolver.py"),
             "preflight", "--control", str(control), "--devkit", str(fixture_devkit),
             "--mode", "shadow", "--json"],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        assert result.returncode == 0, f"R10: resolver preflight rc={result.returncode}: {result.stdout}{result.stderr}"
        preflight_receipt = json.loads(result.stdout)
        assert preflight_receipt["workspace_generation"] == lock_r10["generation"], "R10: generation"
        assert preflight_receipt["released"] is True and preflight_receipt["shadow_only"] is True, "R10: release flags"

    print("[ OK ] workspace-resolver self-test (R1-R11)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
