"""Permanent regression: the sealed Profile B conflict fixture (WR-0 -> WR-2).

Driven by tools/workspace_profile_b_fixture.json, the faithful executable
transcription of docs/design/workspace-resolution/wr0-profile-b-fixture.md.
Asserts every sealed required outcome 1-5; a failure here names the
outcome that broke. This is the permanent regression for the
if(NOT TARGET qiven::foundation) validation-suppression class: resolution
must fail BEFORE configure, independent of consumer/materialization
order, with the compatible control variant resolving clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workspace_resolver as wr  # noqa: E402

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "workspace_profile_b_fixture.json").read_text(
        encoding="utf-8")
)


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


def _build_fixture_workspace(root: Path, *, compatible: bool = False,
                             consumer_order: list[dict] | None = None) -> Path:
    """Materialize the sealed fixture graph as a temp control workspace.

    compatible=True builds the sealed control variant (both consumers
    require api-v1). consumer_order overrides the sealed order (outcome 3).
    """
    graph = FIXTURE["fixture_graph"]
    provider = graph["providers"][0]
    provider_repo, provider_commit, provider_tree = _make_repo(root, "qiven-foundation", {
        "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\n",
    })

    consumers = consumer_order if consumer_order is not None else graph["consumers"]
    declarations = {"schema": "qiven-wr0-census-declarations-v1", "nodes": {
        "qiven-foundation": _record(
            "qiven-foundation",
            [{"contract": p["contract"]} for p in provider["provides"]],
            [],
        ),
    }}
    for consumer in consumers:
        contract = consumer["requires"]["contract"]
        if compatible:
            contract = graph["consumers"][0]["requires"]["contract"]  # both v1
        declarations["nodes"][consumer["id"]] = _record(
            consumer["id"],
            [{"contract": f"qiven-{consumer['id']}-api-v1"}],
            [{"id": "qiven-foundation", "kind": "first-party-source", "contract": contract}],
        )

    control = root / "control"
    (control / "census").mkdir(parents=True)
    manifest = {"schema": "qiven-workspace-v1", "workspace_id": "fixture-profile-b",
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

    lock_sg = {"schema": "qiven-workspace-lock-v1", "workspace_id": "fixture-profile-b",
               "nodes": {
                   "qiven-foundation": node(provider_commit, provider_tree,
                                            declarations["nodes"]["qiven-foundation"]),
                   **{c["id"]: node("c" * 40, "d" * 40, declarations["nodes"][c["id"]])
                      for c in consumers},
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
        (repo / rel).write_text(content, encoding="utf-8", newline="\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "fixture"], repo)
    return repo, _git(["rev-parse", "HEAD"], repo), _git(["rev-parse", "HEAD^{tree}"], repo)


def _expect_conflict(case: str, control: Path) -> wr.ResolutionError:
    try:
        wr.resolve(control, {}, None, "shadow", None)
    except wr.ResolutionError as error:
        return error
    raise AssertionError(f"{case}: expected the sealed conflict, got a clean resolution")


def main() -> int:
    graph = FIXTURE["fixture_graph"]
    runtime_like, draft_like = graph["consumers"]
    incompatible = draft_like["requires"]["contract"]

    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)

        # Outcomes 1+2: typed DependencyConflict naming the consumer edge AND
        # the conflicting node, raised during resolution (before any
        # configure/materialization could run - the resolver never invokes
        # CMake at all).
        control = _build_fixture_workspace(root)
        error = _expect_conflict("B-outcome-1/2", control)
        assert error.kind == "DependencyConflict", f"outcome 1: {error.kind}"
        assert error.consumer_edge == f"{draft_like['id']}->qiven-foundation", (
            f"outcome 1: edge {error.consumer_edge}"
        )
        assert error.node == "qiven-foundation", f"outcome 1: node {error.node}"
        assert incompatible in error.message, f"outcome 1: contract not named: {error.message}"

        # Outcome 3: order independence - sealed order and reversed order give
        # the identical typed verdict.
        reversed_root = root / "reversed"
        reversed_root.mkdir()
        control_r = _build_fixture_workspace(reversed_root, consumer_order=list(reversed(graph["consumers"])))
        error_r = _expect_conflict("B-outcome-3", control_r)
        assert (error_r.kind, error_r.consumer_edge, error_r.node) == (
            error.kind, error.consumer_edge, error.node
        ), "outcome 3: verdict changed with consumer order"

        # Outcome 4: the compatible control variant resolves clean.
        compat_root = root / "compatible"
        compat_root.mkdir()
        control_c = _build_fixture_workspace(compat_root, compatible=True)
        receipt = wr.resolve(control_c, {}, None, "shadow", None)
        assert receipt["shadow_only"] is True and receipt["edges"], "outcome 4: control plumbing"

        # Outcome 5 (K extension): a clean candidate declaration that ADDS a
        # required provider absent from the base lock fails full-graph
        # validation while the base graph still passes, with a
        # candidate-specific receipt. The BASE here is the clean compatible
        # control (the conflict variant legitimately cannot serve as a base).
        absent = root / "candidate-absent.json"
        absent.write_text(json.dumps(_record(
            "fixture-candidate", [], [{"id": "fixture-absent-provider",
                                       "kind": "first-party-source",
                                       "contract": "qiven-absent-api-v1"}]),
        ), encoding="utf-8", newline="\n")
        candidate = wr.validate_candidate(control_c, absent)
        assert candidate["base_graph_valid"] is True, "outcome 5: base must still pass"
        assert candidate["candidate_validated"] is False, "outcome 5: candidate must fail"
        failure = candidate["failures"][0]
        assert failure["type"] == "UnknownNode" and failure["node"] == "fixture-absent-provider", (
            f"outcome 5: {failure}"
        )

        # K extension complement: a candidate requiring the incompatible
        # contract from an EXISTING provider is a typed DependencyConflict.
        incompatible_candidate = root / "candidate-incompatible.json"
        incompatible_candidate.write_text(json.dumps(_record(
            "fixture-candidate-2", [], [{"id": "qiven-foundation",
                                         "kind": "first-party-source",
                                         "contract": incompatible}]),
        ), encoding="utf-8", newline="\n")
        candidate2 = wr.validate_candidate(control_c, incompatible_candidate)
        assert candidate2["candidate_validated"] is False, "K complement: must fail"
        assert candidate2["failures"][0]["type"] == "DependencyConflict", (
            f"K complement: {candidate2['failures'][0]}"
        )

        # A clean candidate (requires the provided contract) validates.
        clean_candidate = root / "candidate-clean.json"
        clean_candidate.write_text(json.dumps(_record(
            "fixture-candidate-3", [], [{"id": "qiven-foundation",
                                         "kind": "first-party-source",
                                         "contract": graph["consumers"][0]["requires"]["contract"]}])),
        encoding="utf-8", newline="\n")
        candidate3 = wr.validate_candidate(control_c, clean_candidate)
        assert candidate3["candidate_validated"] is True and not candidate3["failures"], (
            "clean candidate must validate"
        )

    print("[ OK ] profile-B permanent regression (sealed outcomes 1-5 + K complement)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
