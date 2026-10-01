"""Common Record v1: the minimal versioned producer envelope (ADR-0060 D3).

Frozen by the P0 implementation staging batch C (2026-10-02). The envelope
projects a versioned record over the ten D3 dimensions; ``payload``
references the producer's EXISTING native receipt/result whose own schema
stays authoritative - this module is additive mechanism, never a second
gate engine. No producer emits the record at the freeze revision (producers
begin at the B+D semantics + projection batch).

Public API:
    SCHEMA_VERSION, SCHEMA_PATH
    MODEL_VIEW_MAX_BYTES, CONTROL_IDENTITY_MAX_BYTES,
    INLINE_FINDINGS_MAX, BOUNDED_READ_MAX_BYTES   (declared budgets only)
    CommonRecord (+ section dataclasses)            construction helpers
    validate(record) -> list[dict]                  typed schema-rule findings
    serialize(record) -> str                        deterministic UTF-8 JSON
    read(text) -> ReadResult                        version gate + unknown-field note

EVOLUTION POLICY (ADR-0060 D7). v1 evolves additively only: a new OPTIONAL
field or a new enum value requires a dated note in the schema description;
removing/renaming/re-typing a field, or narrowing an enum, is a breaking
change requiring envelope version 2 plus an explicit versioned adapter.
Compatibility law, quoted and normative: "Bootstrap/launcher receipts and
public Operator/Workspace schemas retain their parseable contracts or
migrate through an explicit versioned adapter; P0 does not silently replace
JSON receipts with prose" and "ADR-0051 router denial/law carriers stay
byte-stable until an explicit public-carrier amendment".

Reader contract: unknown fields are TOLERATED and surfaced under the
``unknown_fields`` note (never silently dropped); a wrong ``schema_version``
is rejected with a typed ``SchemaVersionError`` naming both the observed and
the supported version.

Validation findings use the envelope's own finding shape (rule_id, location
with path + JSON pointer, actual, expected, contract_revision); rule ids are
prefixed ``common-record/`` and contract_revision is ``qiven-common-record-v1``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

_DEVKIT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = _DEVKIT_ROOT / "docs" / "schemas" / "qiven-common-record-v1.schema.json"

#: The envelope version; v1 is the literal integer 1.
SCHEMA_VERSION = 1

# --- frozen model-view budgets (ADR-0060 D3, quoted) ----------------------
# "entire serialized model-visible result 8 KiB UTF-8; control/identity/
# locator portion <= 2 KiB within it; <= 8 inline findings (also byte-budget
# bound); explicit bounded evidence read <= 16 KiB with cursor/range and EOF."
# DECLARED AND EXPORTED ONLY - enforcement is the B+D projection batch's job.

#: Entire serialized model-visible result: 8 KiB UTF-8.
MODEL_VIEW_MAX_BYTES = 8192
#: Control/identity/locator portion within the model view: <= 2 KiB.
CONTROL_IDENTITY_MAX_BYTES = 2048
#: Inline findings carried in the model view (also byte-budget bound): <= 8.
INLINE_FINDINGS_MAX = 8
#: Explicit bounded evidence read with cursor/range and EOF: <= 16 KiB.
BOUNDED_READ_MAX_BYTES = 16384

# --- exact enum vocabularies (ASCII-safe control syntax) ------------------
OBSERVATION_COHERENCE = ("coherent", "uncertain", "unavailable")
ADMISSION_STATES = ("accepted", "rejected", "not_evaluated")
COMPLETION_STATES = (
    "not_started",
    "running",
    "completed",
    "cancelled",
    "deadline_reached",
    "unknown",
)
DOMAIN_OUTCOMES = ("passed", "findings", "failed", "not_applicable", "unknown")
COVERAGE_COLLECTION = ("complete", "partial", "unknown")
EVIDENCE_COMPLETENESS = ("complete", "partial", "unknown")
NEXT_ACTIONS = ("NONE", "FIX", "NEXT", "DIAGNOSE", "RECONCILE")
SIDE_EFFECT_STATES = ("not_started", "completed", "in_progress", "unknown")

#: The explicit-absence sentinel for required dimensions without a value.
UNAVAILABLE = "unavailable"

CONTRACT_REVISION = "qiven-common-record-v1"

# --- class-aware next-action rules (ADR-0060 D3; B+D batch 2026-10-02) -----
# Quote-adaptive from D3, normative: "FIX/NEXT only where the mechanism
# mechanically knows the correction (invocation/schema/policy rejection);
# DIAGNOSE for unexpected compiler/linker/test/crash failures; RECONCILE
# for unknown side effects through the existing run/status handle, never
# automatic mutation replay. Exit-zero report mode with findings is not a
# PASS; a started/background operation is not completed; a deadline is
# terminal only when custody/termination observation establishes it; no
# exact-head gate proof from partial checks, uncertain observation or
# another revision's result. Domain failure is a normal tool outcome when
# transport/observation worked."
#
# The shared mapping table every producer maps through identically (the
# devkit-side producers import THIS function; context/workspace producers
# that cannot import the devkit before identity checks mirror this exact
# table with a pointer back to this constant - it is frozen data law, not
# shared code law, for them).

#: event token -> next_action.action (ASCII-safe control vocabulary).
NEXT_ACTION_EVENTS: dict[str, str] = {
    # clean completion, nothing to do
    "pass": "NONE",
    "completed-clean": "NONE",
    # the mechanism mechanically knows the correction (supported_by required)
    "invocation-rejected": "FIX",
    "policy-rejected": "FIX",
    "schema-rejected": "FIX",
    "finding-with-known-pointer": "FIX",
    # unexpected failure classes - classify before touching anything
    "unexpected-task-failure": "DIAGNOSE",
    "process-crash": "DIAGNOSE",
    "classify-before-retry": "DIAGNOSE",
    "operator-error": "DIAGNOSE",
    # a started/background operation is not completed - re-attach via the
    # existing status handle (supported_by names it)
    "operation-running": "NEXT",
    # unknown side effects - reconcile through the run/status handle,
    # never automatic mutation replay
    "unknown-side-effects": "RECONCILE",
    "lease-expired": "RECONCILE",
    "exit-unknown": "RECONCILE",
}


def next_action_for(event: str, supported_by: str | None = None) -> "NextAction":
    """Map one producer event token to the class-aware NextAction (D3).

    FIX/NEXT require ``supported_by`` (the mechanically-known correction /
    the status handle); passing neither is a loud invariant failure, never
    a guessed record. An unknown event token is likewise rejected - a
    producer must name its situation, not fall through to a default.
    """
    action = NEXT_ACTION_EVENTS.get(event)
    if action is None:
        raise ValueError(f"unknown next-action event: {event!r}")
    if action in ("FIX", "NEXT") and not (supported_by and supported_by.strip()):
        raise ValueError(f"event {event!r} maps to {action}: supported_by is required")
    return NextAction(action=action, supported_by=supported_by or None)

_SHA40_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_JSON_POINTER_RE = re.compile(r"(/([^/~]|~[01])*)*\Z")
_RECORD_KIND_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
_PRODUCER_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_RULE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*\Z")


def _is_int(value: Any) -> bool:
    """True only for real integers (bool is an int subclass; exclude it)."""
    return isinstance(value, int) and not isinstance(value, bool)


class CommonRecordError(Exception):
    """Base class for typed common-record failures."""


class SchemaVersionError(CommonRecordError):
    """A record whose schema_version is not the supported envelope version."""

    def __init__(self, observed: Any, supported: int = SCHEMA_VERSION) -> None:
        super().__init__(
            "common record schema_version mismatch: observed "
            f"{observed!r}, supported {supported!r}"
        )
        self.observed = observed
        self.supported = supported


class RecordDecodeError(CommonRecordError):
    """Input that is not a JSON object document (or has duplicate keys)."""


# --- construction helpers --------------------------------------------------

@dataclass
class Producer:
    id: str
    version: str


@dataclass
class Operation:
    id: str
    repository: str | None = None
    cwd: str | None = None
    invocation: str | None = None
    task: str | None = None
    gate: str | None = None
    selected_revision: str | None = None
    executing_revision: str | None = None
    workspace_generation: str | None = None


@dataclass
class Observation:
    coherence: str
    transport_classification: str | None = None


@dataclass
class Admission:
    state: str
    reason: str | None = None


@dataclass
class Completion:
    state: str


@dataclass
class DomainOutcome:
    outcome: str
    exit_code: int | str


@dataclass
class CoverageItem:
    name: str
    reason: str


@dataclass
class Coverage:
    collection: str
    executed: list[str] = field(default_factory=list)
    blocked: list[CoverageItem] = field(default_factory=list)
    not_executed: list[CoverageItem] = field(default_factory=list)


@dataclass
class FindingLocation:
    path: str
    json_pointer: str | None = None
    line: int | None = None


@dataclass
class Finding:
    rule_id: str
    location: FindingLocation
    actual: str
    expected: str
    contract_revision: str = CONTRACT_REVISION


@dataclass
class NextAction:
    action: str
    supported_by: str | None = None


@dataclass
class Evidence:
    locator: str
    completeness: str
    excerpt: str | None = None
    digest: str | None = None
    byte_count: int | None = None
    layout: str | None = None
    omitted_bytes: int | None = None
    omitted_count: int | None = None


@dataclass
class RetryState:
    side_effects: str
    reconciliation: str | None = None


@dataclass
class Payload:
    kind: str
    locator: str


@dataclass
class CommonRecord:
    record_kind: str
    producer: Producer
    operation: Operation
    observation: Observation
    admission: Admission
    completion: Completion
    domain_outcome: DomainOutcome
    coverage: Coverage
    next_action: NextAction
    retry_state: RetryState
    payload: Payload
    findings: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        doc = _drop_none(asdict(self))
        doc["schema_version"] = SCHEMA_VERSION
        return doc


def _drop_none(value: Any) -> Any:
    """Recursively remove None-valued mapping entries (omitted = absent)."""
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


def _as_record_dict(record: CommonRecord | dict[str, Any]) -> dict[str, Any]:
    if is_dataclass(record) and not isinstance(record, type):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    raise CommonRecordError(
        f"record must be a CommonRecord or dict, got {type(record).__name__}"
    )


# --- validation ------------------------------------------------------------

def _finding(rule_id: str, pointer: str, actual: Any, expected: str) -> dict[str, Any]:
    """A validation finding in the envelope's own five-element shape."""
    return {
        "rule_id": rule_id,
        "location": {"path": "<record>", "json_pointer": pointer},
        "actual": actual if isinstance(actual, str) else repr(actual),
        "expected": expected,
        "contract_revision": CONTRACT_REVISION,
    }


def _check_object(
    record: dict[str, Any], key: str, out: list[dict[str, Any]]
) -> dict[str, Any] | None:
    value = record.get(key)
    if not isinstance(value, dict):
        out.append(_finding("common-record/type", f"/{key}", value, "object"))
        return None
    return value


def _check_enum(
    section: dict[str, Any],
    key: str,
    pointer: str,
    allowed: tuple[str, ...],
    out: list[dict[str, Any]],
    required: bool = True,
) -> None:
    if key not in section:
        if required:
            out.append(
                _finding("common-record/required", pointer, "<missing>", f"'{key}'")
            )
        return
    value = section[key]
    if value not in allowed:
        out.append(
            _finding(
                "common-record/enum",
                pointer,
                value,
                "one of " + ", ".join(allowed),
            )
        )


def _check_string(
    section: dict[str, Any],
    key: str,
    pointer: str,
    out: list[dict[str, Any]],
    required: bool = True,
) -> None:
    if key not in section:
        if required:
            out.append(
                _finding("common-record/required", pointer, "<missing>", f"'{key}'")
            )
        return
    value = section[key]
    if not isinstance(value, str) or not value:
        out.append(_finding("common-record/type", pointer, value, "non-empty string"))


def _check_oneof_unavailable(
    value: Any, pointer: str, pattern: re.Pattern[str], shape: str, out: list[dict[str, Any]]
) -> None:
    if value == UNAVAILABLE:
        return
    if not isinstance(value, str) or pattern.match(value) is None:
        out.append(
            _finding("common-record/type", pointer, value, f"{shape} or 'unavailable'")
        )


def _finding_sort_key(finding: Any) -> tuple[str, str, str, Any]:
    """Canonical (rule_id, location) order key; tolerant of malformed input."""
    if isinstance(finding, dict):
        rule_id = str(finding.get("rule_id", ""))
        location = finding.get("location")
        if isinstance(location, dict):
            return (
                rule_id,
                str(location.get("path", "")),
                str(location.get("json_pointer", "")),
                location.get("line") if _is_int(location.get("line")) else 0,
            )
        return (rule_id, "", "", 0)
    return ("", "", "", 0)


def validate(record: CommonRecord | dict[str, Any]) -> list[dict[str, Any]]:
    """Validate against the v1 schema rules; return findings (empty = valid).

    Unknown fields are NOT findings (readers tolerate and surface them under
    the unknown_fields note). Budgets are declared, not enforced here.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(record, dict) and not (
        is_dataclass(record) and not isinstance(record, type)
    ):
        return [_finding("common-record/type", "", record, "object")]

    doc = _as_record_dict(record)
    if "schema_version" not in doc:
        out.append(
            _finding("common-record/required", "/schema_version", "<missing>", "'schema_version'")
        )
    elif not _is_int(doc["schema_version"]) or doc["schema_version"] != SCHEMA_VERSION:
        out.append(
            _finding(
                "common-record/schema-version",
                "/schema_version",
                doc["schema_version"],
                f"{SCHEMA_VERSION} (this reader's supported envelope version)",
            )
        )

    for key in (
        "record_kind",
        "producer",
        "operation",
        "observation",
        "admission",
        "completion",
        "domain_outcome",
        "coverage",
        "findings",
        "next_action",
        "evidence",
        "retry_state",
        "payload",
    ):
        if key not in doc:
            out.append(_finding("common-record/required", f"/{key}", "<missing>", f"'{key}'"))

    if "record_kind" in doc:
        kind = doc["record_kind"]
        if not isinstance(kind, str) or _RECORD_KIND_RE.match(kind) is None:
            out.append(
                _finding("common-record/type", "/record_kind", kind, "lowercase kebab-case string")
            )

    producer = _check_object(doc, "producer", out)
    if producer is not None:
        _check_string(producer, "id", "/producer/id", out)
        if isinstance(producer.get("id"), str) and _PRODUCER_ID_RE.match(producer["id"]) is None:
            out.append(
                _finding(
                    "common-record/type",
                    "/producer/id",
                    producer["id"],
                    "lowercase kebab-case identifier",
                )
            )
        _check_string(producer, "version", "/producer/version", out)

    operation = _check_object(doc, "operation", out)
    if operation is not None:
        _check_string(operation, "id", "/operation/id", out)
        for key in ("repository", "cwd", "invocation", "task", "gate"):
            _check_string(operation, key, f"/operation/{key}", out, required=False)
        for key in ("selected_revision", "executing_revision"):
            if key in operation:
                _check_oneof_unavailable(
                    operation[key], f"/operation/{key}", _SHA40_RE, "40-hex sha", out
                )
        if "workspace_generation" in operation:
            _check_oneof_unavailable(
                operation["workspace_generation"],
                "/operation/workspace_generation",
                _SHA256_RE,
                "sha256:<64-hex>",
                out,
            )

    observation = _check_object(doc, "observation", out)
    if observation is not None:
        _check_enum(observation, "coherence", "/observation/coherence", OBSERVATION_COHERENCE, out)
        _check_string(
            observation,
            "transport_classification",
            "/observation/transport_classification",
            out,
            required=False,
        )

    admission = _check_object(doc, "admission", out)
    if admission is not None:
        _check_enum(admission, "state", "/admission/state", ADMISSION_STATES, out)
        _check_string(admission, "reason", "/admission/reason", out, required=False)

    completion = _check_object(doc, "completion", out)
    if completion is not None:
        _check_enum(completion, "state", "/completion/state", COMPLETION_STATES, out)

    outcome = _check_object(doc, "domain_outcome", out)
    if outcome is not None:
        _check_enum(outcome, "outcome", "/domain_outcome/outcome", DOMAIN_OUTCOMES, out)
        if "exit_code" not in outcome:
            out.append(
                _finding("common-record/required", "/domain_outcome/exit_code", "<missing>", "'exit_code'")
            )
        else:
            code = outcome["exit_code"]
            if (code != UNAVAILABLE and not _is_int(code)) or isinstance(code, bool):
                out.append(
                    _finding(
                        "common-record/type",
                        "/domain_outcome/exit_code",
                        code,
                        "integer or 'unavailable'",
                    )
                )

    coverage = _check_object(doc, "coverage", out)
    if coverage is not None:
        _check_enum(coverage, "collection", "/coverage/collection", COVERAGE_COLLECTION, out)
        if "executed" in coverage and not isinstance(coverage["executed"], list):
            out.append(_finding("common-record/type", "/coverage/executed", coverage["executed"], "array"))
        for index, item in enumerate(coverage.get("executed") or []):
            if not isinstance(item, str) or not item:
                out.append(
                    _finding(
                        "common-record/type",
                        f"/coverage/executed/{index}",
                        item,
                        "non-empty string",
                    )
                )
        for list_key in ("blocked", "not_executed"):
            if list_key in coverage and not isinstance(coverage[list_key], list):
                out.append(_finding("common-record/type", f"/coverage/{list_key}", coverage[list_key], "array"))
            for index, item in enumerate(coverage.get(list_key) or []):
                if not isinstance(item, dict):
                    out.append(
                        _finding("common-record/type", f"/coverage/{list_key}/{index}", item, "object")
                    )
                    continue
                _check_string(item, "name", f"/coverage/{list_key}/{index}/name", out)
                _check_string(item, "reason", f"/coverage/{list_key}/{index}/reason", out)

    findings_value = doc.get("findings")
    if not isinstance(findings_value, list):
        out.append(_finding("common-record/type", "/findings", findings_value, "array"))
    else:
        for index, item in enumerate(findings_value):
            pointer = f"/findings/{index}"
            if not isinstance(item, dict):
                out.append(_finding("common-record/type", pointer, item, "object"))
                continue
            _check_string(item, "rule_id", f"{pointer}/rule_id", out)
            if isinstance(item.get("rule_id"), str) and _RULE_ID_RE.match(item["rule_id"]) is None:
                out.append(
                    _finding(
                        "common-record/type",
                        f"{pointer}/rule_id",
                        item["rule_id"],
                        "stable rule identifier ([A-Za-z0-9][A-Za-z0-9._/:-]*)",
                    )
                )
            _check_string(item, "actual", f"{pointer}/actual", out)
            _check_string(item, "expected", f"{pointer}/expected", out)
            if "location" not in item:
                out.append(
                    _finding("common-record/required", f"{pointer}/location", "<missing>", "'location'")
                )
            # Schema: oneOf non-empty string | const 'unavailable' - the
            # const arm is a non-empty string, so non-empty string is exact.
            _check_string(item, "contract_revision", f"{pointer}/contract_revision", out)
            location = item.get("location")
            if not isinstance(location, dict):
                out.append(_finding("common-record/type", f"{pointer}/location", location, "object"))
            else:
                _check_string(location, "path", f"{pointer}/location/path", out)
                if "json_pointer" in location and (
                    not isinstance(location["json_pointer"], str)
                    or _JSON_POINTER_RE.match(location["json_pointer"]) is None
                ):
                    out.append(
                        _finding(
                            "common-record/type",
                            f"{pointer}/location/json_pointer",
                            location["json_pointer"],
                            "JSON pointer string",
                        )
                    )
                if "line" in location and (
                    not isinstance(location["line"], int)
                    or isinstance(location["line"], bool)
                    or location["line"] < 1
                ):
                    out.append(
                        _finding(
                            "common-record/type",
                            f"{pointer}/location/line",
                            location["line"],
                            "integer >= 1",
                        )
                    )
        keys = [_finding_sort_key(item) for item in findings_value]
        if keys != sorted(keys):
            out.append(
                _finding(
                    "common-record/findings-order",
                    "/findings",
                    "not sorted by (rule_id, location)",
                    "deterministic order by (rule_id, location)",
                )
            )

    next_action = _check_object(doc, "next_action", out)
    if next_action is not None:
        _check_enum(next_action, "action", "/next_action/action", NEXT_ACTIONS, out)
        if next_action.get("action") in ("FIX", "NEXT") and "supported_by" not in next_action:
            out.append(
                _finding(
                    "common-record/required",
                    "/next_action/supported_by",
                    "<missing>",
                    "'supported_by' (required when action is FIX or NEXT)",
                )
            )
        _check_string(next_action, "supported_by", "/next_action/supported_by", out, required=False)

    evidence_value = doc.get("evidence")
    if not isinstance(evidence_value, list):
        out.append(_finding("common-record/type", "/evidence", evidence_value, "array"))
    else:
        for index, item in enumerate(evidence_value):
            pointer = f"/evidence/{index}"
            if not isinstance(item, dict):
                out.append(_finding("common-record/type", pointer, item, "object"))
                continue
            _check_string(item, "locator", f"{pointer}/locator", out)
            # Schema: excerpt is a plain string (no minLength - the empty
            # excerpt is schema-valid); layout is a non-empty string.
            if "excerpt" in item and not isinstance(item["excerpt"], str):
                out.append(
                    _finding("common-record/type", f"{pointer}/excerpt", item["excerpt"], "string")
                )
            _check_string(item, "layout", f"{pointer}/layout", out, required=False)
            _check_enum(
                item,
                "completeness",
                f"{pointer}/completeness",
                EVIDENCE_COMPLETENESS,
                out,
            )
            if "digest" in item:
                digest = item["digest"]
                if not isinstance(digest, str) or _SHA256_RE.match(digest) is None:
                    out.append(
                        _finding("common-record/type", f"{pointer}/digest", digest, "sha256:<64-hex>")
                    )
            for key in ("byte_count", "omitted_bytes", "omitted_count"):
                if key in item and (
                    not isinstance(item[key], int) or isinstance(item[key], bool) or item[key] < 0
                ):
                    out.append(
                        _finding("common-record/type", f"{pointer}/{key}", item[key], "integer >= 0")
                    )

    retry_state = _check_object(doc, "retry_state", out)
    if retry_state is not None:
        _check_enum(retry_state, "side_effects", "/retry_state/side_effects", SIDE_EFFECT_STATES, out)
        _check_string(retry_state, "reconciliation", "/retry_state/reconciliation", out, required=False)

    payload = _check_object(doc, "payload", out)
    if payload is not None:
        _check_string(payload, "kind", "/payload/kind", out)
        _check_string(payload, "locator", "/payload/locator", out)

    return sorted(out, key=_finding_sort_key)


# --- deterministic serialization -------------------------------------------

def serialize(record: CommonRecord | dict[str, Any]) -> str:
    """Serialize as one deterministic UTF-8 JSON document.

    Key order is sorted; findings are normalized to the canonical
    (rule_id, location) order; non-ASCII string values stay literal
    (localized content allowed; control syntax is ASCII by construction).
    Unicode normalization is NOT applied: NFC and NFD forms of the same
    glyph serialize to distinct bytes (JSON defines no normalization);
    determinism is per byte-identical input, not per rendered glyph.
    """
    doc = _as_record_dict(record)
    if isinstance(doc.get("findings"), list):
        doc["findings"] = sorted(doc["findings"], key=_finding_sort_key)
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2)


# --- reader ----------------------------------------------------------------

@dataclass
class ReadResult:
    """Outcome of read(): the record plus its surfaced unknown-field note."""

    record: dict[str, Any]
    unknown_fields: list[str]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise RecordDecodeError(f'duplicate object key "{key}"')
        seen.add(key)
    return dict(pairs)


# Known v1 key sets, mirroring the schema (unknown keys anywhere in a known
# container are surfaced, never dropped).
_KNOWN: dict[str, Any] = {
    "producer": {"id", "version"},
    "operation": {
        "id",
        "repository",
        "cwd",
        "invocation",
        "task",
        "gate",
        "selected_revision",
        "executing_revision",
        "workspace_generation",
    },
    "observation": {"coherence", "transport_classification"},
    "admission": {"state", "reason"},
    "completion": {"state"},
    "domain_outcome": {"outcome", "exit_code"},
    "coverage": {"executed", "blocked", "not_executed", "collection"},
    "coverage_item": {"name", "reason"},
    "finding": {"rule_id", "location", "actual", "expected", "contract_revision"},
    "finding_location": {"path", "json_pointer", "line"},
    "next_action": {"action", "supported_by"},
    "evidence": {
        "locator",
        "excerpt",
        "digest",
        "byte_count",
        "layout",
        "completeness",
        "omitted_bytes",
        "omitted_count",
    },
    "retry_state": {"side_effects", "reconciliation"},
    "payload": {"kind", "locator"},
}


_ITEM_SHAPES = {
    "blocked": "coverage_item",
    "not_executed": "coverage_item",
    "findings": "finding",
    "evidence": "evidence",
}


def _collect_unknown(value: Any, known: set[str] | None, prefix: str, out: list[str]) -> None:
    """Record JSON-pointer paths of keys outside the v1 known set."""
    if not isinstance(value, dict) or known is None:
        return
    for key, child in value.items():
        pointer = f"{prefix}/{key}"
        if key not in known:
            out.append(pointer)
            continue  # unknown structure: report the key, do not descend
        if key == "location":
            _collect_unknown(child, _KNOWN["finding_location"], pointer, out)
        elif key in _ITEM_SHAPES:
            if isinstance(child, list):
                for index, item in enumerate(child):
                    _collect_unknown(
                        item, _KNOWN.get(_ITEM_SHAPES[key]), f"{pointer}/{index}", out
                    )
        elif key in _KNOWN:
            _collect_unknown(child, _KNOWN[key], pointer, out)


def read(text: str) -> ReadResult:
    """Parse and version-gate one serialized common record.

    Raises SchemaVersionError when schema_version is not the supported
    version (naming observed and supported); raises RecordDecodeError for
    non-JSON input, non-object documents or duplicate keys. Unknown fields
    are tolerated and listed (as JSON pointers) in unknown_fields; they stay
    present in the returned record.
    """
    try:
        doc = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except RecordDecodeError:
        raise
    except json.JSONDecodeError as error:
        raise RecordDecodeError(f"not a JSON document: {error}") from error
    if not isinstance(doc, dict):
        raise RecordDecodeError(f"not a JSON object: {type(doc).__name__}")

    observed = doc.get("schema_version")
    if not _is_int(observed) or observed != SCHEMA_VERSION:
        raise SchemaVersionError(observed, SCHEMA_VERSION)

    top_known = {
        "schema_version",
        "record_kind",
        "producer",
        "operation",
        "observation",
        "admission",
        "completion",
        "domain_outcome",
        "coverage",
        "findings",
        "next_action",
        "evidence",
        "retry_state",
        "payload",
    }
    unknown: list[str] = []
    _collect_unknown(doc, top_known, "", unknown)
    return ReadResult(record=doc, unknown_fields=unknown)
