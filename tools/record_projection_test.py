"""Self-test for tools/record_projection.py (the B+D projection layer).

Each case asserts ONE named D3 budget/semantics law; the case id rides in
the failure message. In-memory records only (testing law: tests never
touch developer repositories).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402
import record_projection as rp  # noqa: E402

SHA = "a" * 40
D64 = "2" * 64


def _base() -> cr.CommonRecord:
    return cr.CommonRecord(
        record_kind="gate-run",
        producer=cr.Producer(id="devkit-qiven-operator", version="1"),
        operation=cr.Operation(
            id="op-20261002T000000Z-0001-ab12cd",
            repository="qiven-devkit",
            cwd="D:/JasonWork/qiven-devkit",
            invocation="python tools/qiven.py gate local",
            gate="local",
            selected_revision=SHA,
            executing_revision=SHA,
            workspace_generation=f"sha256:{D64}",
        ),
        observation=cr.Observation(coherence="coherent"),
        admission=cr.Admission(state="accepted"),
        completion=cr.Completion(state="completed"),
        domain_outcome=cr.DomainOutcome(outcome="failed", exit_code=1),
        coverage=cr.Coverage(collection="partial", executed=["a", "b"],
                             not_executed=[cr.CoverageItem(name="c", reason="stopped")]),
        next_action=cr.next_action_for("unexpected-task-failure"),
        retry_state=cr.RetryState(side_effects="unknown"),
        payload=cr.Payload(kind="gate-machine-json", locator=".generated-temp/x.json"),
    )


def _finding(index: int) -> cr.Finding:
    return cr.Finding(
        rule_id=f"rule-{index // 10}",
        location=cr.FindingLocation(path=f"src/file{index:02d}.cpp", line=index + 1),
        actual=f"observed condition {index} 实际值",
        expected=f"expected constraint {index}",
    )


def main() -> int:
    # PJ1: budget constants are the frozen D3 values and the serialized
    # projection obeys them exactly (bytes, never character counts).
    assert cr.MODEL_VIEW_MAX_BYTES == 8192 and cr.CONTROL_IDENTITY_MAX_BYTES == 2048
    assert cr.INLINE_FINDINGS_MAX == 8 and cr.BOUNDED_READ_MAX_BYTES == 16384

    # PJ2: 50 findings -> 8 inline (the D3 cap), omitted counts + total.
    record = _base()
    record.findings = [_finding(i) for i in range(50)]
    view = rp.project(record)
    assert len(view.encode("utf-8")) <= cr.MODEL_VIEW_MAX_BYTES, "PJ2: total budget"
    counts = rp.project_json(record)["findings"]
    assert counts == {"returned": 8, "total": 50, "omitted": 42}, f"PJ2: {counts}"
    assert "8/50 shown, 42 omitted" in view, "PJ2: counts surface in the view"
    shown_rules = [line for line in view.splitlines() if line.startswith("[")]
    assert len(shown_rules) == 8, f"PJ2: inline finding lines {len(shown_rules)}"

    # PJ3: 100 KiB evidence excerpt -> bounded view with byte range,
    # continue cursor and NO premature EOF; the excerpt cap itself is
    # <= BOUNDED_READ_MAX_BYTES.
    record = _base()
    record.findings = []
    record.evidence = [cr.Evidence(
        locator=".generated-temp/operator/exec/run-1.log",
        completeness="partial",
        excerpt="x" * 100 * 1024,
        digest=f"sha256:{D64}",
        byte_count=200 * 1024,
    )]
    info = rp.project_json(record)
    assert info["model_view_bytes"] <= cr.MODEL_VIEW_MAX_BYTES, "PJ3: total budget"
    assert info["evidence"]["shown_bytes"] <= cr.BOUNDED_READ_MAX_BYTES, "PJ3: excerpt cap"
    assert info["evidence"]["eof"] is False, "PJ3: EOF must not be claimed early"
    assert info["evidence"]["continue_offset"] == info["evidence"]["shown_bytes"]
    assert "--offset" in info["view"] and "more evidence bytes remain" in info["view"], (
        "PJ3: continue cursor missing"
    )

    # PJ4: small excerpt -> EOF marker with the complete range.
    record.evidence = [cr.Evidence(
        locator="temp/q.log", completeness="complete", excerpt="LNK2019: unresolved external symbol",
    )]
    info = rp.project_json(record)
    assert info["evidence"]["eof"] is True, "PJ4: small excerpt must reach EOF"
    assert "EOF (excerpt complete within this view)" in info["view"], "PJ4: EOF marker"
    assert "LNK2019" in info["view"], "PJ4: excerpt content visible"

    # PJ5: purity - the projection NEVER mutates its input (dict deep
    # equality before/after; dataclass and dict paths agree byte-for-byte).
    record = _base()
    record.findings = [_finding(i) for i in range(20)]
    record.evidence = [cr.Evidence(locator="temp/q.log", completeness="complete",
                                   excerpt="e" * 500)]
    doc = record.to_dict()
    frozen = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    frozen_obj = copy.deepcopy(record)
    _ = rp.project(doc)
    _ = rp.project_json(record)
    assert json.dumps(doc, sort_keys=True, ensure_ascii=False) == frozen, (
        "PJ5: dict input mutated"
    )
    assert json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False) == json.dumps(
        frozen_obj.to_dict(), sort_keys=True, ensure_ascii=False
    ), "PJ5: dataclass input mutated"
    assert rp.project(record) == rp.project(record.to_dict()), (
        "PJ5: dataclass and dict views disagree"
    )

    # PJ6: pathological identity values still keep control <= 2048 with
    # all control lines present (reserve control + locator FIRST).
    record = _base()
    record.operation.invocation = "sh " + "-x " * 3000
    record.next_action = cr.next_action_for(
        "finding-with-known-pointer", supported_by="fix\n" + "line\n" * 200)
    info = rp.project_json(record)
    assert info["control"]["bytes"] <= cr.CONTROL_IDENTITY_MAX_BYTES, (
        f"PJ6: control {info['control']['bytes']}"
    )
    assert info["model_view_bytes"] <= cr.MODEL_VIEW_MAX_BYTES, "PJ6: total budget"
    assert "next: FIX" in info["view"], "PJ6: next action survived clipping"
    assert "evidence:" in info["view"].split("findings:")[0], "PJ6: locator stays in control"

    # PJ7: findings render in canonical (rule, location) order.
    record = _base()
    record.findings = [
        cr.Finding(rule_id="b-rule", location=cr.FindingLocation(path="z.cpp"),
                   actual="x", expected="y"),
        cr.Finding(rule_id="a-rule", location=cr.FindingLocation(path="a.cpp"),
                   actual="x", expected="y"),
    ]
    view = rp.project(record)
    first = view.index("rule=a-rule")
    second = view.index("rule=b-rule")
    assert first < second, "PJ7: findings not in (rule, location) order"

    # PJ8: exact accounting - model_view_bytes equals the true serialized
    # byte length; footer repeats a small bounded locator.
    record = _base()
    record.evidence = [cr.Evidence(locator="temp/big.log", completeness="partial",
                                   excerpt="z" * 4000)]
    info = rp.project_json(record)
    assert info["model_view_bytes"] == len(info["view"].encode("utf-8")), "PJ8: byte count"
    footer = info["view"].rstrip().splitlines()[-1]
    assert footer.startswith("== qiven-record end:"), "PJ8: footer shape"
    assert "temp/big.log" in footer, "PJ8: footer repeats the locator"
    assert info["view"].count("temp/big.log") >= 2, "PJ8: header+footer locator repeat"

    # PJ9: zero findings and no excerpt stay truthful (no invented counts).
    info = rp.project_json(_base())
    assert info["findings"] == {"returned": 0, "total": 0, "omitted": 0}, "PJ9: zero counts"
    assert "findings: 0" in info["view"], "PJ9: zero-findings line"

    # PJ10: partial coverage surfaces discovered + blocked/unexecuted.
    assert "blocked/unexec: c" in rp.project(_base()), "PJ10: unexecuted stage named"

    # PJ11: a full projection of a realistic FAIL record round-trips
    # through the envelope validator untouched (projection adds nothing
    # to the record itself).
    record = _base()
    record.findings = [_finding(i) for i in range(12)]
    record.evidence = [cr.Evidence(
        locator="temp/q.log", completeness="partial", excerpt="diag " * 500,
        digest=f"sha256:{D64}", byte_count=9000, layout="stdout+stderr",
        omitted_bytes=100, omitted_count=2)]
    doc = record.to_dict()
    before = cr.validate(doc)
    assert before == [], "PJ11: fixture record must be valid"
    rp.project(doc)
    assert cr.validate(doc) == before, "PJ11: projection changed record validity"
    assert json.dumps(doc, sort_keys=True, ensure_ascii=False) == json.dumps(
        record.to_dict(), sort_keys=True, ensure_ascii=False), "PJ11: record mutated"

    # PJ12: the class-rule helper enforces its own laws (shared mapping).
    assert cr.next_action_for("pass").action == "NONE"
    fix = cr.next_action_for("policy-rejected", "admit the revision in trust policy")
    assert fix.action == "FIX" and fix.supported_by
    assert cr.next_action_for("operation-running", "qiven exec status <id>").action == "NEXT"
    assert cr.next_action_for("lease-expired").action == "RECONCILE"
    for event in ("lease-expired", "unknown-side-effects"):
        na = cr.next_action_for(event)
        assert na.action == "RECONCILE", "PJ12: mapping"
    try:
        cr.next_action_for("fix")  # not an event token
        raise AssertionError("PJ12: unknown event accepted")
    except ValueError:
        pass
    try:
        cr.next_action_for("invocation-rejected")  # FIX without support
        raise AssertionError("PJ12: FIX without supported_by accepted")
    except ValueError:
        pass
    # running ops map to NEXT with the status handle; expired maps to
    # RECONCILE (never an invented retry)
    assert cr.NEXT_ACTION_EVENTS["operation-running"] == "NEXT"
    assert cr.NEXT_ACTION_EVENTS["lease-expired"] == "RECONCILE"
    assert cr.NEXT_ACTION_EVENTS["classify-before-retry"] == "DIAGNOSE"

    print("[ OK ] record-projection self-test (PJ1-PJ12)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
