"""P0 closeout fixture suite (ADR-0060 E batch, 2026-10-02; D15 classes).

Covers the fixture classes this batch owns at the devkit side:
  EC1  invalid-UTF-8 end-to-end through the operator capture seam
       (exit-checklist row 5): raw bytes retained as evidence, bounded
       replacement-char render, honest record, recovery via evidence-read
  EC2  invalid-UTF-8 through the projection excerpt seam
  EC3  known grep/head/tail selectors over the gate human summary
       (exit-checklist row 8): class + action + reference survive on ONE
       summary line
  EC4  the same selectors over the record projection view
  EC5  raw-Bash passthrough profile (exit-checklist row 10): a Qiven-owned
       script through a subprocess keeps exit code + verdict line
  EC6  gate_proof named profile: PASS receipt proof fields + digest
  EC7  merge_proof named profile: the branch->merge receipt row shape
       (byte-exact checked-in publication sample + live fixture receipt)
  EC8  evidence expiry markers (D6): `.expired` sibling -> typed expired
       error naming the original locator; bytes win when both exist
  EC9  unreadable + directory evidence paths -> typed errors
  EC10 unknown running operations (D15): unknown exec id -> typed answer
       + one record with completion=unknown
  EC11 exit-zero report mode law (D3): findings outcome never aliases to
       PASSED in the projection

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402
import record_projection as rp  # noqa: E402

OPERATOR = str(ROOT / "tools" / "qiven_operator.py")
CHECKS = 0

# byte-exact gate PASS receipt captured from the real publication chain
# (qiven-devkit gate `local` PASS at head 4fd1ad8..., 2026-10-01; the
# branch->merge proof shape exercised by every publication since P-53)
REAL_RECEIPT_SAMPLE = """{
 "gate": "local",
 "head": "4fd1ad8def6af2006dc2cd86b55ebf616de970a1",
 "status": "pass",
 "tasks": [
  {
   "duration_seconds": 0.01775280002038926,
   "name": "exact-head",
   "status": "pass"
  },
  {
   "duration_seconds": 0.21462649997556582,
   "name": "check-toolchain",
   "status": "pass"
  },
  {
   "duration_seconds": 39.99350869999034,
   "name": "operator-tests",
   "status": "pass"
  },
  {
   "duration_seconds": 0.14703819999704137,
   "name": "commit-subjects",
   "status": "pass"
  },
  {
   "duration_seconds": 0.028364799974951893,
   "name": "diff-check",
   "status": "pass"
  },
  {
   "duration_seconds": 0.022442799992859364,
   "name": "clean-tree",
   "status": "pass"
  }
 ],
 "timestamp": "2026-10-01T20:08:44Z"
}"""

# the invalid-UTF-8 fixture payload: 19 raw bytes with two invalid
# sequences; the retained artifact must carry them byte-exactly
BAD_BYTES = b"pre \xff\xfe bad \x80\x81 post\n"
BAD_CHILD = (
    "import sys; sys.stdout.buffer.write(b'pre \\xff\\xfe bad \\x80\\x81 post\\n'); "
    "sys.stdout.buffer.flush(); raise SystemExit(7)"
)


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(argv: list[str], *, cwd: Path, expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], cwd=repo)


def load_operator():
    spec = importlib.util.spec_from_file_location("qiven_operator_closeout", ROOT / "tools" / "qiven_operator.py")
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the canonical devkit qiven_operator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def grep_lines(lines: list[str]) -> list[str]:
    """Simulate `grep -E "FAIL|OK"` (documented harness selector)."""
    return [line for line in lines if re.search(r"FAIL|OK", line)]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qiven-p0-closeout-") as temp:
        repo = Path(temp) / "repo"
        (repo / ".qiven").mkdir(parents=True)
        config = {
            "schema_version": 1,
            "repository_name": "p0-closeout-fixture",
            "default_gate": "ec-sel-pass-gate",
            "tasks": {
                "ec-bad-utf8": {"argv": [sys.executable, "-c", BAD_CHILD]},
                "ec-sel-pass": {"argv": [sys.executable, "-c", "print('ec-selector-pass')"]},
            },
            "gates": {
                "ec-utf8-fail": ["ec-bad-utf8"],
                "ec-sel-fail": ["ec-sel-pass", "ec-bad-utf8"],
                "ec-sel-pass-gate": ["ec-sel-pass"],
            },
            "ci": {},
        }
        config_path = repo / ".qiven" / "operator.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.environ["QIVEN_TARGET_ROOT"] = str(repo)

        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "P0Closeout")
        git(repo, "config", "user.email", "closeout@example.invalid")
        git(repo, "add", "--all")
        git(repo, "commit", "-m", "baseline")
        head = git(repo, "rev-parse", "HEAD").stdout.strip()

        records_dir = repo / ".generated-temp" / "operator" / "records"

        def latest_record(prefix: str) -> dict:
            matches = sorted(records_dir.glob(f"{prefix}-*.json"))
            if not matches:
                raise AssertionError(f"no record emitted for {prefix}")
            return json.loads(matches[-1].read_text(encoding="utf-8"))

        # ---------------- EC1: invalid UTF-8 end-to-end (capture seam) ----
        human_fail = run([sys.executable, OPERATOR, "--no-color", "gate",
                          "--name", "ec-utf8-fail"], cwd=repo, expect=1)
        payload = json.loads(run([sys.executable, OPERATOR, "--json", "gate",
                                  "--name", "ec-utf8-fail"], cwd=repo, expect=1).stdout)
        row = payload["results"][0]
        check(row["status"] == "fail" and row["returncode"] == 7, "EC1.fail-shape")
        artifact = Path(row["evidence_path"])
        check(artifact.is_file(), "EC1.evidence-retained", str(row.get("evidence_path")))
        raw = artifact.read_bytes()
        check(raw == BAD_BYTES, "EC1.raw-bytes-byte-exact",
              f"{len(raw)} bytes: {raw[:40]!r}")
        check(row["evidence_bytes"] == len(BAD_BYTES), "EC1.byte-count-honest")
        check(row["evidence_sha256"] == hashlib.sha256(BAD_BYTES).hexdigest(),
              "EC1.digest-honest")
        # the agent render is a bounded REPLACEMENT-CHAR view, never the
        # raw bytes and never a crash
        check("\ufffd" in human_fail.stdout, "EC1.replacement-render")
        check("\ufffd\ufffd bad" in human_fail.stdout, "EC1.replacement-pair")
        check("Traceback" not in human_fail.stdout, "EC1.no-traceback")
        # the record carries honest evidence for the invalid bytes
        rec1 = latest_record(f"ec-utf8-fail-{head}")
        check(cr.validate(rec1) == [], "EC1.record-valid", str(cr.validate(rec1)))
        entry = next(e for e in rec1["evidence"] if e["locator"] == str(artifact))
        check(entry["digest"] == f"sha256:{hashlib.sha256(BAD_BYTES).hexdigest()}"
              and entry["byte_count"] == len(BAD_BYTES)
              and entry["completeness"] == "complete",
              "EC1.record-evidence-honest", str(entry))
        # raw bytes stay recoverable through the bounded evidence route
        ev = json.loads(run([sys.executable, OPERATOR, "--json", "evidence-read",
                             str(artifact)], cwd=repo).stdout)
        check(ev["status"] == "ok" and ev["bytes_returned"] == len(BAD_BYTES)
              and ev["total_bytes"] == len(BAD_BYTES) and ev["eof"] is True,
              "EC1.evidence-read-recoverable", str(ev)[:200])
        check(ev["content"] == BAD_BYTES.decode("utf-8", errors="replace"),
              "EC1.evidence-read-decodes-as-view")
        # the widened boundary stays typed for OTHER temp paths (never an
        # open door onto the whole temp dir)
        outside = Path(tempfile.gettempdir()) / "ec-outside-boundary.log"
        outside.write_bytes(b"no")
        boundary = run([sys.executable, OPERATOR, "--json", "evidence-read",
                        str(outside)], cwd=repo, expect=2)
        check("must stay under" in boundary.stdout, "EC1.boundary-still-typed",
              boundary.stdout[:200])

        # ---------------- EC2: invalid UTF-8 (projection excerpt seam) ----
        decoded_view = BAD_BYTES.decode("utf-8", errors="replace")
        rec2 = cr.CommonRecord(
            record_kind="exec-run",
            producer=cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=cr.Operation(id="ec2-op", repository="p0-closeout-fixture"),
            observation=cr.Observation(coherence="coherent"),
            admission=cr.Admission(state="accepted"),
            completion=cr.Completion(state="completed"),
            domain_outcome=cr.DomainOutcome(outcome="failed", exit_code=7),
            coverage=cr.Coverage(collection="complete", executed=["task"]),
            next_action=cr.next_action_for("unexpected-task-failure"),
            retry_state=cr.RetryState(side_effects="not_started"),
            payload=cr.Payload(kind="task-evidence", locator=str(artifact)),
            evidence=[cr.Evidence(
                locator=str(artifact), completeness="complete",
                excerpt=(decoded_view + "漢字テスト" * 900),  # invalid + multibyte
                digest=f"sha256:{hashlib.sha256(BAD_BYTES).hexdigest()}",
                byte_count=len(BAD_BYTES),
            )],
        )
        info2 = rp.project_json(rec2)
        check(info2["model_view_bytes"] <= cr.MODEL_VIEW_MAX_BYTES, "EC2.view-budget")
        check(decoded_view in info2["view"], "EC2.replacement-chars-visible")
        check(info2["evidence"]["eof"] is False, "EC2.no-premature-eof")

        # ---------------- EC3: selectors over the gate summary -----------
        human_sel = run([sys.executable, OPERATOR, "--no-color", "gate",
                         "--name", "ec-sel-fail"], cwd=repo, expect=1)
        lines = human_sel.stdout.splitlines()
        summary = lines[-1]
        check(summary.startswith(f"[FAIL] gate:ec-sel-fail: FAIL"), "EC3.summary-class",
              summary)
        check("NEXT action: DIAGNOSE" in summary, "EC3.summary-action", summary)
        check(" - evidence: " in summary, "EC3.summary-reference", summary)
        evidence_token = summary.rsplit(" - evidence: ", 1)[1].strip()
        check(Path(evidence_token).is_file()
              and b"\xff" in Path(evidence_token).read_bytes(),
              "EC3.reference-resolves-to-raw-evidence", evidence_token)
        selected = grep_lines(lines)
        check(summary in selected, "EC3.grep-keeps-summary")
        check(any("NEXT action:" in line for line in selected),
              "EC3.grep-keeps-action")
        check(any(" - evidence: " in line for line in selected),
              "EC3.grep-keeps-reference")
        # head-of-output is the progress stream (a still-streaming gate
        # shows [ RUN]/[WAIT] first - documented genuine loss; the verdict
        # summary line is the compensating carrier, asserted above)
        check(not ("NEXT action:" in lines[0] and " - evidence: " in lines[0]),
              "EC3.head-of-progress-documented-loss")

        human_pass = run([sys.executable, OPERATOR, "--no-color", "gate",
                          "--name", "ec-sel-pass-gate"], cwd=repo)
        pass_lines = human_pass.stdout.splitlines()
        pass_summary = pass_lines[-1]
        check(pass_summary.startswith("[ OK ] gate:ec-sel-pass-gate: PASS"),
              "EC3.pass-summary-class", pass_summary)
        check(" - receipt: " in pass_summary, "EC3.pass-summary-receipt-ref",
              pass_summary)
        receipt_token = pass_summary.rsplit(" - receipt: ", 1)[1].strip()
        receipt_path = Path(receipt_token)
        check(receipt_path.is_file(), "EC3.receipt-ref-resolves", receipt_token)
        check(pass_summary in grep_lines(pass_lines), "EC3.grep-keeps-pass-summary")

        # ---------------- EC4: selectors over the projection view --------
        fail_doc = latest_record(f"ec-sel-fail-{head}")
        view = rp.project(fail_doc)
        view_lines = view.splitlines()
        first = view_lines[0]
        check("verdict=FAILED" in first and "next=DIAGNOSE" in first
              and "evidence=" in first, "EC4.line1-carries-triple", first)
        check(first in grep_lines(view_lines), "EC4.grep-keeps-line1")
        footer = view_lines[-1]
        check(footer.startswith("== qiven-record end:")
              and "verdict=FAILED" in footer and "next=DIAGNOSE" in footer
              and "locator=" in footer,
              "EC4.tail-keeps-class-action-and-locator", footer)
        pass_doc = latest_record(f"ec-sel-pass-gate-{head}")
        pass_view_lines = rp.project(pass_doc).splitlines()
        check("verdict=PASSED" in pass_view_lines[0], "EC4.pass-verdict-token",
              pass_view_lines[0])
        # documented genuine selector loss: a case-sensitive `FAIL|OK`
        # grep matches nothing in a PASSED-class projection (no token
        # gaming); the compensating carrier is the operator's `[ OK ]`
        # summary line of the SAME transaction (EC3.pass-summary-class)
        check(not grep_lines(pass_view_lines), "EC4.pass-grep-loss-documented")

        # ---------------- EC5: raw-Bash passthrough profile --------------
        passthrough = run([sys.executable, str(ROOT / "tools" / "check_commit_subjects.py"),
                           "--selftest"], cwd=ROOT)
        check("[ OK ] check_commit_subjects selftest" in passthrough.stdout,
              "EC5.pass-verdict-line-intact", passthrough.stdout[:200])
        typed = run([sys.executable, OPERATOR, "--no-color", "evidence-read",
                     "no-such/missing.log"], cwd=repo, expect=2)
        check(any(line.startswith("[FAIL] evidence not found")
                  for line in typed.stdout.splitlines()),
              "EC5.fail-verdict-line-intact", typed.stdout[:200])

        # ---------------- EC6/EC7: gate_proof + merge_proof profiles -----
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["tasks"]["merge-proof"] = {"builtin": "gate_proof",
                                          "gate": "ec-sel-pass-gate"}
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        proof = run([sys.executable, OPERATOR, "--no-color", "run", "merge-proof"],
                    cwd=repo)
        check(f"[ OK ] merge-proof: ec-sel-pass-gate PASS @ {head[:12]}" in proof.stdout,
              "EC6.proof-verdict-names-gate-and-head", proof.stdout[-200:])

        receipt_bytes = receipt_path.read_bytes()
        pass_record = latest_record(f"ec-sel-pass-gate-{head}")
        receipt_entry = next(e for e in pass_record["evidence"]
                             if e["locator"] == str(receipt_path))
        check(receipt_entry["digest"] == f"sha256:{hashlib.sha256(receipt_bytes).hexdigest()}"
              and receipt_entry["byte_count"] == len(receipt_bytes),
              "EC6.receipt-digest-checked", str(receipt_entry))

        # EC7 live receipt rows (the branch->merge proof shape)
        check(receipt_path.name == f"ec-sel-pass-gate-{head}.json",
              "EC7.receipt-path-shape", receipt_path.name)
        live = json.loads(receipt_bytes.decode("utf-8"))
        for key in ("gate", "head", "status", "timestamp", "tasks"):
            check(key in live, f"EC7.live-field-{key}")
        check(live["gate"] == "ec-sel-pass-gate" and live["head"] == head
              and live["status"] == "pass" and re.fullmatch(r"[0-9a-f]{40}", live["head"]),
              "EC7.live-row-values")
        for task_row in live["tasks"]:
            check(set(task_row) == {"name", "status", "duration_seconds"}
                  and task_row["status"] == "pass",
                  "EC7.live-task-row-shape", str(task_row))
        # EC7 byte-exact publication sample (real receipt from the
        # 2026-10-01 publication chain)
        sample = json.loads(REAL_RECEIPT_SAMPLE)
        check(sample["gate"] == "local" and sample["status"] == "pass"
              and re.fullmatch(r"[0-9a-f]{40}", sample["head"]),
              "EC7.sample-row-values")
        check(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", sample["timestamp"]),
              "EC7.sample-timestamp-rfc3339")
        check(all(set(row) == {"name", "status", "duration_seconds"}
                  and row["status"] == "pass" for row in sample["tasks"]),
              "EC7.sample-task-rows")

        # gate_proof fails closed on tampered / missing receipts
        tampered = json.loads(receipt_bytes.decode("utf-8"))
        tampered["head"] = "0" * 40
        receipt_path.write_text(json.dumps(tampered, indent=1, sort_keys=True),
                                encoding="utf-8")
        mismatch = run([sys.executable, OPERATOR, "--no-color", "run", "merge-proof"],
                       cwd=repo, expect=1)
        check("not a matching PASS" in mismatch.stdout, "EC6.tampered-receipt-fails",
              mismatch.stdout[-200:])
        receipt_path.write_bytes(receipt_bytes)
        receipt_path.unlink()
        missing = run([sys.executable, OPERATOR, "--no-color", "run", "merge-proof"],
                      cwd=repo, expect=1)
        check("no ec-sel-pass-gate PASS receipt" in missing.stdout,
              "EC6.missing-receipt-fails", missing.stdout[-200:])
        receipt_path.write_bytes(receipt_bytes)

        # ---------------- EC8: expiry markers ----------------------------
        ev_dir = repo / ".generated-temp" / "evr"
        ev_dir.mkdir(parents=True, exist_ok=True)
        live_log = ev_dir / "retained.log"
        live_bytes = b"kept evidence bytes\n"
        live_log.write_bytes(live_bytes)
        marker = ev_dir / "retained.log.expired"
        marker.write_text(
            "expired 2026-10-02T00:00:00Z; original 19 bytes; retention sweep",
            encoding="utf-8",
        )
        # both present: the BYTES win (a marker alone never hides
        # surviving diagnostics)
        served = json.loads(run([sys.executable, OPERATOR, "--json", "evidence-read",
                                 "evr/retained.log"], cwd=repo).stdout)
        check(served["status"] == "ok" and served["bytes_returned"] == len(live_bytes),
              "EC8.bytes-win-over-marker")
        # artifact gone, marker present: typed `expired` naming the
        # original locator and the marker's bounded note
        live_log.unlink()
        expired = run([sys.executable, OPERATOR, "--json", "evidence-read",
                       "evr/retained.log"], cwd=repo, expect=2)
        expired_doc = json.loads(expired.stdout)
        check(expired_doc["status"] == "error"
              and "evidence expired" in expired_doc["error"], "EC8.expired-typed",
              expired.stdout[:200])
        check(str(live_log.resolve()) in expired_doc["error"],
              "EC8.original-locator-named", expired_doc["error"][:300])
        check(str(marker) in expired_doc["error"], "EC8.marker-named")
        check("original 19 bytes" in expired_doc["error"], "EC8.marker-note-surfaced")
        # a noteless marker still types the expiry with the locator
        marker.write_text("", encoding="utf-8")
        expired2 = run([sys.executable, OPERATOR, "--json", "evidence-read",
                        "evr/retained.log"], cwd=repo, expect=2)
        check("evidence expired" in expired2.stdout
              and "marker note" not in expired2.stdout, "EC8.noteless-marker")

        # ---------------- EC9: unreadable + directory paths --------------
        (ev_dir / "adir").mkdir(exist_ok=True)
        is_dir = run([sys.executable, OPERATOR, "--json", "evidence-read",
                      "evr/adir"], cwd=repo, expect=2)
        check("evidence path is a directory" in is_dir.stdout, "EC9.directory-typed",
              is_dir.stdout[:200])
        # unreadable (permission-changed/locked) file: a real read-denied
        # ACL is not reliably constructible cross-platform, so the seam is
        # exercised at the resolution boundary (operator-test's R2
        # monkeypatch precedent): a target whose stat/is_dir are real but
        # whose open() raises PermissionError must yield the TYPED
        # `evidence unreadable` error, never a traceback
        locked = ev_dir / "locked.log"
        locked.write_bytes(b"locked\n")
        operator = load_operator()
        real_resolve = operator._evidence_target

        class LockedTarget:
            def __init__(self, real: Path) -> None:
                self._real = real

            def stat(self):
                return self._real.stat()

            def is_dir(self) -> bool:
                return self._real.is_dir()

            def open(self, *args, **kwargs):
                raise PermissionError(
                    5, "Access is denied (fixture)", str(self._real))

            def relative_to(self, *args):  # display falls back to str()
                raise ValueError("stub")

            def __str__(self) -> str:
                return str(self._real)

        operator._evidence_target = lambda text: LockedTarget(locked)
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                rc = operator.main(["--json", "evidence-read", "evr/locked.log"])
        finally:
            operator._evidence_target = real_resolve
        check(rc == 2, "EC9.unreadable-exit", str(rc))
        check("Traceback" not in buffer.getvalue(), "EC9.unreadable-no-traceback")
        check("evidence unreadable" in buffer.getvalue(), "EC9.unreadable-typed",
              buffer.getvalue()[:200])

        # ---------------- EC10: unknown running operations ---------------
        bogus_id = "20260101T000000Z-00000001-deadbe"
        unknown = run([sys.executable, OPERATOR, "--json", "exec", "status", bogus_id],
                      cwd=repo, expect=2)
        unknown_doc = json.loads(unknown.stdout)
        check(unknown_doc["status"] == "error"
              and "unknown exec id" in unknown_doc["error"], "EC10.typed-answer",
              unknown.stdout[:200])
        check("Traceback" not in unknown.stdout, "EC10.no-crash")
        unknown_records = sorted(records_dir.glob("exec-status-unknown-*"))
        check(bool(unknown_records), "EC10.record-emitted")
        u_doc = json.loads(unknown_records[-1].read_text(encoding="utf-8"))
        check(cr.validate(u_doc) == [], "EC10.record-valid", str(cr.validate(u_doc)))
        check(u_doc["completion"]["state"] == "unknown", "EC10.completion-unknown")
        check(u_doc["observation"]["coherence"] == "unavailable",
              "EC10.observation-unavailable")
        check(u_doc["domain_outcome"]["outcome"] == "unknown"
              and u_doc["domain_outcome"]["exit_code"] == "unavailable",
              "EC10.outcome-never-guessed")
        check(u_doc["next_action"]["action"] == "FIX"
              and "qiven exec list" in u_doc["next_action"]["supported_by"],
              "EC10.fix-names-enumeration-handle", str(u_doc["next_action"]))
        check(u_doc["findings"][0]["rule_id"] == "operator/unknown-exec-id",
              "EC10.finding-rule")

        # ---------------- EC11: exit-zero report law ---------------------
        findings_doc = cr.CommonRecord(
            record_kind="validation",
            producer=cr.Producer(id="ctx-reference-sweep", version="report-v1"),
            operation=cr.Operation(id="ec11-op", repository="p0-closeout-fixture"),
            observation=cr.Observation(coherence="coherent"),
            admission=cr.Admission(state="accepted"),
            completion=cr.Completion(state="completed"),
            # exit ZERO while carrying findings (the report-mode class)
            domain_outcome=cr.DomainOutcome(outcome="findings", exit_code=0),
            coverage=cr.Coverage(collection="complete", executed=["sweep"]),
            findings=[cr.Finding(
                rule_id="ctx/dangling-reference",
                location=cr.FindingLocation(path="README.md", line=3),
                actual="dangling 'tools/gone.py'", expected="existing path",
            )],
            next_action=cr.next_action_for(
                "finding-with-known-pointer",
                "ctx/dangling-reference at README.md:3: restore or update the reference",
            ),
            retry_state=cr.RetryState(side_effects="not_started"),
            payload=cr.Payload(kind="report-stdout", locator="stdout"),
            evidence=[cr.Evidence(locator="sweep stdout", completeness="complete")],
        )
        doc = findings_doc.to_dict()
        check(cr.validate(doc) == [], "EC11.record-valid", str(cr.validate(doc)))
        f_view = rp.project(doc)
        check("verdict=FINDINGS" in f_view.splitlines()[0], "EC11.verdict-findings",
              f_view.splitlines()[0])
        check("verdict=PASSED" not in f_view, "EC11.never-aliased-to-pass")
        check("outcome: findings exit=0" in f_view, "EC11.exit-zero-visible")

    print(f"[ OK ] P0 closeout fixtures ({CHECKS} named checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
