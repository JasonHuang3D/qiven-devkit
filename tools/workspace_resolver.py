"""Workspace resolver (WR-1, ADR-0052; accepted architecture doc 01).

Validates the workspace declaration graph and emits resolution receipts.
Read-only with respect to product repositories: it consumes local Git
objects (rev-parse / cat-file / status) and the control tree only, and it
never mutates the workspace lock. Census-wr0 declaration origins are
shadow-only by construction: a receipt containing any census declaration
is labeled shadow-only and cannot back an authoritative operation.

Canonicalization is the RFC 8785 subset over the integer/string/bool/null/
array/object vocabulary (floats are rejected by the schema layer). The
generation digest is sha256 over the domain prefix plus the canonical
encoding of {"lock": <lock sans generation>, "manifest": <manifest>} —
independent of local absolute paths and timestamps by construction.

Exit codes: 0 validated / 1 typed failure / 2 usage or environment error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workspace_schemas as schemas  # noqa: E402

DEVKIT_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_GENERATION = b"qiven-workspace-generation-v1\x00"
DOMAIN_DECLARATION = b"qiven-dependency-declaration-v1\x00"
GIT_TIMEOUT = 15
RECEIPT_SCHEMA = "qiven-workspace-resolution-receipt-v1"
ERROR_SCHEMA = "qiven-workspace-resolution-error-v1"

_SHORT_ESCAPES = {"\x08": "\\b", "\x09": "\\t", "\x0A": "\\n", "\x0C": "\\f", "\x0D": "\\r"}


class ResolutionError(Exception):
    """A typed failure from the section 11 taxonomy (superset allowed)."""

    def __init__(self, kind: str, message: str, *, node: str | None = None,
                 consumer_edge: str | None = None) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message
        self.node = node
        self.consumer_edge = consumer_edge

    def as_dict(self) -> dict[str, str]:
        payload = {"type": self.kind, "message": self.message}
        if self.node:
            payload["node"] = self.node
        if self.consumer_edge:
            payload["consumer_edge"] = self.consumer_edge
        return payload


# ---------------------------------------------------------------------------
# Canonical JSON — RFC 8785 subset (implementation A, hand-rolled serializer)
# ---------------------------------------------------------------------------

def _jcs_string(value: str) -> str:
    out = ['"']
    for char in value:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[char])
        elif char < "\x20":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _sort_key_utf16(key: str) -> bytes:
    # RFC 8785 sorts property names by their UTF-16 code units, not by
    # code point; utf-16-be byte order reproduces that ordering exactly.
    try:
        return key.encode("utf-16-be")
    except UnicodeEncodeError as error:
        raise ResolutionError(
            "CanonicalEncoding",
            f"object key is not encodable UTF-16 (surrogate?): {error}",
        ) from error


def canonical_bytes(value: Any) -> bytes:
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, str):
        try:
            return _jcs_string(value).encode("utf-8")
        except UnicodeEncodeError as error:
            raise ResolutionError(
                "CanonicalEncoding", f"string is not encodable UTF-8 (surrogate?): {error}"
            ) from error
    if isinstance(value, list):
        return b"[" + b",".join(canonical_bytes(item) for item in value) + b"]"
    if isinstance(value, dict):
        fields = []
        for key in sorted(value, key=_sort_key_utf16):
            if not isinstance(key, str):
                raise ResolutionError("CanonicalEncoding", "non-string object key")
            fields.append(_jcs_string(key).encode("utf-8") + b":" + canonical_bytes(value[key]))
        return b"{" + b",".join(fields) + b"}"
    raise ResolutionError("CanonicalEncoding", f"value of type {type(value).__name__} outside the vocabulary")


def canonical_bytes_reference(value: Any) -> bytes:
    """Independent second implementation (composition over stdlib json).

    Required by the golden-vector law: two independently written code paths
    must agree byte-for-byte. This one builds leaves with json.dumps and
    owns the UTF-16 key ordering (inlined below, deliberately NOT shared
    with _sort_key_utf16) and the structural composition itself.
    """
    if value is None or isinstance(value, (bool, int, str)):
        dumps = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return dumps.encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical_bytes_reference(item) for item in value) + b"]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=lambda k: k.encode("utf-16-be")):
            key_text = json.dumps(key, ensure_ascii=False)
            parts.append(key_text.encode("utf-8") + b":" + canonical_bytes_reference(value[key]))
        return b"{" + b",".join(parts) + b"}"
    raise ResolutionError("CanonicalEncoding", f"value of type {type(value).__name__} outside the vocabulary")


def generation_digest(manifest: dict, lock_sans_generation: dict) -> str:
    payload = {"lock": lock_sans_generation, "manifest": manifest}
    return "sha256:" + hashlib.sha256(DOMAIN_GENERATION + canonical_bytes(payload)).hexdigest()


def declaration_digest(record: dict) -> str:
    return "sha256:" + hashlib.sha256(DOMAIN_DECLARATION + canonical_bytes(record)).hexdigest()


def content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


# ---------------------------------------------------------------------------
# Local Git object access (read-only)
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=GIT_TIMEOUT, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ResolutionError("RevisionUnavailable", f"git {args[0]} failed: {error}") from error
    if result.returncode != 0:
        raise ResolutionError("RevisionUnavailable", f"git {args[0]}: {result.stderr.strip()}")
    return result.stdout.strip()


def node_checkout(node_id: str, checkouts: dict[str, str], workspace_root: Path | None) -> Path | None:
    """A path is a locator, never a selector (WG-3)."""
    if node_id in checkouts:
        return Path(checkouts[node_id]).resolve()
    if workspace_root is not None:
        candidate = workspace_root / node_id
        if (candidate / ".git").exists():
            return candidate
    return None


def _verify_checkout(node_id: str, checkout: Path, node: dict, strict_clean: bool) -> dict:
    head = _git(["rev-parse", "HEAD"], checkout)
    tree = _git(["rev-parse", "HEAD^{tree}"], checkout)
    state = "clean"
    if head != node["commit"]:
        raise ResolutionError(
            "RevisionMismatch",
            f"{node_id} checkout HEAD {head} != locked {node['commit']}",
            node=node_id,
        )
    if tree != node["tree"]:
        raise ResolutionError(
            "TreeMismatch",
            f"{node_id} checkout tree {tree} != locked {node['tree']}",
            node=node_id,
        )
    dirty = _git(["status", "--porcelain"], checkout)
    if dirty:
        if strict_clean:
            raise ResolutionError("DirtyDependency", f"{node_id} worktree is dirty", node=node_id)
        state = "dirty-labeled"
    return {"id": node_id, "commit": head, "tree": tree, "state": state}


# ---------------------------------------------------------------------------
# Control identity and declarations
# ---------------------------------------------------------------------------

def _load_validated(control: Path) -> tuple[dict, dict]:
    def _load(name: str) -> Any:
        try:
            return schemas.load_strict(control / name)
        except FileNotFoundError as error:
            raise ResolutionError(
                "WorkspaceNotFound", f"no workspace control data at {control}: {error}"
            ) from error
        except json.JSONDecodeError as error:
            raise ResolutionError(
                "SchemaViolation", f"malformed JSON in {name}: {error}"
            ) from error
        except schemas.SchemaError as error:
            raise ResolutionError(error.error_type, error.message) from error

    manifest = _load("workspace.json")
    lock = _load("workspace.lock.json")
    for instance, schema_name in (
        (manifest, "qiven-workspace-v1.schema.json"),
        (lock, "qiven-workspace-lock-v1.schema.json"),
    ):
        errors = schemas.validate(instance, schemas.load_schema(schema_name))
        if errors:
            first = errors[0]
            raise ResolutionError(
                "SchemaViolation", f"{schema_name}: {first.error_type} at {first.path}: {first.message}"
            ) from first
    return manifest, lock


def _check_generation(manifest: dict, lock: dict) -> str:
    computed = generation_digest(manifest, {k: v for k, v in lock.items() if k != "generation"})
    if computed != lock["generation"]:
        raise ResolutionError(
            "GenerationMismatch",
            f"stored generation {lock['generation']} != computed {computed}",
        )
    if manifest["workspace_id"] != lock["workspace_id"]:
        raise ResolutionError(
            "WorkspaceIdMismatch",
            f"manifest {manifest['workspace_id']} vs lock {lock['workspace_id']}",
        )
    return computed


def _check_trust(control: Path, mode: str, trust_policy: Path | None) -> dict:
    if mode != "authoritative":
        return {"trusted": False, "reason": "shadow mode"}
    if trust_policy is None:
        raise ResolutionError(
            "UntrustedControlRevision",
            "authoritative mode requires --trust-policy admitting exact control revisions",
        )
    try:
        policy = schemas.load_strict(trust_policy)
    except (OSError, schemas.SchemaError) as error:
        raise ResolutionError("UntrustedControlRevision", f"trust policy unreadable: {error}") from error
    control_head = _git(["rev-parse", "HEAD"], control)
    permitted = policy.get("permitted_control_repository")
    if permitted:
        origin_url = _git(["remote", "get-url", "origin"], control)
        if origin_url != permitted:
            raise ResolutionError(
                "UntrustedControlRevision",
                f"control origin {origin_url} is not the permitted repository {permitted}",
            )
    admitted = policy.get("admitted_control_revisions", [])
    if control_head not in admitted:
        raise ResolutionError(
            "UntrustedControlRevision",
            f"control revision {control_head} is not admitted by {trust_policy}",
        )
    return {"trusted": True, "control_revision": control_head}


def _load_declaration(node_id: str, node: dict, control: Path, checkout: Path | None) -> tuple[dict, bool]:
    """Return (record, census_origin). Leaf nodes carry no record."""
    declaration = node["declaration"]
    origin = declaration["origin"]
    if origin == "leaf":
        return {"schema": "qiven-dependencies-v1", "repository": node_id,
                "supported_platforms": ["windows"], "provides": [], "dependencies": []}, False
    if origin == "census-wr0":
        try:
            record_text = (control / declaration["path"]).read_text(encoding="utf-8-sig")
            record = schemas.parse_strict(record_text)
        except (OSError, schemas.SchemaError, json.JSONDecodeError) as error:
            raise ResolutionError("MissingDeclaration", f"{node_id}: {error}") from error
        if isinstance(record, dict) and "nodes" in record:
            # census bundle form: select this node's record out of the file
            entries = record.get("nodes", {})
            if node_id not in entries:
                raise ResolutionError("MissingDeclaration", f"{node_id} absent from census bundle")
            record = entries[node_id]
        if "blob" in declaration:
            blob = _git(["hash-object", str(control / declaration["path"])], control)
            if blob != declaration["blob"]:
                raise ResolutionError(
                    "DeclarationBlobMismatch",
                    f"{node_id}: census file blob {blob} != locked {declaration['blob']}",
                    node=node_id,
                )
    elif origin == "repository-manifest":
        record_text: str | None = None
        if checkout is not None:
            try:
                record_text = _git(["show", f"{node['commit']}:.qiven/dependencies.json"], checkout)
            except ResolutionError:
                record_text = None  # fall through to the control-side cache
        if record_text is None and "blob" in declaration and "path" in declaration:
            # control-side declaration cache (Profile A/I: full-graph validation
            # without a checkout of every node; the cache blob is digest-bound)
            try:
                cache_text = (control / declaration["path"]).read_text(encoding="utf-8-sig")
            except OSError as error:
                raise ResolutionError(
                    "RevisionUnavailable",
                    f"{node_id}: no checkout and unreadable declaration cache "
                    f"{declaration['path']}: {error}",
                    node=node_id,
                ) from error
            blob = _git(["hash-object", str(control / declaration["path"])], control)
            if blob != declaration["blob"]:
                raise ResolutionError(
                    "DeclarationBlobMismatch",
                    f"{node_id}: declaration cache blob {blob} != locked {declaration['blob']}",
                    node=node_id,
                )
            record_text = cache_text
        if record_text is None:
            raise ResolutionError(
                "RevisionUnavailable",
                f"{node_id}: checkout needed for manifest read (no declaration cache)",
                node=node_id,
            )
        try:
            record = schemas.parse_strict(record_text)
        except (schemas.SchemaError, json.JSONDecodeError) as error:
            raise ResolutionError("MissingDeclaration", f"{node_id}: {error}") from error
    else:
        raise ResolutionError("MissingDeclaration", f"{node_id}: unknown origin {origin}")
    errors = schemas.validate(record, schemas.load_schema("qiven-dependencies-v1.schema.json"))
    if errors:
        first = errors[0]
        raise ResolutionError(
            "MissingDeclaration",
            f"{node_id} declaration: {first.error_type} at {first.path}: {first.message}",
            node=node_id,
        ) from first
    computed = declaration_digest(record)
    if computed != declaration["digest"]:
        raise ResolutionError(
            "DeclarationDigestMismatch",
            f"{node_id}: stored digest {declaration['digest']} != computed {computed}",
            node=node_id,
        )
    if declaration.get("origin") == "census-wr0" and not declaration.get("shadow_only", True):
        raise ResolutionError(
            "MissingDeclaration", f"{node_id}: census origin must be shadow_only", node=node_id
        )
    return record, origin == "census-wr0"


def _check_edges(records: dict[str, tuple[dict, bool]], lock: dict) -> list[dict]:
    """Validate every consumer edge (WG-4): before any materialization."""
    edge_results: list[dict] = []
    provisions: dict[str, dict[str, dict]] = {}
    for node_id, (record, _census) in records.items():
        for provided in record.get("provides", []):
            provisions.setdefault(node_id, {})[provided["contract"]] = provided

    for consumer_id, (record, _census) in records.items():
        for dep in record.get("dependencies", []):
            provider = dep["id"]
            edge_id = f"{consumer_id}->{provider}"
            result = {"edge": edge_id, "kind": dep["kind"], "validated": False}
            if provider not in lock["nodes"]:
                raise ResolutionError(
                    "UnknownNode", f"edge {edge_id}: provider not a lock node", node=provider,
                    consumer_edge=edge_id,
                )
            node = lock["nodes"][provider]
            if dep.get("platform") and dep["platform"] != node.get("platform", dep["platform"]):
                raise ResolutionError(
                    "PlatformMismatch", f"edge {edge_id}: platform {dep['platform']} vs node {node.get('platform')}",
                    node=provider, consumer_edge=edge_id,
                )
            contract = dep.get("contract")
            if contract is not None:
                provider_provides = provisions.get(provider, {})
                if contract not in provider_provides:
                    provided_names = sorted(provider_provides) or ["<nothing>"]
                    raise ResolutionError(
                        "DependencyConflict",
                        f"edge {edge_id}: requires {contract}; provider provides {provided_names}",
                        node=provider, consumer_edge=edge_id,
                    )
            for package in dep.get("packages", []):
                provider_provides = provisions.get(provider, {})
                if not any(package in p.get("packages", []) for p in provider_provides.values()):
                    raise ResolutionError(
                        "DependencyConflict",
                        f"edge {edge_id}: package {package} not provided by {provider}",
                        node=provider, consumer_edge=edge_id,
                    )
            result["validated"] = True
            edge_results.append(result)

    # Architectural cycle detection over declared semantic edges.
    graph: dict[str, list[str]] = {
        node_id: [dep["id"] for dep in record.get("dependencies", [])]
        for node_id, (record, _census) in records.items()
    }
    state: dict[str, int] = {}

    def visit(node_id: str, stack: list[str]) -> None:
        state[node_id] = 1
        for next_id in graph.get(node_id, []):
            if state.get(next_id) == 1:
                raise ResolutionError(
                    "CycleDetected",
                    f"architectural cycle: {' -> '.join(stack + [next_id])}",
                )
            if state.get(next_id, 0) == 0:
                visit(next_id, stack + [next_id])
        state[node_id] = 2

    for node_id in sorted(graph):
        if state.get(node_id, 0) == 0:
            visit(node_id, [node_id])
    return edge_results


def _baseline_conflicts(records: dict[str, tuple[dict, bool]], lock: dict) -> list[dict]:
    """Legacy consumer pins that disagree with the locked selection (the
    recorded implementation split) — reported, never silently resolved."""
    conflicts = []
    for consumer_id, (record, _census) in records.items():
        for dep in record.get("dependencies", []):
            pin = dep.get("legacy_consumer_pin")
            if not pin:
                continue
            locked_commit = lock["nodes"][dep["id"]]["commit"]
            if pin["sha"] != locked_commit:
                conflicts.append({
                    "consumer_edge": f"{consumer_id}->{dep['id']}",
                    "legacy_pin": pin["sha"],
                    "locked_node": locked_commit,
                    "note": pin.get("note", "legacy pin split (WR-6 reconciliation target)"),
                })
    return conflicts


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(control: Path, checkouts: dict[str, str], workspace_root: Path | None,
            mode: str, trust_policy: Path | None) -> dict:
    manifest, lock = _load_validated(control)
    generation = _check_generation(manifest, lock)
    trust = _check_trust(control, mode, trust_policy)

    for node_id in lock["nodes"]:
        if node_id not in manifest["repositories"]:
            raise ResolutionError("UnknownNode", f"lock node {node_id} not in the manifest universe")

    strict_clean = mode == "authoritative"
    records: dict[str, tuple[dict, bool]] = {}
    node_receipts: list[dict] = []
    for node_id, node in sorted(lock["nodes"].items()):
        checkout = node_checkout(node_id, checkouts, workspace_root)
        checkout_state = None
        if checkout is not None:
            checkout_state = _verify_checkout(node_id, checkout, node, strict_clean)
        record, census_origin = _load_declaration(node_id, node, control, checkout)
        records[node_id] = (record, census_origin)
        node_receipts.append({
            "id": node_id,
            "commit": node["commit"],
            "tree": node["tree"],
            "declaration_digest": node["declaration"]["digest"],
            "declaration_origin": node["declaration"]["origin"],
            "checkout_state": checkout_state["state"] if checkout_state else "not-materialized",
        })

    edges = _check_edges(records, lock)
    conflicts = _baseline_conflicts(records, lock)
    if conflicts and mode == "authoritative":
        first = conflicts[0]
        raise ResolutionError(
            "BaselineConflict",
            f"{first['consumer_edge']}: legacy pin {first['legacy_pin']} != locked {first['locked_node']}",
            consumer_edge=first["consumer_edge"],
        )

    any_census = any(census for _record, census in records.values())
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "workspace_id": lock["workspace_id"],
        "workspace_control_revision": _git(["rev-parse", "HEAD"], control) if (control / ".git").exists() else None,
        "workspace_generation": generation,
        "mode": mode,
        "shadow_only": any_census or mode != "authoritative",
        "legacy_resolution_used": True,
        "nodes": node_receipts,
        "edges": edges,
        "baseline_conflicts": conflicts,
    }
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    return receipt


def preflight(control: Path, devkit: Path, mode: str, trust_policy: Path | None,
              checkouts: dict[str, str] | None = None,
              devkit_node_id: str = "qiven-devkit") -> dict:
    merged = dict(checkouts or {})
    merged[devkit_node_id] = str(devkit)
    receipt = resolve(control, merged, None, mode, trust_policy)
    lock = schemas.load_strict(control / "workspace.lock.json")
    devkit_node = lock["nodes"][devkit_node_id]
    own_root = DEVKIT_ROOT
    own_head = _git(["rev-parse", "HEAD"], own_root)
    if own_head != devkit_node["commit"]:
        raise ResolutionError(
            "BootstrapDevkitMismatch",
            f"resolver runs from devkit {own_head} but the lock selects {devkit_node['commit']}",
        )
    receipt["operation"] = "preflight"
    receipt["operation_projection"] = [{"id": devkit_node_id, "commit": devkit_node["commit"]}]
    receipt["operation_projection_digest"] = content_digest(receipt["operation_projection"])
    receipt["resolver_devkit_revision"] = own_head
    receipt["released"] = True
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    return receipt


# ---------------------------------------------------------------------------
# Candidate declaration validation (sealed Profile B fixture outcome 5 /
# Profile K counterexample; the minimal WR-2 form of the architecture
# section 5.1 overlay: a candidate's OWN declaration is validated against
# the base lock; full per-node revision overlays arrive with WR-3)
# ---------------------------------------------------------------------------

CANDIDATE_SCHEMA = "qiven-workspace-candidate-receipt-v1"


def validate_candidate(control: Path, manifest_path: Path) -> dict:
    """Validate a candidate dependency declaration against the base lock.

    The base graph must itself validate (its receipt is included); the
    candidate never reuses the base proof — every incoming contract and
    package edge of the candidate is checked against the lock's nodes and
    provisions, and a failure produces a candidate-specific typed receipt
    while the base receipt stays valid.
    """
    base = resolve(control, {}, None, "shadow", None)
    lock = schemas.load_strict(control / "workspace.lock.json")

    try:
        candidate = schemas.load_strict(manifest_path)
    except FileNotFoundError as error:
        raise ResolutionError(
            "WorkspaceNotFound", f"candidate manifest not found: {error}"
        ) from error
    errors = schemas.validate(candidate, schemas.load_schema("qiven-dependencies-v1.schema.json"))
    if errors:
        first = errors[0]
        raise ResolutionError(
            "SchemaViolation",
            f"candidate manifest: {first.error_type} at {first.path}: {first.message}",
        ) from first
    if candidate["repository"] in lock["nodes"]:
        raise ResolutionError(
            "CandidateRejected",
            f"candidate {candidate['repository']} is already a base lock node; "
            "an overlay for an existing node is WR-3 scope, not candidate admission",
        )

    records: dict[str, dict] = {}
    for node_id, node in lock["nodes"].items():
        record, _census = _load_declaration(node_id, node, control, None)
        records[node_id] = record
    provisions = {
        node_id: {p["contract"] for p in record.get("provides", [])}
        for node_id, record in records.items()
    }
    provided_packages = {
        node_id: {pkg for p in record.get("provides", []) for pkg in p.get("packages", [])}
        for node_id, record in records.items()
    }

    failures: list[dict] = []
    for dep in candidate.get("dependencies", []):
        edge = f"{candidate['repository']}->{dep['id']}"
        if dep["id"] not in lock["nodes"]:
            failures.append({
                "type": "UnknownNode", "consumer_edge": edge, "node": dep["id"],
                "message": f"edge {edge}: candidate requires a provider absent from the base lock",
            })
            continue
        contract = dep.get("contract")
        if contract is not None and contract not in provisions[dep["id"]]:
            failures.append({
                "type": "DependencyConflict", "consumer_edge": edge, "node": dep["id"],
                "message": f"edge {edge}: candidate requires {contract}; "
                           f"provider provides {sorted(provisions[dep['id']]) or ['<nothing>']}",
            })
        for package in dep.get("packages", []):
            if package not in provided_packages[dep["id"]]:
                failures.append({
                    "type": "DependencyConflict", "consumer_edge": edge, "node": dep["id"],
                    "message": f"edge {edge}: package {package} not provided by {dep['id']}",
                })
    return {
        "schema": CANDIDATE_SCHEMA,
        "candidate_repository": candidate["repository"],
        "base_generation": base["workspace_generation"],
        "base_graph_valid": True,
        "candidate_validated": not failures,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# WR-3: per-node revision overlays, the CMake adapter, and the lock
# transaction helper (accepted architecture doc 01 sections 4 and 5.1;
# doc 02 stage WR-3). The overlay NEVER mutates the control tree: it
# derives the effective graph (base lock plus clean candidate nodes),
# validates every edge against it, and reports a distinct effective
# generation — an exact-revision overlay, never a float.
# ---------------------------------------------------------------------------

OVERLAY_SCHEMA = "qiven-workspace-overlay-receipt-v1"
ADAPTER_SCHEMA = "qiven-workspace-adapter-receipt-v1"
LOCK_UPDATE_SCHEMA = "qiven-workspace-lock-update-receipt-v1"
ADAPTER_CMAKE_SCHEMA_TAG = "qiven-workspace-adapter-cmake-v1"


def _overlay_node(node_id: str, checkout: Path, strict_clean: bool) -> tuple[dict, dict]:
    """Read a candidate node's identity + repository-owned declaration at
    its HEAD. The declaration comes from the candidate's OWN tree, never
    from the base lock's record (WG-4 / section 5.1)."""
    head = _git(["rev-parse", "HEAD"], checkout)
    tree = _git(["rev-parse", "HEAD^{tree}"], checkout)
    dirty = _git(["status", "--porcelain"], checkout)
    if dirty and strict_clean:
        raise ResolutionError("DirtyDependency", f"{node_id} overlay worktree is dirty", node=node_id)
    try:
        blob_text = _git(["show", f"{head}:.qiven/dependencies.json"], checkout)
    except ResolutionError as error:
        raise ResolutionError(
            "MissingDeclaration",
            f"{node_id}: overlay has no .qiven/dependencies.json at {head}",
            node=node_id,
        ) from error
    try:
        record = schemas.parse_strict(blob_text)
    except (schemas.SchemaError, json.JSONDecodeError) as error:
        raise ResolutionError("MissingDeclaration", f"{node_id}: {error}") from error
    if record.get("repository") != node_id:
        raise ResolutionError(
            "DeclarationRepositoryMismatch",
            f"{node_id}: manifest declares repository {record.get('repository')}",
            node=node_id,
        )
    errors = schemas.validate(record, schemas.load_schema("qiven-dependencies-v1.schema.json"))
    if errors:
        first = errors[0]
        raise ResolutionError(
            "MissingDeclaration",
            f"{node_id} declaration: {first.error_type} at {first.path}: {first.message}",
            node=node_id,
        ) from first
    node = {
        "commit": head,
        "tree": tree,
        "declaration": {
            "origin": "repository-manifest",
            "path": ".qiven/dependencies.json",
            "digest": declaration_digest(record),
            "shadow_only": False,
        },
    }
    if node_id in ("qiven-toolchain-win", "qiven-third-party-win"):
        node["platform"] = "windows"
    state = {"state": "dirty-labeled" if dirty else "clean"}
    return node, state


def _effective_lock(lock: dict, overlays: dict[str, Path], strict_clean: bool) -> tuple[dict, dict]:
    """Apply candidate overlays onto a deep copy of the lock; return the
    effective lock and per-overlay checkout states. An overlay whose
    checkout is ALREADY at the locked commit is an identity-preserving
    no-op: the locked node (with its cache-bound declaration) stands
    unchanged, so a no-op overlay derives the base generation."""
    import copy
    effective = copy.deepcopy(lock)
    overlay_states: dict[str, dict] = {}
    for node_id, checkout_path in sorted(overlays.items()):
        if node_id not in effective["nodes"]:
            raise ResolutionError(
                "UnknownNode", f"overlay node {node_id} is not a base lock node", node=node_id
            )
        checkout = Path(checkout_path).resolve()
        head = _git(["rev-parse", "HEAD"], checkout)
        dirty = _git(["status", "--porcelain"], checkout)
        if dirty and strict_clean:
            raise ResolutionError("DirtyDependency", f"{node_id} overlay worktree is dirty", node=node_id)
        if head == effective["nodes"][node_id]["commit"]:
            overlay_states[node_id] = {
                "id": node_id, "state": "dirty-labeled" if dirty else "clean",
                "commit": head, "overlay_kind": "already-locked",
            }
            continue
        node, _state = _overlay_node(node_id, checkout, strict_clean)
        effective["nodes"][node_id] = node
        overlay_states[node_id] = {"id": node_id, "state": "dirty-labeled" if dirty else "clean",
                                   "commit": node["commit"], "overlay_kind": "candidate"}
    return effective, overlay_states


def _validate_effective(control: Path, manifest: dict, effective_lock: dict,
                        checkouts: dict[str, str], workspace_root: Path | None,
                        mode: str, trust_policy: Path | None) -> dict:
    """Full-graph validation over the effective lock (shared by overlay /
    adapter / lock-update): identity, declarations, edges, conflicts."""
    trust = _check_trust(control, mode, trust_policy)
    records: dict[str, tuple[dict, bool]] = {}
    node_receipts: list[dict] = []
    strict_clean = mode == "authoritative"
    for node_id, node in sorted(effective_lock["nodes"].items()):
        checkout = node_checkout(node_id, checkouts, workspace_root)
        checkout_state = None
        if checkout is not None:
            checkout_state = _verify_checkout(node_id, checkout, node, strict_clean)
        record, census_origin = _load_declaration(node_id, node, control, checkout)
        records[node_id] = (record, census_origin)
        node_receipts.append({
            "id": node_id,
            "commit": node["commit"],
            "tree": node["tree"],
            "declaration_digest": node["declaration"]["digest"],
            "declaration_origin": node["declaration"]["origin"],
            "checkout_state": checkout_state["state"] if checkout_state else "not-materialized",
        })
    edges = _check_edges(records, effective_lock)
    conflicts = _baseline_conflicts(records, effective_lock)
    if conflicts and mode == "authoritative":
        first = conflicts[0]
        raise ResolutionError(
            "BaselineConflict",
            f"{first['consumer_edge']}: legacy pin {first['legacy_pin']} != locked {first['locked_node']}",
            consumer_edge=first["consumer_edge"],
        )
    any_census = any(census for _record, census in records.values())
    generation = generation_digest(manifest, {k: v for k, v in effective_lock.items() if k != "generation"})
    receipt = {
        "workspace_id": effective_lock["workspace_id"],
        "workspace_control_revision": _git(["rev-parse", "HEAD"], control) if (control / ".git").exists() else None,
        "workspace_generation": generation,
        "mode": mode,
        "trusted": trust.get("trusted", False),
        "shadow_only": any_census or mode != "authoritative",
        "legacy_resolution_used": True,
        "nodes": node_receipts,
        "edges": edges,
        "baseline_conflicts": conflicts,
    }
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    return receipt


def resolve_overlay(control: Path, overlays: dict[str, Path], mode: str,
                    trust_policy: Path | None, checkouts: dict[str, str],
                    workspace_root: Path | None) -> dict:
    """The WR-3 section 5.1 overlay: validate base lock plus explicit clean
    candidate revisions; emit the distinct effective generation."""
    manifest, lock = _load_validated(control)
    base_generation = _check_generation(manifest, lock)
    effective, overlay_states = _effective_lock(lock, overlays, mode == "authoritative")
    merged_checkouts = dict(checkouts)
    merged_checkouts.update({node_id: str(path) for node_id, path in overlays.items()})
    receipt = _validate_effective(control, manifest, effective, merged_checkouts, workspace_root, mode, trust_policy)
    receipt["schema"] = OVERLAY_SCHEMA
    receipt["operation"] = "overlay"
    receipt["base_generation"] = base_generation
    receipt["effective_generation"] = receipt.pop("workspace_generation")
    receipt["overlays"] = overlay_states
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    return receipt


def _projection_with_records(repo_id: str, records: dict[str, tuple[dict, bool]]) -> list[str]:
    seen: set[str] = set()
    stack = [repo_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        record = records[current][0]
        for dep in record.get("dependencies", []):
            if dep.get("kind") in ("first-party-source", "third-party-singleton"):
                stack.append(dep["id"])
    return sorted(seen)


def _sanitize_id(node_id: str) -> str:
    return node_id.replace("-", "_")


def _adapter_cmake(target_id: str, generation: str, projection_digest: str,
                   mode: str, control_revision: str | None,
                   providers: list[dict]) -> str:
    """Deterministic CMake adapter (doc 01 section 4): CMake receives the
    resolved roots; it never resolves. Anti-spoof: a provider target that
    exists without the workspace materialization guard is a hard error —
    the if(NOT TARGET) validation-suppression class dies here."""
    lines: list[str] = []
    lines.append(f"# {ADAPTER_CMAKE_SCHEMA_TAG} — generated by the qiven workspace resolver; do not edit")
    lines.append(f"# target: {target_id}")
    lines.append(f"# workspace_generation: {generation}")
    lines.append(f"# operation_projection_digest: {projection_digest}")
    lines.append(f"# mode: {mode}")
    if control_revision:
        lines.append(f"# workspace_control_revision: {control_revision}")
    lines.append("")
    lines.append(f'set(QIVEN_WORKSPACE_GENERATION "{generation}")')
    lines.append(f'set(QIVEN_WORKSPACE_OPERATION_PROJECTION_DIGEST "{projection_digest}")')
    for provider in providers:
        pid = _sanitize_id(provider["id"])
        lines.append(f'set(QIVEN_WORKSPACE_PROVIDER_ROOT_{pid} "{provider["root"]}")')
        lines.append(f'set(QIVEN_WORKSPACE_PROVIDER_COMMIT_{pid} "{provider["commit"]}")')
        for contract in provider["contracts"]:
            lines.append(f'set(QIVEN_WORKSPACE_PROVIDER_CONTRACT_{pid} "{contract}")')
    lines.append("")
    lines.append("if(NOT COMMAND qiven_workspace_materialize)")
    lines.append("    function(qiven_workspace_materialize provider_id)")
    lines.append("        get_property(_qiven_ws_done GLOBAL PROPERTY \"_qiven_workspace_${provider_id}_materialized\")")
    lines.append("        if(_qiven_ws_done)")
    lines.append("            return()")
    lines.append("        endif()")
    lines.append("        # anti-spoof: a pre-existing target NOT created by this adapter is a")
    lines.append("        # hard failure — target presence never satisfies a workspace edge")
    lines.append("        foreach(_qiven_ws_target ${QIVEN_WORKSPACE_PROVIDER_TARGETS_${provider_id}})")
    lines.append("            if(TARGET ${_qiven_ws_target})")
    lines.append('                message(FATAL_ERROR "qiven workspace: target ${_qiven_ws_target} exists but was not materialized by the workspace adapter (target-presence spoof; ADR-0052 doc 02 WR-3)")')
    lines.append("            endif()")
    lines.append("        endforeach()")
    lines.append('        add_subdirectory("${QIVEN_WORKSPACE_PROVIDER_ROOT_${provider_id}}" "${CMAKE_BINARY_DIR}/qiven-workspace/${provider_id}" EXCLUDE_FROM_ALL)')
    lines.append('        set_property(GLOBAL PROPERTY "_qiven_workspace_${provider_id}_materialized" TRUE)')
    lines.append("    endfunction()")
    lines.append("endif()")
    for provider in providers:
        pid = _sanitize_id(provider["id"])
        lines.append(f'set(QIVEN_WORKSPACE_PROVIDER_TARGETS_{pid} "{" ".join(provider["targets"])}")')
    lines.append("")
    return "\n".join(lines)


def emit_adapter(control: Path, repo_id: str, repo_checkout: Path, mode: str,
                 trust_policy: Path | None, checkouts: dict[str, str],
                 workspace_root: Path | None, out_dir: Path | None) -> dict:
    """Validate the effective graph for the target's operation closure and
    emit the CMake adapter that supplies the resolved provider roots
    (QIVEN_RESOLUTION_FILE). The target itself is bound to its HEAD; a
    dirty target stays compile-legal in shadow mode, labeled."""
    manifest, lock = _load_validated(control)
    _check_generation(manifest, lock)
    effective, overlay_states = _effective_lock(
        lock, {repo_id: repo_checkout}, mode == "authoritative")
    if overlay_states[repo_id]["state"] == "dirty-labeled" and mode == "authoritative":
        raise ResolutionError(
            "DirtyDependency", f"{repo_id} target worktree is dirty (authoritative)", node=repo_id
        )
    merged_checkouts = dict(checkouts)
    merged_checkouts[repo_id] = str(repo_checkout)
    # full-graph validation materializes NOTHING beyond the explicit
    # checkouts (doc 01 section 5: worktrees only for the operation
    # closure; unrelated sibling checkouts are not this operation's
    # concern — declarations come from the census/cache)
    receipt = _validate_effective(control, manifest, effective, merged_checkouts, None, mode, trust_policy)

    # rebuild records for the projection walk (validated above; no re-read)
    records: dict[str, tuple[dict, bool]] = {}
    for node_id, node in effective["nodes"].items():
        checkout = node_checkout(node_id, merged_checkouts, None)
        record, census_origin = _load_declaration(node_id, node, control, checkout)
        records[node_id] = (record, census_origin)
    projection = _projection_with_records(repo_id, records)

    providers: list[dict] = []
    target_record = records[repo_id][0]
    for dep in target_record.get("dependencies", []):
        if dep.get("kind") not in ("first-party-source", "third-party-singleton"):
            continue
        provider_id = dep["id"]
        if provider_id not in projection:
            continue
        checkout = node_checkout(provider_id, merged_checkouts, workspace_root)
        if checkout is None:
            raise ResolutionError(
                "RevisionUnavailable",
                f"provider {provider_id} has no checkout for adapter materialization",
                node=provider_id,
            )
        # operation-closure materialization IS verified: exact commit,
        # clean tree in authoritative mode (doc 01 section 5 step 6)
        provider_state = _verify_checkout(
            provider_id, checkout, effective["nodes"][provider_id], mode == "authoritative")
        provider_record = records[provider_id][0]
        contracts = sorted(p["contract"] for p in provider_record.get("provides", []))
        targets = sorted({t for p in provider_record.get("provides", []) for t in p.get("targets", [])})
        providers.append({
            "id": provider_id,
            "root": str(checkout),
            "commit": effective["nodes"][provider_id]["commit"],
            "contracts": contracts,
            "targets": targets,
            "checkout_state": provider_state["state"],
        })

    projection_record = [
        {"id": node_id, "commit": effective["nodes"][node_id]["commit"]} for node_id in projection
    ]
    projection_digest = content_digest(projection_record)
    generation = receipt["workspace_generation"]
    control_revision = receipt["workspace_control_revision"]
    cmake_text = _adapter_cmake(repo_id, generation, projection_digest, mode, control_revision, providers)
    adapter_sha = "sha256:" + hashlib.sha256(cmake_text.encode("utf-8")).hexdigest()

    out_root = out_dir or (control.parent / ".generated-temp" / "workspace" / generation.split(":", 1)[1][:16] / repo_id)
    out_root.mkdir(parents=True, exist_ok=True)
    adapter_path = out_root / "adapter.cmake"
    adapter_path.write_text(cmake_text, encoding="utf-8", newline="\n")

    receipt["schema"] = ADAPTER_SCHEMA
    receipt["operation"] = "adapter"
    receipt["target_repository"] = repo_id
    receipt["target_revision"] = effective["nodes"][repo_id]["commit"]
    receipt["operation_projection"] = projection_record
    receipt["operation_projection_digest"] = projection_digest
    receipt["providers"] = providers
    receipt["adapter_path"] = str(adapter_path)
    receipt["adapter_sha256"] = adapter_sha
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    return receipt


def _hash_object_stdin(text: str) -> str:
    # bytes payload: text-mode stdin would newline-translate on Windows and
    # silently change the blob identity
    try:
        result = subprocess.run(
            ["git", "hash-object", "--stdin"], input=text.encode("utf-8"),
            capture_output=True, timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ResolutionError("RevisionUnavailable", f"git hash-object failed: {error}") from error
    if result.returncode != 0:
        raise ResolutionError(
            "RevisionUnavailable", f"git hash-object: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode("ascii").strip()


def lock_update(control: Path, moves: dict[str, Path], mode: str,
                trust_policy: Path | None) -> dict:
    """Compute (never write) the next lock after moving nodes to exact
    candidate revisions with repository-owned declarations — the WR-3
    cutover transaction helper. The emitted declaration cache makes the
    moved nodes' declaration objects available to full-graph validation
    without a checkout of every node (Profile A/I). The session writes
    the emitted lock + cache into the control tree and commits them as
    one auditable transaction (--apply)."""
    manifest, lock = _load_validated(control)
    base_generation = _check_generation(manifest, lock)
    effective, overlay_states = _effective_lock(lock, moves, mode == "authoritative")

    declaration_cache: list[dict] = []
    cache_files: dict[str, str] = {}
    for node_id in sorted(moves):
        checkout = Path(moves[node_id]).resolve()
        head = _git(["rev-parse", "HEAD"], checkout)
        manifest_text = _git(["show", f"{head}:.qiven/dependencies.json"], checkout)
        cache_path = f"declarations/{node_id}.json"
        blob = _hash_object_stdin(manifest_text)
        effective["nodes"][node_id]["declaration"].update({
            "path": cache_path,
            "blob": blob,
        })
        declaration_cache.append({"node": node_id, "path": cache_path, "blob": blob})
        cache_files[cache_path] = manifest_text

    merged_checkouts = {node_id: str(path) for node_id, path in moves.items()}
    receipt = _validate_effective(control, manifest, effective, merged_checkouts, None, mode, trust_policy)
    new_generation = generation_digest(manifest, {k: v for k, v in effective.items() if k != "generation"})
    effective["generation"] = new_generation

    changed = [
        {
            "id": node_id,
            "from_commit": lock["nodes"][node_id]["commit"],
            "to_commit": effective["nodes"][node_id]["commit"],
            "declaration_origin": "repository-manifest",
        }
        for node_id in sorted(moves)
    ]
    receipt["schema"] = LOCK_UPDATE_SCHEMA
    receipt["operation"] = "lock-update"
    receipt["base_generation"] = base_generation
    receipt["new_generation"] = new_generation
    receipt["changed_nodes"] = changed
    receipt["declaration_cache"] = declaration_cache
    receipt["new_lock"] = effective
    receipt["graph_receipt_digest"] = content_digest(
        {k: v for k, v in receipt.items() if k != "graph_receipt_digest"}
    )
    receipt["_cache_files"] = cache_files  # consumed by --apply; not part of the receipt identity
    return receipt


# ---------------------------------------------------------------------------
# Golden vectors
# ---------------------------------------------------------------------------

def run_golden_vectors() -> list[str]:
    vectors = schemas.load_strict(DEVKIT_ROOT / "docs" / "schemas" / "workspace-generation-golden-vectors.json")
    failures = []
    for vector in vectors.get("jcs_vectors", []):
        expected = vector["expected"].encode("utf-8")
        got_a = canonical_bytes(vector["value"])
        got_b = canonical_bytes_reference(vector["value"])
        if got_a != expected or got_b != expected:
            failures.append(f"jcs {vector['id']}: A={got_a!r} B={got_b!r} expected={expected!r}")
    for vector in vectors.get("generation_vectors", []):
        expected = vector["expected_generation"]
        lock_sg = {k: v for k, v in vector["lock"].items() if k != "generation"}
        got = generation_digest(vector["manifest"], lock_sg)
        if got != expected:
            failures.append(f"generation {vector['id']}: {got} != {expected}")
        if "expected_declaration_digest" in vector:
            got_decl = declaration_digest(vector["declaration"])
            if got_decl != vector["expected_declaration_digest"]:
                failures.append(f"declaration {vector['id']}: {got_decl} != {vector['expected_declaration_digest']}")
    return failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _emit(receipt: dict, as_json: bool, out: Path | None) -> None:
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if as_json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print("[ OK ] workspace resolution")
        print(f"       generation {receipt['workspace_generation']}")
        print(f"       mode {receipt['mode']} shadow_only={receipt['shadow_only']}")
        for conflict in receipt.get("baseline_conflicts", []):
            print(f"       [SPLIT] {conflict['consumer_edge']}: pin {conflict['legacy_pin'][:12]} != lock {conflict['locked_node'][:12]}")
        if out is not None:
            print(f"       receipt {out}")


def _default_out(control: Path, operation: str) -> Path:
    stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    return control.parent / ".generated-temp" / "workspace-resolver" / f"{stamp}-{operation}" / "receipt.json"


def _parse_node_map(pairs: list[str], label: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ResolutionError("SchemaViolation", f"--{label} expects NODE=CHECKOUT, got {pair!r}")
        node_id, path = pair.split("=", 1)
        out[node_id.strip()] = Path(path.strip()).resolve()
    if not out:
        raise ResolutionError("SchemaViolation", f"--{label} requires at least one NODE=CHECKOUT")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="qiven workspace resolver (WR-1, shadow read-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target):
        target.add_argument("--control", required=True, help="workspace control checkout")
        target.add_argument("--checkouts", help="JSON mapping of node id -> checkout path")
        target.add_argument("--workspace-root", help="workspace root for locator-based checkouts")
        target.add_argument("--mode", choices=["shadow", "authoritative"], default="shadow")
        target.add_argument("--trust-policy", help="admitted control revisions (authoritative)")
        target.add_argument("--json", action="store_true", help="machine output")
        target.add_argument("--out", help="receipt output file")

    validate_cmd = sub.add_parser("validate")
    add_common(validate_cmd)

    preflight_cmd = sub.add_parser("preflight")
    add_common(preflight_cmd)
    preflight_cmd.add_argument("--devkit", required=True, help="locked Devkit checkout")

    candidate_cmd = sub.add_parser("candidate")
    candidate_cmd.add_argument("--control", required=True, help="workspace control checkout")
    candidate_cmd.add_argument("--manifest", required=True, help="candidate dependencies-v1 file")
    candidate_cmd.add_argument("--json", action="store_true", help="machine output")

    overlay_cmd = sub.add_parser("overlay")
    add_common(overlay_cmd)
    overlay_cmd.add_argument("--overlay", action="append", required=True,
                             metavar="NODE=CHECKOUT",
                             help="candidate node overlay (repeatable)")

    adapter_cmd = sub.add_parser("adapter")
    add_common(adapter_cmd)
    adapter_cmd.add_argument("--repo", required=True, help="target repository id")
    adapter_cmd.add_argument("--repo-checkout", required=True, help="target repository checkout")
    adapter_cmd.add_argument("--out-dir", help="adapter output directory "
                           "(default <workspace>/.generated-temp/workspace/<gen>/<repo>)")

    lock_cmd = sub.add_parser("lock-update")
    add_common(lock_cmd)
    lock_cmd.add_argument("--move", action="append", required=True,
                          metavar="NODE=CHECKOUT",
                          help="move a lock node to the checkout's exact clean HEAD (repeatable)")
    lock_cmd.add_argument("--apply", action="store_true",
                          help="write the new lock + declaration cache into the control tree "
                               "(the session then commits the control repository)")

    sub.add_parser("golden-vectors")

    args = parser.parse_args(argv)

    try:
        if args.command == "golden-vectors":
            failures = run_golden_vectors()
            if failures:
                for failure in failures:
                    print(f"[FAIL] {failure}")
                return 1
            print("[ OK ] golden vectors")
            return 0

        control = Path(args.control).resolve()
        checkouts: dict[str, str] = {}
        if args.checkouts:
            checkouts = schemas.load_strict(Path(args.checkouts).resolve())
        workspace_root = Path(args.workspace_root).resolve() if args.workspace_root else None
        trust_policy = Path(args.trust_policy).resolve() if args.trust_policy else None

        if args.command == "validate":
            receipt = resolve(control, checkouts, workspace_root, args.mode, trust_policy)
        elif args.command == "candidate":
            receipt = validate_candidate(control, Path(args.manifest).resolve())
            print(json.dumps(receipt, sort_keys=True) if args.json else json.dumps(receipt, indent=2, sort_keys=True))
            return 0 if receipt["candidate_validated"] else 1
        elif args.command == "overlay":
            overlays = _parse_node_map(args.overlay, "overlay")
            receipt = resolve_overlay(control, overlays, args.mode, trust_policy, checkouts, workspace_root)
        elif args.command == "adapter":
            receipt = emit_adapter(control, args.repo, Path(args.repo_checkout).resolve(),
                                   args.mode, trust_policy, checkouts, workspace_root,
                                   Path(args.out_dir).resolve() if args.out_dir else None)
        elif args.command == "preflight":
            devkit = Path(args.devkit).resolve()
            receipt = preflight(control, devkit, args.mode, trust_policy, checkouts)
        else:  # lock-update
            moves = _parse_node_map(args.move, "move")
            receipt = lock_update(control, moves, args.mode, trust_policy)
            if args.apply:
                (control / "workspace.lock.json").write_text(
                    json.dumps(receipt["new_lock"], indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
                for cache_path, cache_text in receipt.pop("_cache_files").items():
                    target = control / cache_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(cache_text, encoding="utf-8", newline="\n")
                receipt["applied_to"] = str(control)
            else:
                receipt.pop("_cache_files", None)
        out = Path(args.out) if args.out else _default_out(control, args.command)
        _emit(receipt, args.json, out)
        return 0
    except ResolutionError as error:
        payload = {"schema": ERROR_SCHEMA, "error": error.as_dict()}
        print(json.dumps(payload, sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1
    except json.JSONDecodeError as error:
        # safety net: malformed JSON anywhere in the control tree is typed,
        # never a bare traceback through the CLI
        payload = {"schema": ERROR_SCHEMA, "error": {
            "type": "SchemaViolation", "message": f"malformed JSON: {error}"}}
        print(json.dumps(payload, sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1
    except schemas.SchemaError as error:
        payload = {"schema": ERROR_SCHEMA, "error": error.as_dict()}
        print(json.dumps(payload, sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
