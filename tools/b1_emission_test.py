"""B1 emission fixture suite (ADR-0060 D3; P0 repair batch B1, 2026-10-02).

Covers the B1 emission-completion carriers at the devkit side:
  B1-1  `qiven run` FAIL: selector-law summary line (NEXT action +
        supported_by + evidence) + task-run record + the bounded
        record-projection view riding the FAIL carrier
  B1-2  `qiven run` PASS: the success carrier line stays byte-stable
        (`run: PASS`, no suffix); a task-run record with outcome=passed
        still lands
  B1-3  `qiven ci start` success names its own watch handle (NEXT,
        supported_by = the exact re-call) + ci-dispatch record carrying the
        selected candidate (selected_revision + materialized invocation);
        gh is stubbed at the network seam only (in-process _run_capture)
  B1-3b `qiven ci start --candidate <malformed>` refuses LOCALLY with the
        typed four-element carrier (WHAT/WHY/evidence/NEXT) and dispatches
        nothing (no gh call is made)
  B1-4  `qiven ci watch` non-success terminal verdict teaches its next
        step (DIAGNOSE + the exact gh log command) + ci-watch record;
        explicit-identity mode, gh stubbed at _gh_capture
  B1-5  `qiven exec list` with no runs states itself (no silent success)
  B1-6  `qiven exec status <unknown>` typed answer carries the FIX route
        on the carrier (`qiven exec list`), not only in the record
  B1-7  `qiven gate` FAIL carrier carries the projection view block
        after the byte-stable selector-law summary line

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories).
"""

from __future__ import annotations

import importlib.util
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

OPERATOR = str(ROOT / "tools" / "qiven_operator.py")
CHECKS = 0


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
    spec = importlib.util.spec_from_file_location("qiven_operator_b1", ROOT / "tools" / "qiven_operator.py")
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the canonical devkit qiven_operator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeCapture:
    """Deterministic stand-in for the operator's process-capture seams.

    ci dispatch/list/view argv shapes only; anything unexpected fails the
    test loudly instead of silently succeeding.
    """

    def __init__(self, *, dispatch_rc: int = 0,
                 run_list: list[dict] | None = None,
                 run_view: dict | None = None,
                 passthrough=None,
                 remote_head: str = "",
                 remote_branch: str = "main") -> None:
        self.dispatch_rc = dispatch_rc
        self.run_list = run_list or []
        self.run_view = run_view or {}
        self.passthrough = passthrough
        self.remote_head = remote_head
        self.remote_branch = remote_branch
        self.seen: list[list[str]] = []

    def __call__(self, argv: list[str], *, cwd: Path | None = None):
        self.seen.append(list(argv))

        class _Completed:
            pass

        def _result(rc: int, out: str, err: str = ""):
            result = _Completed()
            result.returncode = rc
            result.stdout = out
            result.stderr = err
            return result

        if argv and argv[0] == "git":
            if argv[1:2] == ["ls-remote"]:
                # fixture remote: the update-ref'd remote-tracking ref IS
                # the stand-in for the unreachable origin URL
                return _result(0, f"{self.remote_head}\trefs/heads/{self.remote_branch}\n")
            if self.passthrough is not None:
                # real git in the fixture repo (only the gh network seam is
                # stubbed - git facts stay real evidence); preserve the
                # original default cwd by omitting the kwarg when unset
                if cwd is None:
                    return self.passthrough(argv)
                return self.passthrough(argv, cwd=cwd)
        if argv[:3] == ["gh", "workflow", "run"]:
            return _result(self.dispatch_rc,
                           "" if self.dispatch_rc == 0 else "dispatch refused")
        if argv[:3] == ["gh", "run", "list"]:
            return _result(0, json.dumps(self.run_list))
        if argv[:3] == ["gh", "run", "view"]:
            return _result(0, json.dumps(self.run_view))
        raise AssertionError(f"unexpected capture argv in fixture: {argv}")


def main() -> int:
    global CHECKS
    with tempfile.TemporaryDirectory(prefix="qiven-b1-emission-") as temp:
        repo = Path(temp) / "repo"
        (repo / ".qiven").mkdir(parents=True)
        config = {
            "schema_version": 1,
            "repository_name": "b1-emission-fixture",
            "default_gate": "b1-pass-gate",
            "tasks": {
                "b1-fail": {"argv": [sys.executable, "-c",
                                     "import sys; sys.stderr.write('boom\\n'); raise SystemExit(3)"]},
                "b1-pass": {"argv": [sys.executable, "-c", "print('b1-pass')"]},
            },
            "gates": {
                "b1-fail-gate": ["b1-fail"],
                "b1-pass-gate": ["b1-pass"],
            },
            "ci": {},
        }
        (repo / ".qiven" / "operator.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        os.environ["QIVEN_TARGET_ROOT"] = str(repo)

        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "B1Emission")
        git(repo, "config", "user.email", "b1@example.invalid")
        git(repo, "remote", "add", "origin", "https://github.com/example/b1-fixture.git")
        git(repo, "add", "--all")
        git(repo, "commit", "-m", "baseline")
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "update-ref", "refs/remotes/origin/main", head)

        records_dir = repo / ".generated-temp" / "operator" / "records"

        def latest_record(prefix: str) -> dict:
            matches = sorted(records_dir.glob(f"{prefix}-*.json"))
            if not matches:
                listing = (
                    [p.name for p in sorted(records_dir.glob("*.json"))]
                    if records_dir.is_dir() else f"records dir missing: {records_dir}"
                )
                raise AssertionError(
                    f"no record emitted for {prefix}; dir state: {listing}"
                )
            return json.loads(matches[-1].read_text(encoding="utf-8"))

        # ---------------- B1-1: run FAIL carrier + record + view --------
        human = run([sys.executable, OPERATOR, "--no-color", "run", "b1-fail"],
                    cwd=repo, expect=1)
        fail_line = next(
            (ln for ln in human.stdout.splitlines() if "run: FAIL" in ln),
            "",
        )
        check("NEXT action: DIAGNOSE" in fail_line, "B1-1.next-action", fail_line)
        check(" - evidence: " in fail_line, "B1-1.evidence-selector", fail_line)
        check("QIVEN-RECORD v1" in human.stdout, "B1-1.projection-view",
              "the bounded record view must ride the FAIL carrier")
        record = latest_record("run")
        check(record.get("record_kind") == "task-run", "B1-1.record-kind")
        check(record.get("next_action", {}).get("action") == "DIAGNOSE", "B1-1.record-next")
        check(record.get("domain_outcome", {}).get("outcome") == "failed", "B1-1.record-outcome")
        doc = cr._as_record_dict(record)
        cr.validate(doc)  # the emitted record satisfies the frozen envelope
        check(True, "B1-1.record-valid")

        # ---------------- B1-2: run PASS stays byte-stable --------------
        human_ok = run([sys.executable, OPERATOR, "--no-color", "run", "b1-pass"],
                       cwd=repo, expect=0)
        check(any(ln.strip() == "[ OK ] run: PASS" for ln in human_ok.stdout.splitlines()),
              "B1-2.pass-line-byte-stable", human_ok.stdout)
        check(not any("NEXT action" in ln for ln in human_ok.stdout.splitlines()),
              "B1-2.pass-no-teaching", "PASS carrier must not grow teaching lines")
        record_ok = latest_record("run")
        check(record_ok.get("domain_outcome", {}).get("outcome") == "passed",
              "B1-2.record-passed")
        check(record_ok.get("next_action", {}).get("action") == "NONE", "B1-2.record-none")

        # ---------------- B1-3: ci start names the watch handle ---------
        operator = load_operator()
        operator.CI_WATCH_POLL_SECONDS = 0.01  # fixture pace, not prod pace
        repo_ci = dict(config)
        repo_ci["ci"] = {"full": {"workflow": "ci.yml", "inputs": {}}}
        operator._load_config = lambda: repo_ci  # type: ignore[assignment]
        real_capture = operator._run_capture
        fake = FakeCapture(dispatch_rc=0, passthrough=real_capture,
                           remote_head=head, remote_branch="main")
        operator._run_capture = fake  # type: ignore[assignment]
        old_argv, old_stdout = sys.argv, sys.stdout
        import io as _io
        try:
            buffer = _io.StringIO()
            sys.stdout = buffer
            sys.argv = [OPERATOR, "--no-color", "ci", "start", "full"]
            code = operator.main()
        finally:
            sys.argv, sys.stdout = old_argv, old_stdout
        out = buffer.getvalue()
        check(code == 0, "B1-3.exit", out[-400:])
        check("NEXT action: qiven ci watch full" in out, "B1-3.watch-handle", out)
        dispatch_record = latest_record("ci-dispatch")
        check(dispatch_record.get("record_kind") == "ci-dispatch", "B1-3.record-kind")
        check(dispatch_record.get("next_action", {}).get("action") == "NEXT",
              "B1-3.record-next")
        check("qiven ci watch full" in str(dispatch_record.get("next_action", {}).get("supported_by")),
              "B1-3.record-supported-by")
        # candidate law (2026-10-03): the record carries the SELECTED
        # candidate (selected_revision) and the materialized invocation —
        # the explicit selection is recorded even in the default-HEAD case.
        check(dispatch_record.get("operation", {}).get("selected_revision") == head,
              "B1-3.record-candidate-selected-revision")
        check(f"--candidate {head}" in str(dispatch_record.get("operation", {}).get("invocation")),
              "B1-3.record-invocation-materialized")
        cr.validate(cr._as_record_dict(dispatch_record))
        check(True, "B1-3.record-valid-with-candidate")

        # ---------------- B1-3b: malformed --candidate refuses locally --
        # The typed four-element carrier fires BEFORE any dispatch surface
        # is touched (fail closed; nothing reaches gh).
        gh_before = [a for a in fake.seen if a[:1] == ["gh"]]
        buffer = _io.StringIO()
        try:
            sys.stdout = buffer
            sys.argv = [OPERATOR, "--no-color", "ci", "start", "full",
                        "--candidate", "deadbeef"]
            code = operator.main()
        finally:
            sys.argv, sys.stdout = old_argv, old_stdout
        out = buffer.getvalue()
        check(code == 2, "B1-3b.exit", out[-400:])
        fail_line = next((ln for ln in out.splitlines() if "[FAIL]" in ln), "")
        check(all(marker in fail_line for marker in
                  ("40-hex", "WHY:", "evidence:", "NEXT action: FIX")),
              "B1-3b.four-element-carrier", fail_line)
        gh_after = [a for a in fake.seen if a[:1] == ["gh"]]
        check(gh_after == gh_before, "B1-3b.no-dispatch",
              "a malformed candidate must never reach gh")

        # ---------------- B1-4: ci watch failure verdict teaches --------
        terminal_run = {
            "databaseId": 4242,
            "headSha": head,
            "status": "completed",
            "conclusion": "failure",
            "url": "https://github.com/example/b1-fixture/actions/runs/4242",
        }
        fake_watch = FakeCapture(run_list=[terminal_run],
                                 run_view={"url": terminal_run["url"],
                                           "status": "completed",
                                           "conclusion": "failure"})
        operator._gh_capture = fake_watch  # type: ignore[assignment]
        buffer = _io.StringIO()
        try:
            sys.stdout = buffer
            sys.argv = [OPERATOR, "--no-color", "ci", "watch", "full"]
            code = operator.main()
        finally:
            sys.argv, sys.stdout = old_argv, old_stdout
        out = buffer.getvalue()
        check(code == 1, "B1-4.exit")
        verdict_line = next(
            (ln for ln in out.splitlines() if "conclusion=failure" in ln), ""
        )
        check("NEXT action: DIAGNOSE" in verdict_line, "B1-4.next-action", verdict_line)
        check("gh run view 4242" in verdict_line and "--log-failed" in verdict_line,
              "B1-4.exact-gh-command", verdict_line)
        watch_record = latest_record("ci-watch")
        check(watch_record.get("record_kind") == "ci-watch", "B1-4.record-kind")
        check(watch_record.get("domain_outcome", {}).get("outcome") == "failed",
              "B1-4.record-outcome")
        check(watch_record.get("next_action", {}).get("action") == "DIAGNOSE",
              "B1-4.record-next")

        # ---------------- B1-5: exec list empty states itself -----------
        listing = run([sys.executable, OPERATOR, "--no-color", "exec", "list"],
                      cwd=repo, expect=0)
        check("no runs" in listing.stdout, "B1-5.empty-stated",
              "empty exec list must not be silent")

        # ---------------- B1-6: unknown exec id carries the FIX route ---
        unknown = run([sys.executable, OPERATOR, "--no-color", "exec", "status",
                       "no-such-run"], cwd=repo, expect=2)
        check("unknown exec id" in unknown.stdout, "B1-6.typed-answer", unknown.stdout)
        check("NEXT action: FIX" in unknown.stdout, "B1-6.fix-route", unknown.stdout)
        check("qiven exec list" in unknown.stdout, "B1-6.enumeration-handle", unknown.stdout)

        # ---------------- B1-7: gate FAIL carries the projection view ---
        gate_fail = run([sys.executable, OPERATOR, "--no-color", "gate",
                         "--name", "b1-fail-gate"], cwd=repo, expect=1)
        summary = next(
            (ln for ln in gate_fail.stdout.splitlines()
             if "gate:b1-fail-gate: FAIL" in ln),
            "",
        )
        check("NEXT action:" in summary and " - evidence: " in summary,
              "B1-7.selector-line", summary)
        check("QIVEN-RECORD v1" in gate_fail.stdout, "B1-7.projection-view",
              "the bounded record view must ride the gate FAIL carrier")
        # the selector-law line stays ONE line (class + action + locator);
        # the view block follows it, never merges into it
        check(not re.search(r"NEXT action:.*NEXT action:", summary), "B1-7.one-action")

        print(f"[ OK ] b1-emission: {CHECKS} checks")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
