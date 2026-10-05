"""B3 template fixture suite (ADR-0060 D3; P0 repair batch B3, 2026-10-02).

Covers the B3 template-reunification surface at the devkit side:
  B3-T1  the template launcher (qiven.py.in) IS the strict R6b variant,
        behaviorally: unreadable / non-object / rejected preflight
        receipts fail typed BEFORE any operator import; notes surface;
        missing bootstrap is named
  B3-T2  source contract: the strict refusal markers are present and
        the warn-and-continue drift marker is gone from every template
        launcher copy
  B3-T3  the rendered managed tool set passes the managed B3 carrier
        suite (what a newly generated repository ships and gates on)
  B3-T4  the template manifest declares the carrier suite as managed
        and the operator policy wires it into the local gate
  B3-T5  the devkit's own live format_sources.py emits the same
        four-element carriers (counts + rule + FIX/DIAGNOSE routes,
        bounded evidence, byte-stable PASS)

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
MANAGED = ROOT / "templates" / "cpp-library" / "managed"
TOOLS = MANAGED / "tools"
CHECKS = 0
CANNED_WARNING = "warning: code should be clang-formatted [-Wclang-format-violations]"
RENDERED_TOOLS = ("tools/qiven.py", "tools/format_sources.py",
                  "tools/apply_patch.py", "tools/b3_carrier_test.py")


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(argv: list[str], *, cwd: Path, expect: int = 0,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], cwd=repo)


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def render_tools(destination: Path) -> None:
    """Render the placeholder-free managed tool templates into a fixture
    tools directory (what QivenRepoSync's configure_file(@ONLY) emits)."""
    (destination / "tools").mkdir(parents=True, exist_ok=True)
    for relative in RENDERED_TOOLS:
        source = MANAGED / (relative + ".in")
        if not source.is_file():
            raise AssertionError(f"managed template missing: {source}")
        shutil.copyfile(source, destination / relative)


def make_repo(temp: Path, name: str) -> Path:
    repo = temp / name
    (repo / "tools").mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "B3Template")
    git(repo, "config", "user.email", "b3@example.invalid")
    return repo


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "--all")
    git(repo, "commit", "-m", message)


def template_launcher_cases(temp: Path) -> None:
    launcher = TOOLS / "qiven.py.in"
    control = temp / "t1-control"
    (control / "bootstrap").mkdir(parents=True)
    devkit = temp / "t1-devkit"
    (devkit / "tools").mkdir(parents=True)
    write(devkit / "tools" / "qiven_operator.py",
          "def main() -> int:\n    print('OPERATOR-REACHED')\n    return 0\n")
    bootstrap = control / "bootstrap" / "qiven-bootstrap.py"

    def launch(control_dir: Path) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "QIVEN_WORKSPACE_CONTROL": str(control_dir),
               "QIVEN_DEVKIT_CHECKOUT": str(devkit)}
        return subprocess.run(
            [sys.executable, str(launcher)], env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )

    write(bootstrap, "print('this is not json')\n")
    done = launch(control)
    check(done.returncode != 0, "B3-T1.unreadable-exit", done.stdout)
    check("preflight receipt unreadable" in done.stdout
          and "refusing Operator import" in done.stdout,
          "B3-T1.unreadable-typed", done.stdout)
    check("OPERATOR-REACHED" not in done.stdout, "B3-T1.unreadable-no-import", done.stdout)

    write(bootstrap, "print('[1, 2, 3]')\n")
    done = launch(control)
    check(done.returncode != 0, "B3-T1.nonobject-exit", done.stdout)
    check("preflight receipt is not an object" in done.stdout and "list" in done.stdout,
          "B3-T1.nonobject-typed", done.stdout)
    check("OPERATOR-REACHED" not in done.stdout, "B3-T1.nonobject-no-import", done.stdout)

    write(bootstrap, "import sys\nprint('fixture rejection detail')\nsys.exit(3)\n")
    done = launch(control)
    check(done.returncode != 0, "B3-T1.rejected-exit", done.stdout)
    check("fixture rejection detail" in done.stdout, "B3-T1.rejected-relayed", done.stdout)
    check("[FAIL] workspace bootstrap rejected the local Devkit" in done.stdout,
          "B3-T1.rejected-typed", done.stdout)

    write(bootstrap, "import json\nprint(json.dumps({'bootstrap_notes': "
                     "['fixture identity note']}))\n")
    done = launch(control)
    check(done.returncode == 0, "B3-T1.notes-exit", done.stdout)
    check("[devkit-identity] devkit identity note: fixture identity note" in done.stdout,
          "B3-T1.notes-surfaced", done.stdout)
    check("OPERATOR-REACHED" in done.stdout, "B3-T1.happy-path", done.stdout)

    done = launch(temp / "t1-missing-control")
    check(done.returncode != 0, "B3-T1.missing-exit", done.stdout)
    check("[FAIL] workspace bootstrap not found at" in done.stdout,
          "B3-T1.missing-typed", done.stdout)


def source_contract_cases() -> None:
    launcher = (TOOLS / "qiven.py.in").read_text(encoding="utf-8")
    check("refusing Operator import" in launcher, "B3-T2.strict-present")
    check("notes not surfaced" not in launcher, "B3-T2.warn-and-continue-gone")
    check("P0 repair R6b" in launcher, "B3-T2.r6b-law-named")


def rendered_suite_case(temp: Path) -> None:
    repo = make_repo(temp, "b3-rendered")
    render_tools(repo)
    commit(repo, "baseline")
    done = run([sys.executable, str(repo / "tools" / "b3_carrier_test.py")], cwd=repo)
    check("[ OK ] b3-carrier:" in done.stdout, "B3-T3.managed-suite-passes", done.stdout[-600:])
    check("[SKIP] B3-L" not in done.stdout, "B3-T3.launcher-cases-ran",
          "the rendered launcher is strict; its cases must not skip")


def manifest_cases() -> None:
    manifest = (ROOT / "templates" / "cpp-library" / "managed-files.cmake").read_text(
        encoding="utf-8")
    version = re.search(r'QIVEN_TEMPLATE_VERSION "([0-9]+\.[0-9]+\.[0-9]+)"', manifest)
    check(version is not None, "B3-T4.version-format")
    check("tools/b3_carrier_test.py" in manifest, "B3-T4.suite-managed")
    policy_text = (MANAGED / ".qiven" / "operator.json.in").read_text(encoding="utf-8")
    policy = json.loads(policy_text.replace("@REPOSITORY_NAME@", "b3-fixture"))
    task = policy.get("tasks", {}).get("b3-carrier-tests")
    check(isinstance(task, dict) and "tools/b3_carrier_test.py" in task.get("argv", []),
          "B3-T4.task-declared")
    check("b3-carrier-tests" in policy.get("gates", {}).get("local", []),
          "B3-T4.gate-wired")


def load_format_sources(tool_path: Path, behaviors: dict[str, tuple[int, str]]
                        ) -> tuple[ModuleType, Callable[[], None]]:
    """Load a format_sources.py copy with the toolchain module and the
    clang-format process boundary stubbed; git stays real."""
    fake_clang = "fixture-clang-format"
    stub = ModuleType("toolchain")
    stub.resolve = lambda: {"clang_format": fake_clang, "cmake": "cmake-fixture"}  # type: ignore[attr-defined]
    saved_toolchain = sys.modules.get("toolchain")
    real_subprocess = subprocess

    class _Result:
        pass

    class _SubprocessProxy:
        def run(self, argv: list[str], *args, **kwargs):
            if argv and argv[0] == fake_clang:
                result = _Result()
                result.returncode, result.stdout = behaviors.get(
                    Path(argv[-1]).name, (0, ""))
                return result
            return real_subprocess.run(argv, *args, **kwargs)

        def __getattr__(self, name: str):
            return getattr(real_subprocess, name)

    sys.modules["toolchain"] = stub
    spec = importlib.util.spec_from_file_location("format_sources_b3_devkit", tool_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {tool_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.subprocess = _SubprocessProxy()  # type: ignore[attr-defined]

    def restore() -> None:
        if saved_toolchain is None:
            sys.modules.pop("toolchain", None)
        else:
            sys.modules["toolchain"] = saved_toolchain

    return module, restore


def call_main(module: ModuleType, argv: list[str]) -> tuple[int, str]:
    saved_argv = sys.argv
    sys.argv = ["format_sources.py", *argv]
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            code = module.main()
    finally:
        sys.argv = saved_argv
    return int(code), buffer.getvalue()


def live_tool_cases(temp: Path) -> None:
    repo = make_repo(temp, "b3-live-counts")
    shutil.copyfile(ROOT / "tools" / "format_sources.py",
                    repo / "tools" / "format_sources.py")
    write(repo / "clean.cpp", "int main() { return 0; }\n")
    write(repo / "unformatted_a.cpp", "int  main( ){return 0;}\n")
    write(repo / "unformatted_b.cpp", "int  main( ){return 1;}\n")
    commit(repo, "baseline")
    behaviors = {"unformatted_a.cpp": (1, CANNED_WARNING + "\n"),
                 "unformatted_b.cpp": (1, CANNED_WARNING + "\n")}
    module, restore = load_format_sources(repo / "tools" / "format_sources.py", behaviors)
    try:
        code, out = call_main(module, ["--check"])
    finally:
        restore()
    check(code == 1, "B3-T5.check-exit", out)
    selector = next((ln for ln in out.splitlines() if "failures=" in ln), "")
    check("failures=2 of 3" in selector and "violate .clang-format" in selector
          and "FIX: python tools/format_sources.py --fix" in selector,
          "B3-T5.check-selector", selector)

    module, restore = load_format_sources(repo / "tools" / "format_sources.py", {})
    try:
        code, out = call_main(module, ["--check"])
    finally:
        restore()
    check(code == 0, "B3-T5.pass-exit", out)
    check("[ OK ] format --check: 3 tracked C/C++ sources" in out.splitlines(),
          "B3-T5.pass-byte-stable", out)
    check(not any(("FIX:" in ln or "DIAGNOSE:" in ln) for ln in out.splitlines()),
          "B3-T5.pass-no-teaching", out)

    huge = "".join(f"{CANNED_WARNING} line {n:04d}\n" for n in range(200))
    module, restore = load_format_sources(repo / "tools" / "format_sources.py",
                                          {"unformatted_a.cpp": (1, huge)})
    try:
        code, out = call_main(module, ["--fix"])
    finally:
        restore()
    check(code == 1, "B3-T5.fixfail-exit", out)
    selector = next((ln for ln in out.splitlines() if "failures=" in ln), "")
    check("DIAGNOSE:" in selector and "-i --style=file unformatted_a.cpp" in selector,
          "B3-T5.fixfail-diagnose", selector)
    check("[evidence: first " in out and " captured bytes]" in out,
          "B3-T5.bounded-evidence", out[:400])


def main() -> int:
    global CHECKS
    with tempfile.TemporaryDirectory(prefix="qiven-b3-template-") as temp_name:
        temp = Path(temp_name)
        template_launcher_cases(temp)
        source_contract_cases()
        rendered_suite_case(temp)
        manifest_cases()
        live_tool_cases(temp)
    print(f"[ OK ] b3-template: {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
