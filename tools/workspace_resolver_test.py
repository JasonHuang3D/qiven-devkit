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

        # R12: syntactically broken control JSON (one quote removed from the
        # lock) is a typed SchemaViolation, never a bare traceback.
        malformed_root = root / "r12"
        malformed_root.mkdir()
        control_mal, _ = _fixture_workspace(malformed_root)
        (control_mal / "workspace.lock.json").write_text(
            (control_mal / "workspace.lock.json").read_text(encoding="utf-8").replace(
                '"workspace_id": "fixture-ws",', '"workspace_id: "fixture-ws",'),
            encoding="utf-8", newline="\n")
        _git(["add", "-A"], control_mal)
        _git(["commit", "-q", "-m", "malformed lock"], control_mal)
        error_mal = _resolve_typed(control_mal)
        assert error_mal.kind == "SchemaViolation", f"R12: {error_mal.kind}"
        assert "malformed JSON in workspace.lock.json" in error_mal.message, (
            f"R12: file not named: {error_mal.message}"
        )

        # R13 (F6): candidate package requirements are checked — a dep whose
        # package is not provided by the provider is a DependencyConflict
        # failure in the candidate receipt.
        package_candidate = root / "candidate-package.json"
        package_candidate.write_text(json.dumps(_record("fixture-candidate", [
            {"contract": "qiven-candidate-api-v1"},
        ], [
            _dep("fixture-provider", "first-party-source", PROVIDER_V1,
                 packages=["fixture-missing-package"]),
        ])), encoding="utf-8", newline="\n")
        candidate_pkg = wr.validate_candidate(control, package_candidate)
        assert candidate_pkg["candidate_validated"] is False, "R13: package gap accepted"
        package_failures = [f for f in candidate_pkg["failures"]
                            if f["type"] == "DependencyConflict"]
        assert package_failures and (
            package_failures[0]["message"] ==
            "edge fixture-candidate->fixture-provider: package "
            "fixture-missing-package not provided by fixture-provider"
        ), f"R13: {candidate_pkg['failures']}"

        # R14 (F5): the reference canonicalizer owns its UTF-16 key ordering
        # (inline key function, not shared with the primary). For a BMP key
        # vs an astral key, UTF-16 unit order is NOT code-point order (the
        # surrogate pair 0xD83D.. sorts before 0xFF01); both implementations
        # must still agree byte-for-byte on the UTF-16 order.
        tricky = {"\uff01": 1, "\U0001F600": 2}
        expected_tricky = '{"\U0001F600":2,"\uff01":1}'.encode("utf-8")
        assert wr.canonical_bytes(tricky) == expected_tricky, "R14: primary key order"
        assert wr.canonical_bytes_reference(tricky) == expected_tricky, (
            "R14: reference key order"
        )

        # R15 (F8): an object key containing a lone surrogate is a typed
        # CanonicalEncoding failure in the key branch (not a bare traceback).
        try:
            wr.canonical_bytes({"\ud800": 1, "a": 2})
        except wr.ResolutionError as error:
            assert error.kind == "CanonicalEncoding", f"R15: {error.kind}"
        else:
            raise AssertionError("R15: surrogate key accepted")

        # ------------------------------------------------------------------
        # WR-3 (overlay / adapter / lock-update)
        # ------------------------------------------------------------------

        def _repo_with_manifest(root_dir: Path, name: str, record: dict) -> Path:
            files = {".qiven/dependencies.json": json.dumps(record, indent=2) + "\n",
                     "README.md": f"{name} fixture\n"}
            repo, _commit, _tree = _make_repo(root_dir, name, files)
            return repo

        # R16 (sealed WR-3 fixture, doc 02 stage WR-3): runtime accepts
        # Foundation contract A while draft requires incompatible contract B
        # -> the GRAPH fails typed before any configure, regardless of which
        # consumer would have created the provider target first (validation
        # never consults target presence).
        r16_root = root / "r16"
        r16_root.mkdir()
        control_16, _ = _fixture_workspace(r16_root)
        a_record = _record("fixture-a", [{"contract": "qiven-a-api-v1"}], [
            _dep("fixture-provider", "first-party-source", PROVIDER_V1)])
        b_record = _record("fixture-b", [{"contract": "qiven-b-api-v1"}], [
            _dep("fixture-provider", "first-party-source", PROVIDER_V2)])
        a_repo = _repo_with_manifest(r16_root, "overlay-a", a_record)
        b_repo = _repo_with_manifest(r16_root, "overlay-b", b_record)
        try:
            wr.resolve_overlay(control_16, {"fixture-a": a_repo, "fixture-b": b_repo},
                               "shadow", None, {}, None)
        except wr.ResolutionError as error:
            assert error.kind == "DependencyConflict", f"R16: {error.kind}"
            assert error.consumer_edge == "fixture-b->fixture-provider", "R16: edge"
        else:
            raise AssertionError("R16: incompatible contract pair accepted")
        # order independence: swapping the overlay application order must not
        # change the verdict (sorted application inside _effective_lock).
        try:
            wr.resolve_overlay(control_16, {"fixture-b": b_repo, "fixture-a": a_repo},
                               "shadow", None, {}, None)
        except wr.ResolutionError as error:
            assert error.kind == "DependencyConflict", "R16: order changed the verdict"
        else:
            raise AssertionError("R16: order changed the verdict (accepted)")

        # R17: clean overlay of one node -> distinct effective generation,
        # repository-manifest origin, validated edges; the control lock is
        # NEVER mutated; an unknown overlay node is typed.
        r17_root = root / "r17"
        r17_root.mkdir()
        control_17, lock_17 = _fixture_workspace(r17_root)
        a_repo_17 = _repo_with_manifest(r17_root, "overlay-a17", a_record)
        receipt_17 = wr.resolve_overlay(control_17, {"fixture-a": a_repo_17},
                                        "shadow", None, {}, None)
        assert receipt_17["effective_generation"] != receipt_17["base_generation"], (
            "R17: overlay must derive a distinct effective generation"
        )
        node_17 = [n for n in receipt_17["nodes"] if n["id"] == "fixture-a"][0]
        assert node_17["declaration_origin"] == "repository-manifest", "R17: origin"
        assert all(edge["validated"] for edge in receipt_17["edges"]), "R17: edges"
        assert (control_17 / "workspace.lock.json").read_text(encoding="utf-8") == \
               json.dumps(lock_17, indent=2) + "\n", "R17: overlay mutated the control lock"
        try:
            wr.resolve_overlay(control_17, {"fixture-nope": a_repo_17}, "shadow", None, {}, None)
        except wr.ResolutionError as error:
            assert error.kind == "UnknownNode", "R17: unknown overlay node"
        else:
            raise AssertionError("R17: unknown overlay node accepted")

        # R18: adapter emission — deterministic bytes, resolved roots, the
        # anti-spoof guard (a provider target existing without the workspace
        # materialization is FATAL), and typed failure when a projected
        # provider has no checkout.
        r18_root = root / "r18"
        r18_root.mkdir()
        control_18, _ = _fixture_workspace(r18_root)
        provider_repo_18 = r18_root / "fixture-provider"  # built by _fixture_workspace
        a_repo_18 = _repo_with_manifest(r18_root, "overlay-a18", a_record)
        out_dir_18 = r18_root / "ad"
        receipt_18 = wr.emit_adapter(
            control_18, "fixture-a", a_repo_18, "shadow", None,
            {"fixture-provider": str(provider_repo_18)}, None, out_dir_18)
        adapter_text = Path(receipt_18["adapter_path"]).read_text(encoding="utf-8")
        assert wr.ADAPTER_CMAKE_SCHEMA_TAG in adapter_text, "R18: schema tag"
        assert 'set(QIVEN_WORKSPACE_PROVIDER_ROOT_fixture_provider "' in adapter_text, "R18: root"
        assert "message(FATAL_ERROR" in adapter_text and "target-presence spoof" in adapter_text, (
            "R18: anti-spoof guard missing"
        )
        assert "EXCLUDE_FROM_ALL" in adapter_text, "R18: singleton materialization"
        assert "qiven_workspace_materialize" in adapter_text, "R18: guard function"
        assert receipt_18["operation_projection_digest"].startswith("sha256:"), "R18: digest"
        assert receipt_18["target_repository"] == "fixture-a", "R18: target"
        # determinism: identical inputs -> identical adapter bytes
        receipt_18b = wr.emit_adapter(
            control_18, "fixture-a", a_repo_18, "shadow", None,
            {"fixture-provider": str(provider_repo_18)}, None, out_dir_18)
        assert receipt_18b["adapter_sha256"] == receipt_18["adapter_sha256"], "R18: determinism"
        # typed failure: projected provider without a checkout
        try:
            wr.emit_adapter(control_18, "fixture-a", a_repo_18, "shadow", None, {}, None, out_dir_18)
        except wr.ResolutionError as error:
            assert error.kind == "RevisionUnavailable", f"R18: {error.kind}"
        else:
            raise AssertionError("R18: missing provider checkout accepted")

        # R19: lock-update — the WR-3 cutover transaction helper. Move the
        # provider to a repository-manifest revision; the emitted lock +
        # declaration cache round-trip: written into a control copy, it
        # re-validates with a matching generation reading the moved node's
        # declaration from the CACHE (no checkout of that node).
        r19_root = root / "r19"
        r19_root.mkdir()
        control_19, _ = _fixture_workspace(r19_root)
        provider_record = _record("fixture-provider", [{"contract": PROVIDER_V1}], [])
        provider_repo_19 = _repo_with_manifest(r19_root, "moved-provider", provider_record)
        receipt_19 = wr.lock_update(control_19, {"fixture-provider": provider_repo_19},
                                    "shadow", None)
        assert receipt_19["new_generation"] != receipt_19["base_generation"], "R19: generation moved"
        assert receipt_19["changed_nodes"][0]["declaration_origin"] == "repository-manifest", "R19: origin"
        node_19 = receipt_19["new_lock"]["nodes"]["fixture-provider"]
        assert node_19["declaration"]["origin"] == "repository-manifest", "R19: lock node origin"
        assert node_19["declaration"]["shadow_only"] is False, "R19: not shadow"
        cache_19 = receipt_19["declaration_cache"][0]
        assert cache_19["path"] == "declarations/fixture-provider.json", "R19: cache path"
        control_19b = r19_root / "control-copy"
        import shutil as _shutil
        _shutil.copytree(control_19, control_19b)
        (control_19b / "workspace.lock.json").write_text(
            json.dumps(receipt_19["new_lock"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        cache_dir = control_19b / "declarations"
        cache_dir.mkdir()
        for cache_path, cache_text in receipt_19["_cache_files"].items():
            (control_19b / cache_path).write_text(cache_text, encoding="utf-8", newline="\n")
        _git(["add", "-A"], control_19b)
        _git(["commit", "-q", "-m", "fixture lock transaction"], control_19b)
        receipt_19b = wr.resolve(control_19b, {}, None, "shadow", None)
        assert receipt_19b["workspace_generation"] == receipt_19["new_generation"], (
            "R19: emitted lock fails its own generation check"
        )
        node_19b = [n for n in receipt_19b["nodes"] if n["id"] == "fixture-provider"][0]
        assert node_19b["declaration_origin"] == "repository-manifest", "R19: cache-loaded origin"
        # a TAMPERED cache (content != locked blob) fails typed
        (control_19b / "declarations" / "fixture-provider.json").write_text(
            json.dumps(provider_record | {"note": "tampered"}, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        _git(["add", "-A"], control_19b)
        _git(["commit", "-q", "-m", "tamper cache"], control_19b)
        try:
            wr.resolve(control_19b, {}, None, "shadow", None)
        except wr.ResolutionError as error:
            assert error.kind == "DeclarationBlobMismatch", f"R19: tamper {error.kind}"
        else:
            raise AssertionError("R19: tampered cache accepted")

        # R20: overlay hygiene — dirty overlay checkout is typed DirtyDependency
        # in authoritative mode, labeled (not fatal) in shadow; a manifest
        # declaring the wrong repository is a typed mismatch.
        r20_root = root / "r20"
        r20_root.mkdir()
        control_20, _ = _fixture_workspace(r20_root)
        a_repo_20 = _repo_with_manifest(r20_root, "overlay-a20", a_record)
        dirty_file = a_repo_20 / "dirty-marker.txt"
        dirty_file.write_text("uncommitted\n", encoding="utf-8")
        receipt_20 = wr.resolve_overlay(control_20, {"fixture-a": a_repo_20},
                                        "shadow", None, {}, None)
        assert receipt_20["overlays"]["fixture-a"]["state"] == "dirty-labeled", "R20: shadow label"
        try:
            wr.resolve_overlay(control_20, {"fixture-a": a_repo_20}, "authoritative", None, {}, None)
        except wr.ResolutionError as error:
            assert error.kind == "DirtyDependency", f"R20: {error.kind}"
        else:
            raise AssertionError("R20: dirty authoritative overlay accepted")
        dirty_file.unlink()
        wrong_record = _record("fixture-not-a", [{"contract": "qiven-a-api-v1"}], [])
        wrong_repo = _repo_with_manifest(r20_root, "overlay-wrong", wrong_record)
        try:
            wr.resolve_overlay(control_20, {"fixture-a": wrong_repo}, "shadow", None, {}, None)
        except wr.ResolutionError as error:
            assert error.kind == "DeclarationRepositoryMismatch", f"R20: {error.kind}"
        else:
            raise AssertionError("R20: mismatched repository manifest accepted")

        # R21: identity-preserving no-op overlay — a checkout ALREADY at a
        # node's locked commit (zero delta: same commit/tree) keeps the
        # locked node unchanged: already-locked overlay kind, effective
        # generation == base generation, and the node keeps its census-bound
        # declaration instead of a repository-manifest rebuild (the fixture
        # provider carries no .qiven/dependencies.json at its locked commit,
        # so a rebuild path cannot silently pass).
        r21_root = root / "r21"
        r21_root.mkdir()
        control_21, _ = _fixture_workspace(r21_root)
        provider_repo_21 = r21_root / "fixture-provider"  # built at the exact locked commit
        receipt_21 = wr.resolve_overlay(control_21, {"fixture-provider": provider_repo_21},
                                        "shadow", None, {}, None)
        assert receipt_21["overlays"]["fixture-provider"]["overlay_kind"] == "already-locked", (
            "R21: zero-delta overlay not classified already-locked"
        )
        assert receipt_21["effective_generation"] == receipt_21["base_generation"], (
            "R21: no-op overlay must derive the base generation"
        )
        node_21 = [n for n in receipt_21["nodes"] if n["id"] == "fixture-provider"][0]
        assert node_21["declaration_origin"] == "census-wr0", (
            "R21: locked node rebuilt instead of preserved"
        )

        # R22 (F3): authoritative mode with an active trust policy refuses
        # a DIRTY control working tree — admission is over the control
        # commit, but the lock and declarations are read from the working
        # tree, so a dirty tree must never be consumed branded with the
        # admitted HEAD; shadow mode on the same dirty tree still resolves,
        # and the authoritative resolve succeeds once the tree is clean.
        r22_root = root / "r22"
        r22_root.mkdir()
        control_22, lock_22 = _fixture_workspace(r22_root)
        marker_22 = control_22 / "notes.md"  # tracked, never consumed by the resolver
        marker_22.write_text("fixture marker\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], control_22)
        _git(["commit", "-q", "-m", "fixture marker"], control_22)
        head_22 = _git(["rev-parse", "HEAD"], control_22)
        policy_22 = root / "trust-r22.json"
        policy_22.write_text(json.dumps({
            "schema": "qiven-workspace-control-trust-v1",
            "admitted_control_revisions": [head_22],
        }), encoding="utf-8", newline="\n")
        marker_22.write_text("uncommitted edit\n", encoding="utf-8", newline="\n")
        error_22 = _resolve_typed(control_22, mode="authoritative", trust_policy=policy_22)
        assert error_22.kind == "ControlTreeDirty", f"R22: {error_22.kind}"
        receipt_22 = wr.resolve(control_22, {}, None, "shadow", None)
        assert receipt_22["workspace_generation"] == lock_22["generation"], (
            "R22: shadow must still resolve the dirty control tree"
        )
        marker_22.write_text("fixture marker\n", encoding="utf-8", newline="\n")
        receipt_22b = wr.resolve(control_22, {}, None, "authoritative", policy_22)
        assert receipt_22b["mode"] == "authoritative", (
            "R22: clean control at the admitted revision must resolve in authoritative mode"
        )


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

    print("[ OK ] workspace-resolver self-test (R1-R22)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
