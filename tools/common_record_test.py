"""Self-test for tools/common_record.py (Common Record v1, ADR-0060 D3/D7).

Each case asserts ONE named envelope law; the case id rides in the failure
message. Fixtures are in-memory records only (testing law: tests never touch
developer repositories). No producer emits the record yet - these cases
freeze the envelope contract itself (batch C).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402
import workspace_schemas as ws  # noqa: E402

SHA = "a" * 40
SHA_OTHER = "b" * 40
D64 = "3" * 64


def _minimal_record() -> cr.CommonRecord:
    return cr.CommonRecord(
        record_kind="validation",
        producer=cr.Producer(id="ctx-validator", version="1"),
        operation=cr.Operation(
            id="run-20261002T000000Z-0001",
            repository="qiven-context",
            cwd="D:/JasonWork/qiven-context",
            invocation="python tools/validate_context.py",
            gate="context-local",
        ),
        observation=cr.Observation(coherence="coherent"),
        admission=cr.Admission(state="accepted"),
        completion=cr.Completion(state="completed"),
        domain_outcome=cr.DomainOutcome(outcome="passed", exit_code=0),
        coverage=cr.Coverage(collection="complete", executed=["views", "records"]),
        next_action=cr.NextAction(action="NONE"),
        retry_state=cr.RetryState(side_effects="not_started"),
        payload=cr.Payload(kind="stdout", locator="tools/validate_context.py"),
    )


def _minimal_dict() -> dict:
    return _minimal_record().to_dict()


def _expect_one_finding(case: str, record: dict, rule_id: str, pointer: str) -> None:
    findings = cr.validate(record)
    matched = [
        f
        for f in findings
        if f["rule_id"] == rule_id and f["location"]["json_pointer"] == pointer
    ]
    assert matched, f"{case}: expected {rule_id} at {pointer}, got {findings}"
    assert len(matched) == 1, f"{case}: duplicate findings for {pointer}: {matched}"
    for element in ("rule_id", "location", "actual", "expected", "contract_revision"):
        assert element in matched[0], f"{case}: finding missing element {element}"


def main() -> int:
    # CR1: schema self-validation - the shipped schema document parses under
    # the strict law, carries the v1 identity, and its enums are exactly the
    # module's exported vocabularies (public descriptor / implementation parity).
    schema_text = cr.SCHEMA_PATH.read_text(encoding="utf-8")
    schema = ws.parse_strict(schema_text)
    assert schema["$id"] == "qiven-common-record-v1.schema.json", "CR1: $id"
    assert schema["properties"]["schema_version"]["const"] == 1, "CR1: v1 const"
    assert set(schema["required"]) == {
        "schema_version", "record_kind", "producer", "operation", "observation",
        "admission", "completion", "domain_outcome", "coverage", "findings",
        "next_action", "evidence", "retry_state", "payload",
    }, "CR1: top-level required set"
    enum_parity = (
        (cr.OBSERVATION_COHERENCE, ("observation", ("coherence",))),
        (cr.ADMISSION_STATES, ("admission", ("state",))),
        (cr.COMPLETION_STATES, ("completion", ("state",))),
        (cr.DOMAIN_OUTCOMES, ("domain_outcome", ("outcome",))),
        (cr.COVERAGE_COLLECTION, ("coverage", ("collection",))),
        (cr.EVIDENCE_COMPLETENESS, ("evidence-items", ("completeness",))),
        (cr.NEXT_ACTIONS, ("next_action", ("action",))),
        (cr.SIDE_EFFECT_STATES, ("retry_state", ("side_effects",))),
    )
    for tokens, (section, (field,)) in enum_parity:
        if section == "evidence-items":
            node = schema["properties"]["evidence"]["items"]
        else:
            node = schema["properties"][section]
        assert node["properties"][field]["enum"] == list(tokens), (
            f"CR1: enum parity broke at {section}.{field}"
        )
    # CR1a: the evolution policy and D7 quotes are encoded in the description.
    assert "additively" in schema["description"], "CR1a: evolution policy missing"
    assert "versioned adapter" in schema["description"], "CR1a: adapter rule missing"
    assert "byte-stable" in schema["description"], "CR1a: ADR-0051 carrier law missing"
    # CR1b: the schema gates supported_by on FIX/NEXT (conditional requirement).
    next_action_schema = schema["properties"]["next_action"]
    assert next_action_schema.get("allOf"), "CR1b: supported_by conditional missing"

    # CR2: minimal-valid-record acceptance - only the required fields, valid.
    assert cr.validate(_minimal_record()) == [], "CR2: minimal dataclass record"
    assert cr.validate(_minimal_dict()) == [], "CR2: minimal dict record"
    read_result = cr.read(cr.serialize(_minimal_record()))
    assert read_result.unknown_fields == [], "CR2: minimal record has no unknowns"

    # CR3: every enum enforced (one bad token each, ASCII-safe control syntax).
    base = _minimal_dict()
    bad_tokens = (
        ("/observation/coherence", ("observation", "coherence"), "maybe"),
        ("/admission/state", ("admission", "state"), "denied"),
        ("/completion/state", ("completion", "state"), "done"),
        ("/domain_outcome/outcome", ("domain_outcome", "outcome"), "success"),
        ("/next_action/action", ("next_action", "action"), "RETRY"),
    )
    for pointer, (section, key), bad in bad_tokens:
        record = json.loads(json.dumps(base))
        record[section][key] = bad
        _expect_one_finding(f"CR3:{pointer}", record, "common-record/enum", pointer)

    # CR4: findings deterministic order - unsorted is a finding; serialize
    # normalizes to the canonical (rule_id, location) order.
    record = _minimal_record()
    record.domain_outcome = cr.DomainOutcome(outcome="findings", exit_code=1)
    record.findings = [
        cr.Finding(
            rule_id="ctx-rule/b",
            location=cr.FindingLocation(path="views/a.yaml", json_pointer="/x"),
            actual="observed b",
            expected="expected b",
        ),
        cr.Finding(
            rule_id="ctx-rule/a",
            location=cr.FindingLocation(path="views/b.yaml", json_pointer="/y"),
            actual="observed a",
            expected="expected a",
        ),
    ]
    unsorted_doc = record.to_dict()
    order_findings = [
        f for f in cr.validate(unsorted_doc) if f["rule_id"] == "common-record/findings-order"
    ]
    assert order_findings, "CR4: unsorted findings not flagged"
    text = cr.serialize(record)
    resorted = json.loads(text)
    keys = [(f["rule_id"], f["location"]["path"]) for f in resorted["findings"]]
    assert keys == [("ctx-rule/a", "views/b.yaml"), ("ctx-rule/b", "views/a.yaml")], (
        f"CR4: serialize did not normalize order: {keys}"
    )
    assert not [
        f for f in cr.validate(resorted) if f["rule_id"] == "common-record/findings-order"
    ], "CR4: normalized record still flagged"

    # CR5: reader tolerance - unknown fields are surfaced under the
    # unknown_fields note (never silently dropped) and are NOT validation
    # findings; duplicate keys are a typed decode rejection.
    doc = _minimal_dict()
    doc["future_section"] = {"note": "additive evolution"}
    doc["observation"]["zh_note"] = "本地化备注"
    doc["evidence"] = [
        {
            "locator": "temp/q.log",
            "completeness": "partial",
            "omitted_bytes": 4096,
            "surprise": 1,
        }
    ]
    result = cr.read(json.dumps(doc, ensure_ascii=False))
    assert sorted(result.unknown_fields) == [
        "/evidence/0/surprise",
        "/future_section",
        "/observation/zh_note",
    ], f"CR5: unknown_fields note wrong: {result.unknown_fields}"
    assert result.record["future_section"] == {"note": "additive evolution"}, (
        "CR5: unknown field was dropped"
    )
    assert not [
        f for f in cr.validate(result.record) if "unknown" in f["rule_id"]
    ], "CR5: unknown fields must not be validation findings"
    try:
        cr.read('{"schema_version": 1, "schema_version": 1}')
        raise AssertionError("CR5: duplicate key accepted")
    except cr.RecordDecodeError:
        pass

    # CR6: version-mismatch typed rejection - the reader names observed AND
    # supported; validate() reports the same breach as a finding.
    v2_doc = _minimal_dict()
    v2_doc["schema_version"] = 2
    try:
        cr.read(json.dumps(v2_doc))
        raise AssertionError("CR6: schema_version 2 accepted by reader")
    except cr.SchemaVersionError as error:
        assert error.observed == 2 and error.supported == 1, "CR6: typed fields"
        assert "2" in str(error) and "1" in str(error), "CR6: message names versions"
    _expect_one_finding("CR6", v2_doc, "common-record/schema-version", "/schema_version")
    try:
        cr.read('{"schema_version": true}')
        raise AssertionError("CR6: bool schema_version accepted")
    except cr.SchemaVersionError:
        pass

    # CR7: round-trip serialize/validate - deterministic bytes, localized
    # values stay literal UTF-8, dict and dataclass paths agree.
    record = _minimal_record()
    record.operation.selected_revision = SHA
    record.operation.executing_revision = SHA_OTHER
    record.operation.workspace_generation = f"sha256:{D64}"
    record.domain_outcome = cr.DomainOutcome(outcome="failed", exit_code="unavailable")
    record.coverage = cr.Coverage(
        collection="partial",
        executed=["build"],
        blocked=[cr.CoverageItem(name="test", reason="build failed")],
        not_executed=[cr.CoverageItem(name="docs", reason="blocked by test")],
    )
    record.findings = [
        cr.Finding(
            rule_id="compile/rule-1",
            location=cr.FindingLocation(path="源码/工具.py", line=42),
            actual="实际值",
            expected="期望值",
        )
    ]
    record.next_action = cr.NextAction(action="FIX", supported_by="fix field 源码/工具.py:42")
    record.evidence = [
        cr.Evidence(
            locator="%TEMP%/qiven-operator/local-<stamp>.json",
            digest=f"sha256:{D64}",
            byte_count=16384,
            layout="stdout+stderr",
            completeness="partial",
            omitted_bytes=4096,
            omitted_count=2,
        )
    ]
    record.retry_state = cr.RetryState(
        side_effects="unknown", reconciliation="qiven exec status <id>"
    )
    text = cr.serialize(record)
    assert cr.serialize(record) == text, "CR7: serialization not deterministic"
    assert "源码/工具.py" in text, "CR7: localized values must stay literal UTF-8"
    assert cr.validate(json.loads(text)) == [], "CR7: round-trip record invalid"
    assert cr.serialize(json.loads(text)) == text, "CR7: dict/dataclass paths disagree"
    assert cr.read(text).unknown_fields == [], "CR7: round-trip introduced unknowns"

    # CR8: budget constants exported with the documented D3 values (declared
    # only - enforcement is the B+D projection batch's job).
    assert cr.MODEL_VIEW_MAX_BYTES == 8192, "CR8: MODEL_VIEW_MAX_BYTES"
    assert cr.CONTROL_IDENTITY_MAX_BYTES == 2048, "CR8: CONTROL_IDENTITY_MAX_BYTES"
    assert cr.INLINE_FINDINGS_MAX == 8, "CR8: INLINE_FINDINGS_MAX"
    assert cr.BOUNDED_READ_MAX_BYTES == 16384, "CR8: BOUNDED_READ_MAX_BYTES"

    # CR9: next_action class-aware rule - FIX/NEXT require supported_by.
    doc = _minimal_dict()
    doc["next_action"] = {"action": "FIX"}
    _expect_one_finding(
        "CR9", doc, "common-record/required", "/next_action/supported_by"
    )
    doc["next_action"] = {"action": "NEXT", "supported_by": "re-run with --fix"}
    assert not [
        f for f in cr.validate(doc) if f["rule_id"] == "common-record/required"
    ], "CR9: supported_by presence not accepted"

    # CR10: typed shapes - exit code / revision identity / explicit absence.
    doc = _minimal_dict()
    doc["domain_outcome"]["exit_code"] = "zero"
    _expect_one_finding(
        "CR10", doc, "common-record/type", "/domain_outcome/exit_code"
    )
    doc = _minimal_dict()
    doc["domain_outcome"]["exit_code"] = "unavailable"
    assert cr.validate(doc) == [], "CR10: explicit-unavailable exit code"
    doc = _minimal_dict()
    doc["operation"]["selected_revision"] = "not-a-sha"
    _expect_one_finding(
        "CR10", doc, "common-record/type", "/operation/selected_revision"
    )
    doc = _minimal_dict()
    del doc["operation"]["id"]
    _expect_one_finding("CR10", doc, "common-record/required", "/operation/id")

    print("[ OK ] common-record self-test (CR1-CR10)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
