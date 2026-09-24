"""Shadow resolution preflight and legacy-pin comparator (WR-2, ADR-0052).

Runs Workspace Resolution in shadow mode against the control lock, then
extracts every LEGACY revision selection the consumer repositories
actually enforce today (CMake pinned-SHA variables, the context
devkit_pin, managed operator snapshots) and compares them with the lock
node selections, per dependency class. Emits a machine-readable shadow
report (doc 02 section 2 WR-2): per-class equality or typed shadow
conflict — a mismatch fails THAT class's migration gate and never
invalidates an unrelated legacy operation.

Exit codes: 0 report produced (shadow conflicts are per-class gates,
not run failures) / 1 typed tool failure / 2 usage or environment error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workspace_resolver as wr  # noqa: E402
import workspace_schemas as ws  # noqa: E402

REPORT_SCHEMA = "qiven-workspace-shadow-report-v1"
ERROR_SCHEMA = "qiven-workspace-shadow-error-v1"

# Legacy pin extraction: variable-name-keyed, deterministic (verified against
# the live consumer CMakeLists 2026-09-25: QIVEN_FOUNDATION_PINNED_SHA,
# QIVEN_DRAFT_PINNED_SHA, QIVEN_THIRD_PARTY_PIN).
_PIN_VARIABLES: dict[str, str] = {
    "QIVEN_FOUNDATION_PINNED_SHA": "qiven-foundation",
    "QIVEN_DRAFT_PINNED_SHA": "qiven-context-draft",
    "QIVEN_THIRD_PARTY_PIN": "qiven-third-party-win",
}
_PIN_LINE = re.compile(
    r"set\(\s*([A-Z0-9_]+)\s+\"([0-9a-f]{40})\"\s*\)", re.IGNORECASE
)

# Managed operator snapshots: operator.json without a devkit_pin field; the
# census records their mechanism (template 0.1.9 custody rollout) and no
# mechanical git identity is carried inside the consumer repository.
_MANAGED_SNAPSHOT_REPOS = [
    "qiven-runtime",
    "qiven-foundation",
    "qiven-math",
    "qiven-context-draft",
]

# Census temporary records: replacement stage per node class + the hard
# WR-8 removal gate (doc 02 WR-2 exit bullet 3).
_REPLACEMENT_STAGE = {
    "qiven-foundation": "WR-3",
    "qiven-context-draft": "WR-4",
    "qiven-toolchain-win": "WR-5",
    "qiven-third-party-win": "WR-5",
    "qiven-devkit": "WR-6",
    "qiven-context": "WR-6",
    "qiven-runtime": "WR-3",
    "qiven-math": "WR-3",
    "qiven-docs": "WR-7",
}

_CONSUMERS = [
    "qiven-runtime",
    "qiven-context-draft",
    "qiven-math",
    "qiven-context",
    "qiven-foundation",
]


class ShadowError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def extract_cmake_pins(repo_root: Path) -> dict[str, str]:
    """Return provider-id -> pinned sha from a consumer CMakeLists.txt."""
    cmake = repo_root / "CMakeLists.txt"
    if not cmake.is_file():
        return {}
    pins: dict[str, str] = {}
    for match in _PIN_LINE.finditer(cmake.read_text(encoding="utf-8", errors="replace")):
        variable, sha = match.group(1).upper(), match.group(2)
        provider = _PIN_VARIABLES.get(variable)
        if provider is None:
            # An unknown pinned variable is a typed extraction failure, never
            # a silently skipped edge (an unparsed pin would fake equality).
            raise ShadowError(
                "PinExtractionAmbiguous",
                f"{repo_root.name}: unknown pin variable {variable} ({sha[:12]}); "
                "teach the extractor or remove the pin",
            )
        if provider in pins and pins[provider] != sha:
            raise ShadowError(
                "PinExtractionAmbiguous",
                f"{repo_root.name}: two different pins for {provider}",
            )
        pins[provider] = sha
    return pins


def extract_devkit_pin(repo_root: Path) -> str | None:
    operator = repo_root / ".qiven" / "operator.json"
    if not operator.is_file():
        return None
    try:
        config = json.loads(operator.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ShadowError("PinExtractionAmbiguous", f"{repo_root.name}: {error}") from error
    pin = config.get("devkit_pin")
    if pin is not None and not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise ShadowError("PinExtractionAmbiguous", f"{repo_root.name}: malformed devkit_pin")
    return pin


def collect_legacy_selections(workspace_root: Path) -> dict[str, list[dict[str, Any]]]:
    """provider-id -> list of {consumer, kind, selection} legacy facts."""
    legacy: dict[str, list[dict[str, Any]]] = {}
    for consumer in _CONSUMERS:
        repo_root = workspace_root / consumer
        if not repo_root.is_dir():
            continue
        for provider, sha in extract_cmake_pins(repo_root).items():
            legacy.setdefault(provider, []).append(
                {"consumer": consumer, "kind": "cmake-pin", "selection": sha}
            )
        devkit_pin = extract_devkit_pin(repo_root)
        if devkit_pin is not None:
            legacy.setdefault("qiven-devkit", []).append(
                {"consumer": consumer, "kind": "devkit-pin", "selection": devkit_pin}
            )
        elif (repo_root / ".qiven" / "operator.json").is_file() and consumer in _MANAGED_SNAPSHOT_REPOS:
            legacy.setdefault("qiven-devkit", []).append(
                {"consumer": consumer, "kind": "managed-snapshot", "selection": None}
            )
    return legacy


def compare_classes(lock: dict, legacy: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Per dependency class (keyed by provider node): equality vs typed shadow conflict."""
    classes: list[dict[str, Any]] = []
    providers = sorted(set(lock["nodes"]) | set(legacy))
    for provider in providers:
        node = lock["nodes"].get(provider)
        entries = legacy.get(provider, [])
        if node is None:
            classes.append({
                "class": provider,
                "verdict": "unknown-node",
                "cutover_eligible": False,
                "disposition": "resolver UnknownNode class; not a migration class",
                "legacy_selections": entries,
                "locked_selection": None,
            })
            continue
        locked_commit = node["commit"]
        pinned = [e for e in entries if e["selection"] is not None]
        snapshots = [e for e in entries if e["kind"] == "managed-snapshot"]
        if not entries:
            verdict = "no-legacy-selection"
            detail = "no consumer-local pin exists for this class (discovery-only mechanism)"
            eligible = False
            disposition = f"{_REPLACEMENT_STAGE.get(provider, 'WR-?')} migration replaces the mechanism"
        elif all(e["selection"] == locked_commit for e in pinned) and not snapshots:
            verdict = "equality"
            detail = "every legacy pin equals the locked selection"
            eligible = True
            disposition = f"cutover-eligible at {_REPLACEMENT_STAGE.get(provider, 'WR-?')}"
        elif snapshots and not pinned:
            verdict = "shadow-discrepancy"
            detail = "managed operator snapshots carry no mechanical git identity to compare"
            eligible = False
            disposition = "WR-6 disposition (doc 02 WR-2 exit: explicit discrepancy, never a global equivalence claim)"
        else:
            mismatches = [
                f"{e['consumer']}:{e['selection'][:12]}"
                for e in pinned
                if e["selection"] != locked_commit
            ]
            verdict = "shadow-conflict"
            detail = f"legacy pin(s) {' '.join(mismatches)} != locked {locked_commit[:12]}"
            eligible = False
            disposition = (
                "fails this class's migration gate only; WR-6 reconciliation target"
                if provider == "qiven-devkit"
                else f"fails this class's migration gate only; {_REPLACEMENT_STAGE.get(provider, 'WR-?')} target"
            )
        classes.append({
            "class": provider,
            "verdict": verdict,
            "cutover_eligible": eligible,
            "disposition": disposition,
            "detail": detail,
            "legacy_selections": entries,
            "locked_selection": locked_commit,
        })
    return classes


def build_report(control: Path, workspace_root: Path) -> dict[str, Any]:
    # Shadow graph validation: declarations from the control tree's census,
    # no checkout verification (a locator is not needed for pin comparison).
    receipt = wr.resolve(control, {}, None, "shadow", None)
    lock = ws.load_strict(control / "workspace.lock.json")
    legacy = collect_legacy_selections(workspace_root)
    classes = compare_classes(lock, legacy)

    temporary_records = [
        {
            "node": node_id,
            "declaration_origin": node["declaration"]["origin"],
            "provider_authored_guarantee": False,
            "replacement_stage": _REPLACEMENT_STAGE.get(node_id, "WR-?"),
            "wr8_removal_gate": True,
        }
        for node_id, node in sorted(lock["nodes"].items())
        if node["declaration"]["origin"] == "census-wr0"
    ]
    return {
        "schema": REPORT_SCHEMA,
        "workspace_generation": receipt["workspace_generation"],
        "mode": "shadow",
        "graph_receipt_digest": receipt["graph_receipt_digest"],
        "classes": classes,
        "equality_classes": [c["class"] for c in classes if c["verdict"] == "equality"],
        "conflict_classes": [
            c["class"] for c in classes if c["verdict"] in ("shadow-conflict", "shadow-discrepancy")
        ],
        "temporary_records": temporary_records,
        "census_provision_note": (
            "census-wr0 declarations are shadow-only baseline evidence, never "
            "provider-authored guarantees; each carries its replacement stage "
            "and the hard WR-8 removal gate"
        ),
        "ca1_note": (
            "CA-1 source lock does not exist yet; the CA-1 comparison clause is "
            "not applicable at WR-2 and is recorded, not skipped silently"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WR-2 shadow preflight + legacy-pin comparator")
    parser.add_argument("--control", required=True, help="workspace control checkout")
    parser.add_argument("--workspace-root", required=True, help="live workspace root (legacy pin extraction)")
    parser.add_argument("--json", action="store_true", help="machine output")
    parser.add_argument("--out", help="report output file")
    args = parser.parse_args(argv)

    control = Path(args.control).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    if not workspace_root.is_dir():
        print(f"[FAIL] workspace root not found: {workspace_root}", file=sys.stderr)
        return 2

    try:
        report = build_report(control, workspace_root)
    except (wr.ResolutionError, ShadowError) as error:
        kind = getattr(error, "kind", type(error).__name__)
        print(json.dumps({"schema": ERROR_SCHEMA, "error": {"type": kind, "message": str(error)}},
                         sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1
    except ws.SchemaError as error:
        print(json.dumps({"schema": ERROR_SCHEMA, "error": error.as_dict()},
                         sort_keys=True) if args.json else f"[FAIL] {error}")
        return 1

    out = Path(args.out) if args.out else (
        workspace_root / ".generated-temp" / "workspace-shadow"
        / f"{time.strftime('%Y-%m-%dT%H%M%SZ', time.gmtime())}-shadow" / "report.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("[ OK ] workspace shadow report (per-class verdicts)")
        print(f"       generation {report['workspace_generation']}")
        for entry in report["classes"]:
            marker = "EQ " if entry["verdict"] == "equality" else "CONF"
            print(f"       [{marker}] {entry['class']}: {entry['verdict']} -> {entry['disposition']}")
        print(f"       report {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
