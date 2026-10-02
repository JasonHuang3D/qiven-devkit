"""B7a carrier fixture suite (ADR-0060 D3; P0 repair batch B7a, 2026-10-02).

Covers the B7a four-element carrier upgrades at the devkit side:
  B7a-1..3   gate_proof builtin: missing-receipt / stale-receipt FAIL
             carriers (rule + receipt locator + FIX route; prefix bytes
             pinned) and the byte-stable PASS line
  B7a-4..6   git_clean_tree builtin: dirty FAIL carrier (bounded listing
             + rule + FIX), the 8-finding omission budget, PASS shape
  B7a-7..8   git_diff_check builtin: whitespace FAIL carrier (rule +
             bounded findings + FIX) and PASS shape
  B7a-9..11  launcher qiven.cmd: QIVEN_PYTHON-invalid and
             no-supported-python FAIL carriers (four elements, first
             line byte-stable) + the template .in stays the normalized
             byte twin of the devkit launcher
  B7a-12..17 QivenRepoNew / QivenRepoAdopt / QivenRepoSync generator
             rejections carry rule + evidence + NEXT (classification
             prefix bytes stable; the pinned 'use sync-repo' wording
             intact); the sync conflict is driven end-to-end from a
             real generation
  B7a-18..20 tool wrappers new/adopt/sync: usage rejections carry the
             four-element carrier (exit 2)
  B7a-21..24 task wrappers: every self-test script routes its assertion
             failures through the shared four-element renderer; the
             renderer itself is driven; commit-subjects and
             resolver-patterns FAIL carriers are driven on fixtures;
             commit-subjects PASS bytes stay stable
  B7a-25..27 cmake suite carriers: fail() renders rule+evidence+NEXT and
             is defined before first use; cmd-control-flow sites carry
             NEXT; SKIP carriers state evidence + NEXT

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "tools" / "qiven_operator.py"
DEVKIT_CMD = ROOT / "tools" / "qiven.cmd"
TEMPLATE_CMD = ROOT / "templates" / "cpp-library" / "managed" / "tools" / "qiven.cmd.in"
CHECKS = 0

SELFTEST_SCRIPTS = (
    "operator-test.py", "common_record_test.py", "record_projection_test.py",
    "p0_closeout_test.py", "context_records_crosscheck_test.py",
    "router_record_adapter_test.py", "workspace_schemas_test.py",
    "workspace_resolver_test.py", "workspace_bootstrap_test.py",
    "workspace_shadow_test.py", "workspace_profile_b_test.py",
    "hook_exec_router_test.py", "check_resolver_patterns_test.py",
    "b2_envelope_test.py",
)


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(argv: list[str], *, cwd: Path, expect: int | None = 0,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if expect is not None and completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], cwd=repo)


def make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "B7aCarrier")
    git(path, "config", "user.email", "b7a@example.invalid")
    # the operator's own bookkeeping (records/receipts/durations) lives in
    # the repo-local generated-temp area; ignore it like every real repo
    # does so clean-tree fixtures measure only the fixture's dirt
    (path / ".gitignore").write_text(".generated-temp/\n", encoding="utf-8")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(path, "add", "--all")
    git(path, "commit", "-m", "baseline")
    return path


def operator_fixture(temp: Path, name: str, tasks: dict) -> tuple[Path, Path]:
    repo = make_git_repo(temp / name)
    (repo / ".qiven").mkdir()
    config = {
        "schema_version": 1,
        "repository_name": name,
        "default_gate": "b7a-gate",
        "tasks": tasks,
        "gates": {"b7a-gate": list(tasks)},
        "ci": {},
    }
    (repo / ".qiven" / "operator.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "operator config")
    return repo, repo / ".qiven" / "operator.json"


def op_run(repo: Path, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "QIVEN_TARGET_ROOT": str(repo)}
    return run([sys.executable, str(OPERATOR), "--no-color", *args],
               cwd=repo, expect=expect, env=env)


def head_of(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def write_receipt(repo: Path, gate: str, head: str, status: str) -> Path:
    path = repo / ".generated-temp" / "operator" / "receipts" / f"{gate}-{head}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"gate": gate, "head": head, "status": status,
                                "timestamp": "2026-10-02T00:00:00Z", "tasks": []}),
                    encoding="utf-8")
    return path


def builtin_cases(temp: Path) -> None:
    # B7a-1: gate_proof missing receipt
    repo, _ = operator_fixture(
        temp, "b7a-gp-missing",
        {"merge-proof": {"builtin": "gate_proof", "gate": "b7a-gate"}})
    head = head_of(repo)
    done = op_run(repo, "run", "merge-proof", expect=1)
    check(f"no b7a-gate PASS receipt for exact head {head[:12]}" in done.stdout,
          "B7a-1.pinned-prefix", done.stdout)
    check("rule: operator/gate-proof-missing-receipt" in done.stdout, "B7a-1.rule", done.stdout)
    check(".generated-temp" in done.stdout and "receipts" in done.stdout
          and "absent" in done.stdout, "B7a-1.evidence-locator", done.stdout)
    check("NEXT: FIX - run `qiven gate --name b7a-gate`" in done.stdout,
          "B7a-1.fix-route", done.stdout)

    # B7a-2: gate_proof stale receipt (wrong status for the exact head)
    repo, _ = operator_fixture(
        temp, "b7a-gp-stale",
        {"merge-proof": {"builtin": "gate_proof", "gate": "b7a-gate"}})
    head = head_of(repo)
    write_receipt(repo, "b7a-gate", head, "fail")
    done = op_run(repo, "run", "merge-proof", expect=1)
    check(f"receipt for {head[:12]} is not a matching PASS" in done.stdout,
          "B7a-2.pinned-prefix", done.stdout)
    check("rule: operator/gate-proof-stale-receipt" in done.stdout, "B7a-2.rule", done.stdout)
    check("NEXT: FIX - run `qiven gate --name b7a-gate`" in done.stdout,
          "B7a-2.fix-route", done.stdout)

    # B7a-3: gate_proof PASS stays byte-stable
    repo, _ = operator_fixture(
        temp, "b7a-gp-pass",
        {"merge-proof": {"builtin": "gate_proof", "gate": "b7a-gate"}})
    head = head_of(repo)
    write_receipt(repo, "b7a-gate", head, "pass")
    done = op_run(repo, "run", "merge-proof")
    check(f"[ OK ] merge-proof: b7a-gate PASS @ {head[:12]}" in done.stdout,
          "B7a-3.pass-byte-stable", done.stdout)
    check("NEXT" not in done.stdout, "B7a-3.pass-no-teaching", done.stdout)

    # B7a-4: git_clean_tree dirty FAIL carrier
    repo, _ = operator_fixture(temp, "b7a-clean", {"clean-tree": {"builtin": "git_clean_tree"}})
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    done = op_run(repo, "run", "clean-tree", expect=1)
    check("working tree is not clean" in done.stdout, "B7a-4.pinned-detail", done.stdout)
    check("rule: operator/clean-tree" in done.stdout, "B7a-4.rule", done.stdout)
    check("?? untracked.txt" in done.stdout, "B7a-4.evidence-listing", done.stdout)
    check("NEXT: FIX - commit or stash" in done.stdout, "B7a-4.fix-route", done.stdout)

    # B7a-5: the dirty listing is bounded to the 8-finding D3 budget
    repo, _ = operator_fixture(temp, "b7a-clean-cap", {"clean-tree": {"builtin": "git_clean_tree"}})
    for n in range(12):
        (repo / f"dirty-{n:02d}.txt").write_text("dirty\n", encoding="utf-8")
    done = op_run(repo, "run", "clean-tree", expect=1)
    check("[evidence: first 8 of 12 dirty path(s)" in done.stdout,
          "B7a-5.omission-count", done.stdout)
    check("--untracked-files=all" in done.stdout, "B7a-5.full-listing-pointer", done.stdout)

    # B7a-6: clean-tree PASS shape (duration form, no teaching)
    repo, _ = operator_fixture(temp, "b7a-clean-pass", {"clean-tree": {"builtin": "git_clean_tree"}})
    done = op_run(repo, "run", "clean-tree")
    check("[ OK ] clean-tree (" in done.stdout, "B7a-6.pass-shape", done.stdout)
    check("NEXT" not in done.stdout, "B7a-6.pass-no-teaching", done.stdout)

    # B7a-7: git_diff_check whitespace FAIL carrier
    repo, _ = operator_fixture(temp, "b7a-diff", {"diff-check": {"builtin": "git_diff_check",
                                                                 "base": "origin/main"}})
    head = head_of(repo)
    git(repo, "update-ref", "refs/remotes/origin/main", head)
    (repo / "ws.txt").write_text("trailing whitespace   \n", encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "introduce whitespace error")
    done = op_run(repo, "run", "diff-check", expect=1)
    check("git diff --check failed vs origin/main...HEAD" in done.stdout,
          "B7a-7.what", done.stdout)
    check("rule: operator/diff-check" in done.stdout, "B7a-7.rule", done.stdout)
    check("ws.txt" in done.stdout, "B7a-7.evidence-listing", done.stdout)
    check("NEXT: FIX - fix the whitespace/conflict markers" in done.stdout,
          "B7a-7.fix-route", done.stdout)
    check("git diff --check origin/main...HEAD" in done.stdout,
          "B7a-7.full-listing-pointer", done.stdout)

    # B7a-8: diff-check PASS shape
    repo, _ = operator_fixture(temp, "b7a-diff-pass", {"diff-check": {"builtin": "git_diff_check",
                                                                      "base": "origin/main"}})
    head = head_of(repo)
    git(repo, "update-ref", "refs/remotes/origin/main", head)
    done = op_run(repo, "run", "diff-check")
    check("[ OK ] diff-check (" in done.stdout, "B7a-8.pass-shape", done.stdout)
    check("NEXT" not in done.stdout, "B7a-8.pass-no-teaching", done.stdout)


def launcher_cases() -> None:
    # B7a-9: QIVEN_PYTHON invalid (points at nothing runnable) -> typed
    # four-element refusal, exit 2; the probe degrades honestly to
    # "printed no version" rather than hanging on an interactive child
    env = {**os.environ,
           "QIVEN_PYTHON": str(Path(tempfile.gettempdir()) / "b7a-no-such-python.exe")}
    done = run(["cmd.exe", "/d", "/c", "call", str(DEVKIT_CMD)], cwd=ROOT, expect=2, env=env)
    check("[FAIL] QIVEN_PYTHON must point to Python 3.9 or newer:" in done.stdout,
          "B7a-9.first-line-stable", done.stdout)
    check("evidence: the configured interpreter reports Python" in done.stdout,
          "B7a-9.evidence", done.stdout)
    check("NEXT: FIX - point QIVEN_PYTHON at a Python 3.9 or newer executable" in done.stdout,
          "B7a-9.fix-route", done.stdout)

    # B7a-10: no supported python on PATH -> typed refusal naming every probe
    env = {**os.environ, "PATH": str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                                     / "System32")}
    env.pop("QIVEN_PYTHON", None)
    done = run(["cmd.exe", "/d", "/c", "call", str(DEVKIT_CMD)], cwd=ROOT, expect=2, env=env)
    check("[FAIL] Qiven Operator requires Python 3.9 or newer. Set QIVEN_PYTHON or "
          "make a supported python available on PATH." in done.stdout,
          "B7a-10.first-line-stable", done.stdout)
    check("every candidate failed the 3.9+ probe" in done.stdout, "B7a-10.evidence",
          done.stdout)
    check("NEXT: FIX - set QIVEN_PYTHON to a Python 3.9+ executable path" in done.stdout,
          "B7a-10.fix-route", done.stdout)

    # B7a-11: the template .in stays the normalized byte twin of the launcher
    live = (DEVKIT_CMD).read_bytes().replace(b"\r\n", b"\n")
    template = (TEMPLATE_CMD).read_bytes().replace(b"\r\n", b"\n")
    check(live == template, "B7a-11.template-twin",
          "tools/qiven.cmd and templates/.../qiven.cmd.in must stay byte-identical "
          "modulo line endings")


def cmake_generator_cases(temp: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from toolchain import resolve  # noqa: E402
    cmake = resolve()["cmake"]
    common = ["-DDEVKIT_ROOT=" + str(ROOT), "-DREPOSITORY_NAME=g", "-DCMAKE_PROJECT_NAME=g",
              "-DCMAKE_TARGET_NAME=g", "-DCMAKE_ALIAS=qiven::g", "-DCPP_NAMESPACE=qiven::g",
              "-DTEST_OPTION_NAME=G_TESTS", "-DVS_SOLUTION_NAME=g"]

    def generate(script: Path, defs: list[str], *, cwd: Path,
                 expect_ok: bool) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run([cmake, *defs, "-P", str(script)], cwd=cwd, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   check=False)
        if expect_ok and completed.returncode != 0:
            raise AssertionError(f"expected success: {script} {defs}\n{completed.stdout}")
        if not expect_ok and completed.returncode == 0:
            raise AssertionError(f"expected rejection: {script} {defs}\n{completed.stdout}")
        return completed

    # B7a-12: New refuses a non-empty destination with the four elements
    dest = temp / "new-dest"
    dest.mkdir()
    (dest / "keep.txt").write_text("keep\n", encoding="utf-8")
    done = generate(ROOT / "cmake" / "QivenRepoNew.cmake",
                    common[:1] + [f"-DDESTINATION={dest}"] + common[1:],
                    cwd=temp, expect_ok=False)
    check("Destination contains existing content" in done.stdout, "B7a-12.prefix-stable",
          done.stdout)
    check("rule: qivenrepo/new/destination-not-empty" in done.stdout, "B7a-12.rule", done.stdout)
    check("keep.txt" in done.stdout, "B7a-12.evidence", done.stdout)
    check("NEXT: FIX - point DESTINATION at an empty or nonexistent directory" in done.stdout,
          "B7a-12.fix-route", done.stdout)

    # B7a-13: New rejects an invalid template family id
    done = generate(ROOT / "cmake" / "QivenRepoNew.cmake",
                    common[:1] + [f"-DDESTINATION={temp / 'never'}", "-DTEMPLATE=Bad_Family"]
                    + common[1:], cwd=temp, expect_ok=False)
    check("Invalid template family: Bad_Family" in done.stdout, "B7a-13.prefix-stable",
          done.stdout)
    check("rule: qivenrepo/new/invalid-template-family" in done.stdout, "B7a-13.rule",
          done.stdout)
    check("NEXT: FIX -" in done.stdout, "B7a-13.fix-route", done.stdout)

    # B7a-14: Adopt refuses an already-managed repo (pinned 'use sync-repo' wording)
    repo = make_git_repo(temp / "adopt-managed")
    (repo / ".qiven").mkdir()
    done = generate(ROOT / "cmake" / "QivenRepoAdopt.cmake",
                    common[:1] + ["-DMODE=check", f"-DREPOSITORY={repo}"] + common[1:],
                    cwd=temp, expect_ok=False)
    # cmake wraps long message() lines; assert the pinned wording in parts
    check("Target already contains .qiven ownership state" in done.stdout
          and "use sync-repo" in done.stdout, "B7a-14.pinned-wording", done.stdout)
    check("rule: qivenrepo/adopt/already-managed" in done.stdout, "B7a-14.rule", done.stdout)
    check("NEXT: FIX - run the sync path instead" in done.stdout, "B7a-14.fix-route",
          done.stdout)

    # B7a-15: Adopt MODE law
    done = generate(ROOT / "cmake" / "QivenRepoAdopt.cmake",
                    common[:1] + ["-DMODE=CHECK", f"-DREPOSITORY={temp / 'nowhere'}"]
                    + common[1:], cwd=temp, expect_ok=False)
    check("MODE must be exactly check or apply" in done.stdout, "B7a-15.prefix-stable",
          done.stdout)
    check("rule: qivenrepo/adopt/mode-law" in done.stdout, "B7a-15.rule", done.stdout)
    check("NEXT: FIX - re-run with MODE check" in done.stdout, "B7a-15.fix-route", done.stdout)

    # B7a-16: Sync refuses an unmanaged repository
    repo = make_git_repo(temp / "sync-unmanaged")
    done = generate(ROOT / "cmake" / "QivenRepoSync.cmake",
                    [common[0], f"-DREPOSITORY={repo}"], cwd=temp, expect_ok=False)
    check("Repository lacks qiven-devkit metadata" in done.stdout, "B7a-16.prefix-stable",
          done.stdout)
    check("rule: qivenrepo/sync/not-managed" in done.stdout, "B7a-16.rule", done.stdout)
    check("NEXT: FIX - adopt first" in done.stdout, "B7a-16.fix-route", done.stdout)

    # B7a-17: full flow - generate, commit, dirty a managed file, sync conflicts
    managed = temp / "sync-conflict-repo"
    generate(ROOT / "cmake" / "QivenRepoNew.cmake",
             common[:1] + [f"-DDESTINATION={managed}"] + common[1:], cwd=temp, expect_ok=True)
    git(managed, "init", "-b", "main")
    git(managed, "config", "user.name", "B7aCarrier")
    git(managed, "config", "user.email", "b7a@example.invalid")
    git(managed, "add", "--all")
    git(managed, "commit", "-m", "baseline")
    (managed / ".clang-format").write_text("# consumer edit\n", encoding="utf-8")
    done = generate(ROOT / "cmake" / "QivenRepoSync.cmake",
                    [common[0], f"-DREPOSITORY={managed}"], cwd=temp, expect_ok=False)
    check("Managed-file conflict; no files changed" in done.stdout, "B7a-17.prefix-stable",
          done.stdout)
    check(".clang-format" in done.stdout, "B7a-17.evidence-paths", done.stdout)
    check("rule: qivenrepo/sync/conflict" in done.stdout, "B7a-17.rule", done.stdout)
    check("NEXT: FIX - for each listed path" in done.stdout, "B7a-17.fix-route", done.stdout)


def tool_usage_cases() -> None:
    # B7a-18: new_cpp_library usage rejection
    done = run([sys.executable, str(ROOT / "tools" / "new_cpp_library.py"), "a", "b"],
               cwd=ROOT, expect=2)
    check("[FAIL] new_cpp_library.py: usage rejected" in done.stdout, "B7a-18.what", done.stdout)
    check("evidence: got 2 argument(s)" in done.stdout, "B7a-18.evidence", done.stdout)
    check("NEXT: FIX - re-run with the documented argument order" in done.stdout,
          "B7a-18.fix-route", done.stdout)

    # B7a-19: adopt_cpp_library mode-law rejection
    done = run([sys.executable, str(ROOT / "tools" / "adopt_cpp_library.py"), "CHECK", "x"],
               cwd=ROOT, expect=2)
    check("[FAIL] adopt_cpp_library.py: usage rejected" in done.stdout, "B7a-19.what", done.stdout)
    check("MODE is case-sensitive" in done.stdout, "B7a-19.why", done.stdout)
    check("NEXT: FIX - re-run with MODE check first" in done.stdout, "B7a-19.fix-route",
          done.stdout)

    # B7a-20: sync_repo usage rejection
    done = run([sys.executable, str(ROOT / "tools" / "sync_repo.py")], cwd=ROOT, expect=2)
    check("[FAIL] sync_repo.py: usage rejected" in done.stdout, "B7a-20.what", done.stdout)
    check("NEXT: FIX - re-run as: python tools/sync_repo.py <repository-root>" in done.stdout,
          "B7a-20.fix-route", done.stdout)


def task_wrapper_cases(temp: Path) -> None:
    # B7a-21: every self-test script routes assertion failures through the
    # shared four-element renderer (structural; the behavior case is B7a-22)
    tail = ("if __name__ == \"__main__\":\n"
            "    import selftest_carrier\n"
            "    raise SystemExit(selftest_carrier.run(__file__, main))\n")
    for name in SELFTEST_SCRIPTS:
        text = (ROOT / "tools" / name).read_text(encoding="utf-8")
        check(text.endswith(tail), f"B7a-21.{name}", "renderer wiring tail missing")

    # B7a-22: the renderer itself, driven in-process
    spec = importlib.util.spec_from_file_location("selftest_carrier_b7a",
                                                  ROOT / "tools" / "selftest_carrier.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def failing_main() -> int:
        raise AssertionError("B7X: fixture case violated")

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            code = module.run(str(ROOT / "tools" / "common_record_test.py"), failing_main)
    finally:
        sys.stdout = sys.__stdout__
    out = buffer.getvalue()
    check(code == 1, "B7a-22.exit")
    check("Traceback (most recent call last)" in out, "B7a-22.traceback-verbatim", out[:400])
    check("[FAIL] common_record_test.py: self-test case failed - B7X: fixture case violated"
          in out, "B7a-22.what", out[-600:])
    check("why: the case text names the violated law" in out, "B7a-22.why", out[-600:])
    check("evidence: complete traceback above" in out, "B7a-22.evidence", out[-600:])
    check("NEXT: DIAGNOSE - re-run `python tools/common_record_test.py`" in out,
          "B7a-22.next", out[-600:])

    # B7a-23: commit-subjects FAIL carrier, driven on a fixture repository
    # (the tool resolves its repository from its own path, so a copy runs
    # against the fixture - the b3 live-tool pattern)
    repo = temp / "subjects"
    (repo / "tools").mkdir(parents=True)
    source_tool = ROOT / "tools" / "check_commit_subjects.py"
    (repo / "tools" / "check_commit_subjects.py").write_bytes(source_tool.read_bytes())
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "B7aCarrier")
    git(repo, "config", "user.email", "b7a@example.invalid")
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "role: jason-worker\nLLM: m\n\nfeat(x): regressed layout")
    done = run([sys.executable, str(repo / "tools" / "check_commit_subjects.py")],
               cwd=repo, expect=1)
    check("[FAIL] 1 commit subject(s) start with 'role:'" in done.stdout, "B7a-23.what",
          done.stdout)
    check("law: pit P-51" in done.stdout, "B7a-23.why", done.stdout)
    check("NEXT: FIX - rewrite the offender commits" in done.stdout, "B7a-23.fix-route",
          done.stdout)

    # commit-subjects PASS bytes stay stable on a clean fixture
    clean = temp / "subjects-clean"
    (clean / "tools").mkdir(parents=True)
    (clean / "tools" / "check_commit_subjects.py").write_bytes(source_tool.read_bytes())
    git(clean, "init", "-b", "main")
    git(clean, "config", "user.name", "B7aCarrier")
    git(clean, "config", "user.email", "b7a@example.invalid")
    (clean / "f.txt").write_text("x\n", encoding="utf-8")
    git(clean, "add", "--all")
    git(clean, "commit", "-m", "feat(x): good subject\n\nbody\n\nrole: jason-worker")
    done = run([sys.executable, str(clean / "tools" / "check_commit_subjects.py")], cwd=clean)
    check("[ OK ] commit subjects clean (attribution in trailer position)" in done.stdout,
          "B7a-23.pass-byte-stable", done.stdout)

    # B7a-24: resolver-patterns FAIL carrier, driven on a fixture repository
    repo = temp / "patterns"
    repo.mkdir()
    (repo / "CMakeLists.txt").write_text(
        "target_link_libraries(x PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../qiven-math)\n",
        encoding="utf-8")
    done = run([sys.executable, str(ROOT / "tools" / "check_resolver_patterns.py"),
                "--repo", str(repo)], cwd=repo, expect=1)
    check("R1 patterns/CMakeLists.txt" in done.stdout, "B7a-24.rule-letter-site",
          done.stdout)
    check("[FAIL] forbidden resolver patterns: 1 finding(s)" in done.stdout, "B7a-24.what",
          done.stdout)
    check("taxonomy R1-R6" in done.stdout, "B7a-24.why", done.stdout)
    check("NEXT: FIX - remove the forbidden pattern" in done.stdout, "B7a-24.fix-route",
          done.stdout)


def cmake_suite_cases() -> None:
    # B7a-25: test.cmake fail() renders the four elements and is defined
    # BEFORE its first parse-time call (the latent unknown-command class)
    text = (ROOT / "tools" / "test.cmake").read_text(encoding="utf-8")
    check("NEXT: DIAGNOSE - re-run qiven run devkit-regression" in text, "B7a-25.fail-next")
    check("rule: devkit-regression assertion" in text, "B7a-25.fail-rule")
    check("disposable fixtures at ${fixtures}" in text, "B7a-25.fail-evidence")
    definition = text.index("function(fail message_text)")
    first_use = text.index('fail("could not derive the current template version')
    check(definition < first_use, "B7a-25.fail-defined-before-use",
          "fail() must be defined before its first parse-time call")
    adopt = (ROOT / "tools" / "adoption-missing-sync-test.cmake").read_text(encoding="utf-8")
    check("NEXT: DIAGNOSE - re-run qiven run adoption-missing-sync" in adopt,
          "B7a-25.missing-sync-next")

    # B7a-26: cmd-control-flow assertion sites carry NEXT lines
    control = (ROOT / "tools" / "cmd-control-flow-test.cmake").read_text(encoding="utf-8")
    check(control.count("NEXT: FIX -") >= 4, "B7a-26.next-per-site",
          "each guarded law needs its FIX route")
    check("Generated CMD control-flow regression checks passed" in control,
          "B7a-26.pass-line-stable")

    # B7a-27: SKIP carriers state evidence and a NEXT action
    crosscheck = (ROOT / "tools" / "context_records_crosscheck_test.py").read_text(
        encoding="utf-8")
    check("[SKIP] XC2: evidence:" in crosscheck and "NEXT: NEXT - run inside the qiven "
          "workspace layout" in crosscheck, "B7a-27.xc2-skip-carrier")
    bootstrap = (ROOT / "tools" / "workspace_bootstrap_test.py").read_text(encoding="utf-8")
    check("[SKIP] B1-B6: evidence:" in bootstrap and "NEXT: NEXT - run inside the qiven "
          "workspace" in bootstrap, "B7a-27.bootstrap-skip-carrier")

    # router summary carrier (structural pin; the source wraps the line)
    router = (ROOT / "tools" / "hook_exec_router_test.py").read_text(encoding="utf-8")
    check("NEXT: DIAGNOSE - re-run `python " in router
          and "fix the classifier branch for the" in router,
          "B7a-27.router-summary")


def main() -> int:
    global CHECKS
    with tempfile.TemporaryDirectory(prefix="qiven-b7a-carrier-") as temp_name:
        temp = Path(temp_name)
        builtin_cases(temp)
        launcher_cases()
        cmake_generator_cases(temp)
        tool_usage_cases()
        task_wrapper_cases(temp)
    cmake_suite_cases()
    print(f"[ OK ] b7a-carrier: {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
