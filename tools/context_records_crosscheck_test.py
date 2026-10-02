"""Cross-repo Common Record conformance check: ctx-validator vs the
FROZEN devkit envelope (ADR-0060 E batch; CV mirror-drift closure).

The context validator emits Common Records through a STDLIB-ONLY builder
(qiven-context tools/validate_context.py `_emit_common_record` - this
repository is never imported by context outside the WR-6 launcher path),
and context's own suite validates against a LOCAL structural mirror.
Neither leg proves the emitted bytes against the FROZEN schema. This
suite closes that gap from the devkit side:

  XC1  byte-exact CHECKED-IN samples (captured from the real builder on
       the validator fixture corpus 2026-10-02) validate against the
       frozen `common_record.validate`, pass the version-gated reader,
       and round-trip through the frozen deterministic serializer
  XC2  LIVE leg (runs whenever a sibling qiven-context checkout with its
       .venv exists; SKIP visibly otherwise - the workspace-bootstrap
       cross-repo precedent): drives the REAL builder in a subprocess,
       then validates the emitted record bytes with the frozen validator

Disposable temp fixtures only; the context checkout is only READ.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402

# --- byte-exact samples (captured 2026-10-02 from the real builder: ------
# validator_fixture corpus, clean run + one broken required path). These
# are FROZEN evidence: if the context builder's shape changes, XC2 catches
# the drift live while XC1 keeps pinning the historical contract bytes.
SAMPLE_PASS = r"""{
  "admission": {
    "state": "accepted"
  },
  "completion": {
    "state": "completed"
  },
  "coverage": {
    "collection": "complete",
    "executed": [
      "validate_repository"
    ]
  },
  "domain_outcome": {
    "exit_code": 0,
    "outcome": "passed"
  },
  "evidence": [
    {
      "completeness": "complete",
      "layout": "stdout",
      "locator": "validator stdout (this run)"
    }
  ],
  "findings": [],
  "next_action": {
    "action": "NONE"
  },
  "observation": {
    "coherence": "coherent"
  },
  "operation": {
    "cwd": "C:\\Users\\61626\\AppData\\Local\\Temp\\cv-capture-jhwv5he9\\fixture",
    "id": "20261001T202336Z-00017652-0def00",
    "invocation": "python tools/validate_context.py",
    "repository": "qiven-context"
  },
  "payload": {
    "kind": "validator-stdout",
    "locator": "tools/validate_context.py stdout"
  },
  "producer": {
    "id": "ctx-validator",
    "version": "context-validation-v1"
  },
  "record_kind": "validation",
  "retry_state": {
    "side_effects": "not_started"
  },
  "schema_version": 1
}"""

SAMPLE_FINDINGS = r"""{
  "admission": {
    "state": "accepted"
  },
  "completion": {
    "state": "completed"
  },
  "coverage": {
    "collection": "complete",
    "executed": [
      "validate_repository"
    ]
  },
  "domain_outcome": {
    "exit_code": 1,
    "outcome": "findings"
  },
  "evidence": [
    {
      "completeness": "complete",
      "layout": "stdout",
      "locator": "validator stdout (this run)"
    }
  ],
  "findings": [
    {
      "actual": "required path absent",
      "contract_revision": "context-validation-v1",
      "expected": "required path present",
      "location": {
        "path": "projects"
      },
      "rule_id": "ctx/required-path"
    }
  ],
  "next_action": {
    "action": "FIX",
    "supported_by": "ctx/required-path at projects: fix the named condition per the context-validation-v1 validator contract"
  },
  "observation": {
    "coherence": "coherent"
  },
  "operation": {
    "cwd": "C:\\Users\\61626\\AppData\\Local\\Temp\\cv-capture-jhwv5he9\\fixture",
    "id": "20261001T202337Z-00017652-2b6d63",
    "invocation": "python tools/validate_context.py",
    "repository": "qiven-context"
  },
  "payload": {
    "kind": "validator-stdout",
    "locator": "tools/validate_context.py stdout"
  },
  "producer": {
    "id": "ctx-validator",
    "version": "context-validation-v1"
  },
  "record_kind": "validation",
  "retry_state": {
    "side_effects": "not_started"
  },
  "schema_version": 1
}"""


def _crosscheck(text: str, label: str) -> None:
    result = cr.read(text)
    findings = cr.validate(result.record)
    if findings:
        raise AssertionError(f"[{label}] frozen-envelope findings: {findings}")
    if result.unknown_fields:
        raise AssertionError(f"[{label}] unexpected unknown fields: {result.unknown_fields}")
    # deterministic-serializer parity: the context builder's bytes and
    # the frozen canonical serialization agree byte-for-byte
    canonical = cr.serialize(result.record)
    if canonical != text.strip():
        raise AssertionError(
            f"[{label}] serializer parity broken: canonical {len(canonical)} bytes "
            f"vs sample {len(text.strip())} bytes"
        )


def _context_checkout() -> tuple[Path, Path] | None:
    context = ROOT.parent / "qiven-context"
    if sys.platform == "win32":
        venv_python = context / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = context / ".venv" / "bin" / "python"
    if not (context / "tools" / "validate_context.py").is_file() or not venv_python.is_file():
        return None
    return context, venv_python


def _live_child_source(context_tools: str) -> str:
    return f"""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, r"{context_tools}")
import validator_fixture, validate_context as vc
tmp = tempfile.mkdtemp(prefix="cv-crosscheck-")
try:
    base = Path(tmp) / "fixture"
    validator_fixture.build(base)
    clean = vc.validate_repository(base)
    shutil.rmtree(base / "projects")
    broken = vc.validate_repository(base)
    p_pass = vc._emit_common_record(base, [], 0)
    p_fail = vc._emit_common_record(base, broken, 1)
    out = {{
        "clean_errors": len(clean),
        "broken_errors": len(broken),
        "pass_record": Path(p_pass).read_text(encoding="utf-8"),
        "fail_record": Path(p_fail).read_text(encoding="utf-8"),
    }}
    print("XCCROSSCHECK " + json.dumps(out))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
"""


def main() -> int:
    # XC1: checked-in byte-exact samples against the frozen envelope
    _crosscheck(SAMPLE_PASS, "XC1.pass-sample")
    _crosscheck(SAMPLE_FINDINGS, "XC1.findings-sample")
    pass_doc = json.loads(SAMPLE_PASS)
    findings_doc = json.loads(SAMPLE_FINDINGS)
    assert pass_doc["domain_outcome"]["outcome"] == "passed", "XC1.pass-outcome"
    assert findings_doc["domain_outcome"]["outcome"] == "findings", "XC1.findings-outcome"
    assert findings_doc["next_action"]["action"] == "FIX", "XC1.findings-next-fix"
    assert findings_doc["findings"][0]["rule_id"] == "ctx/required-path", "XC1.rule-id"

    # XC2: live leg against the real builder in the sibling checkout
    located = _context_checkout()
    if located is None:
        print("[SKIP] XC2: no sibling qiven-context checkout with .venv "
              "(pass records cross-checked against the frozen envelope only)")
        print("[SKIP] XC2: evidence: sibling probes found no qiven-context with a "
              ".venv next to this devkit; XC1 (frozen-envelope leg) ran completely")
        print("[SKIP] XC2: NEXT: NEXT - run inside the qiven workspace layout for "
              "the live builder crosscheck (no FIX applies: absence is environment, "
              "not a defect)")
        print("[ OK ] context records crosscheck (XC1; XC2 skipped - checkout absent)")
        return 0
    context, venv_python = located
    with tempfile.TemporaryDirectory(prefix="qiven-cv-crosscheck-") as temp:
        bridge = Path(temp) / "drive_builder.py"
        bridge.write_text(_live_child_source(str(context / "tools")),
                          encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [str(venv_python), str(bridge)],
            capture_output=True, text=True, timeout=180, check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"[XC2] builder drive failed rc={completed.returncode}: "
                f"{completed.stdout[-400:]} {completed.stderr[-400:]}")
        marker = next(line for line in completed.stdout.splitlines()
                      if line.startswith("XCCROSSCHECK "))
        out = json.loads(marker[len("XCCROSSCHECK "):])
        if out["clean_errors"] != 0 or out["broken_errors"] < 1:
            raise AssertionError(
                f"[XC2] unexpected corpus state: clean={out['clean_errors']} "
                f"broken={out['broken_errors']}")
        _crosscheck(out["pass_record"], "XC2.live-pass")
        _crosscheck(out["fail_record"], "XC2.live-findings")
    print("[ OK ] context records crosscheck (XC1 + live XC2)")
    return 0


if __name__ == "__main__":
    import selftest_carrier
    raise SystemExit(selftest_carrier.run(__file__, main))
