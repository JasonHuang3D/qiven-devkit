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
    return key.encode("utf-16-be")


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
    only owns the UTF-16 key ordering and structural composition itself.
    """
    if value is None or isinstance(value, (bool, int, str)):
        dumps = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return dumps.encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical_bytes_reference(item) for item in value) + b"]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=_sort_key_utf16):
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
    try:
        manifest = schemas.load_strict(control / "workspace.json")
        lock = schemas.load_strict(control / "workspace.lock.json")
    except schemas.SchemaError as error:
        raise ResolutionError(error.error_type, error.message) from error
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
        if checkout is None:
            raise ResolutionError("RevisionUnavailable", f"{node_id}: checkout needed for manifest read")
        blob_text = _git(["show", f"{node['commit']}:.qiven/dependencies.json"], checkout)
        try:
            record = schemas.parse_strict(blob_text)
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
        else:
            devkit = Path(args.devkit).resolve()
            receipt = preflight(control, devkit, args.mode, trust_policy, checkouts)
        out = Path(args.out) if args.out else _default_out(control, args.command)
        _emit(receipt, args.json, out)
        return 0
    except ResolutionError as error:
        payload = {"schema": ERROR_SCHEMA, "error": error.as_dict()}
        print(json.dumps(payload, sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1
    except schemas.SchemaError as error:
        payload = {"schema": ERROR_SCHEMA, "error": error.as_dict()}
        print(json.dumps(payload, sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
