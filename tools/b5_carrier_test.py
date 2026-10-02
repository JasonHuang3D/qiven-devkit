"""B5 carrier fixture suite (ADR-0060 D3; P0 repair batch B5, 2026-10-02).

Covers the B5 build/test carrier envelope at the devkit side:
  B5-S1   `qiven exec sweep` with nothing to do states itself (NEXT NONE)
  B5-S2   `qiven exec sweep` with reconciled actions teaches WHY (lease
          law, exit codes never guessed) + the DIAGNOSE read-back route
  B5-T3   `qiven run <task>` FAIL through the real CLI: task-level
          four-element carrier (rule + retained-evidence locator + NEXT
          DIAGNOSE with the evidence-read handle) composed with the
          run-level selector line and the record projection view
  B5-T4   `qiven run` PASS stays byte-stable (no teaching lines)
  B5-CI1..3  .github/workflows/ci.yml: the plan's unknown-unit rejection
          and the ci-gate failure carry rule + WHY + NEXT; the pass line
          stays byte-stable

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "tools" / "qiven_operator.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CHECKS = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(argv: list[str], *, cwd: Path, expect: int | None = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if expect is not None and completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], cwd=repo)


def make_fixture(temp: Path, name: str, tasks: dict) -> Path:
    repo = temp / name
    repo.mkdir(parents=True)
    (repo / ".gitignore").write_text(".generated-temp/\n", encoding="utf-8")
    (repo / ".qiven").mkdir()
    config = {
        "schema_version": 1,
        "repository_name": name,
        "default_gate": "b5-gate",
        "tasks": tasks,
        "gates": {"b5-gate": list(tasks)},
        "ci": {},
    }
    (repo / ".qiven" / "operator.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "B5Carrier")
    git(repo, "config", "user.email", "b5@example.invalid")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "baseline")
    return repo


def op_run(repo: Path, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "QIVEN_TARGET_ROOT": str(repo)}
    completed = subprocess.run(
        [sys.executable, str(OPERATOR), "--no-color", *args],
        cwd=repo, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {args}\n{completed.stdout}"
        )
    return completed


def sweep_cases(temp: Path) -> None:
    # ---------------- S1: no actions states itself -------------------
    repo = make_fixture(temp, "b5-sweep-empty", {"noop": {"argv": ["cmd", "/c", "exit", "0"]}})
    done = op_run(repo, "exec", "sweep")
    check("[ OK ] exec sweep: no actions" in done.stdout, "B5-S1.no-action-stated", done.stdout)
    check("NEXT action: NONE - nothing to reconcile" in done.stdout,
          "B5-S1.next-none", done.stdout)

    # ---------------- S2: reconciled actions teach WHY + NEXT --------
    repo = make_fixture(temp, "b5-sweep-stale", {"noop": {"argv": ["cmd", "/c", "exit", "0"]}})
    exec_dir = repo / ".generated-temp" / "operator" / "exec"
    exec_dir.mkdir(parents=True, exist_ok=True)
    stale_id = "20260101T000000Z-00000001-b5swee"
    (exec_dir / f"{stale_id}.json").write_text(
        json.dumps({
            "schema": 2, "id": stale_id, "argv": ["gone"], "pid": 4194303,
            "watchdog_pid": 4194302, "job_name": f"qiven-exec-{stale_id}",
            "log": str(exec_dir / f"{stale_id}.log"),
            "started_utc": "2026-01-01T00:00:00Z",
            "deadline_utc": "2026-01-01T00:10:00Z",
            "max_lifetime_seconds": 600.0, "status": "running",
        }),
        encoding="utf-8",
    )
    done = op_run(repo, "exec", "sweep")
    check(f"exec sweep:" in done.stdout and stale_id in done.stdout,
          "B5-S2.action-listed", done.stdout)
    check("why:" in done.stdout and "past their lease or stale" in done.stdout,
          "B5-S2.why-lease-law", done.stdout)
    check("exit code is unknown and never guessed" in done.stdout,
          "B5-S2.why-never-guessed", done.stdout)
    check("NEXT action: DIAGNOSE - read each run's log" in done.stdout,
          "B5-S2.next-diagnose", done.stdout)
    check(".generated-temp/operator/exec/" in done.stdout,
          "B5-S2.log-route", done.stdout)
    record_after = json.loads((exec_dir / f"{stale_id}.json").read_text(encoding="utf-8"))
    check(record_after.get("status") in ("expired", "indeterminate", "stopped"),
          "B5-S2.record-finalized", str(record_after.get("status")))


def task_cases(temp: Path) -> None:
    tasks = {
        "b5-fail": {"argv": [sys.executable, "-c",
                             "print('b5-head'); raise SystemExit(3)"]},
        "b5-pass": {"argv": [sys.executable, "-c", "print('b5-ok')"]},
    }
    repo = make_fixture(temp, "b5-task-carriers", tasks)

    # ---------------- T3: run FAIL four-element composition ----------
    done = op_run(repo, "run", "b5-fail", expect=1)
    check("[FAIL] b5-fail: exit 3" in done.stdout, "B5-T3.what-line", done.stdout)
    check("rule: operator/task-failed" in done.stdout, "B5-T3.task-rule", done.stdout)
    check("full output retained at:" in done.stdout, "B5-T3.evidence-locator", done.stdout)
    check("NEXT: DIAGNOSE -" in done.stdout and "qiven evidence-read" in done.stdout,
          "B5-T3.task-next", done.stdout)
    check("re-run `qiven run b5-fail`" in done.stdout, "B5-T3.rerun-command", done.stdout)
    summary = next((ln for ln in done.stdout.splitlines() if "run: FAIL" in ln), "")
    check("NEXT action: DIAGNOSE" in summary, "B5-T3.run-selector-next", summary)
    check(" - evidence: " in summary, "B5-T3.run-selector-evidence", summary)
    check("QIVEN-RECORD v1" in done.stdout, "B5-T3.projection-view", done.stdout)

    # ---------------- T4: run PASS stays byte-stable -----------------
    done = op_run(repo, "run", "b5-pass")
    check(any(ln.strip() == "[ OK ] run: PASS" for ln in done.stdout.splitlines()),
          "B5-T4.pass-line-byte-stable", done.stdout)
    check(not any("NEXT" in ln for ln in done.stdout.splitlines()),
          "B5-T4.pass-no-teaching", "PASS carrier must not grow teaching lines")


def ci_cases() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    # CI1: the plan's unknown-unit rejection teaches WHY + FIX
    check("Unknown validation unit:" in text, "B5-CI1.typed-what")
    check("rule: devkit/ci-plan" in text, "B5-CI1.rule")
    check("NEXT action: FIX - re-dispatch with jobs=full" in text, "B5-CI1.fix-route")
    # CI2: the ci-gate failure teaches WHY + DIAGNOSE
    check("[FAIL] CI Gate: WHY:" in text, "B5-CI2.fail-what-why")
    check("rule: devkit/ci-gate" in text, "B5-CI2.rule")
    check("NEXT action: DIAGNOSE - open the failed unit's step logs" in text,
          "B5-CI2.diagnose-route")
    check("without a fix is not a retry" in text, "B5-CI2.no-blind-retry")
    # CI3: the pass line stays byte-stable
    check("CI Gate: requested validation passed" in text, "B5-CI3.pass-line-stable")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qiven-b5-carrier-") as temp_name:
        temp = Path(temp_name)
        sweep_cases(temp)
        task_cases(temp)
    ci_cases()
    print(f"[ OK ] b5-carrier: {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
