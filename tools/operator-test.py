from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
CMAKE = os.environ.get("QIVEN_CMAKE")
if not CMAKE:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from toolchain import resolve
    CMAKE = resolve()["cmake"]


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    expect: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def generate(repo: Path) -> None:
    run(
        [
            CMAKE,
            f"-DDEVKIT_ROOT={ROOT}",
            f"-DDESTINATION={repo}",
            "-DREPOSITORY_NAME=operator-fixture",
            "-DCMAKE_PROJECT_NAME=operator-fixture",
            "-DCMAKE_TARGET_NAME=operator-fixture",
            "-DCMAKE_ALIAS=qiven::operator_fixture",
            "-DCPP_NAMESPACE=qiven::operator_fixture",
            "-DTEST_OPTION_NAME=QIVEN_OPERATOR_FIXTURE_BUILD_TESTS",
            "-DVS_SOLUTION_NAME=operator-fixture",
            "-P",
            str(ROOT / "cmake" / "QivenRepoNew.cmake"),
        ]
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args])


def load_operator(repo: Path):
    module_path = repo / "tools" / "qiven_operator.py"
    spec = importlib.util.spec_from_file_location("qiven_operator_fixture", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load generated qiven_operator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parallel_code(me: Path, other: Path) -> str:
    return (
        "from pathlib import Path\n"
        "import time\n"
        f"me = Path({str(me)!r})\n"
        f"other = Path({str(other)!r})\n"
        "me.write_text('ready', encoding='utf-8')\n"
        "deadline = time.monotonic() + 2.0\n"
        "while time.monotonic() < deadline and not other.exists():\n"
        "    time.sleep(0.01)\n"
        "raise SystemExit(0 if other.exists() else 9)\n"
    )


def assert_no_repo_bytecode(repo: Path) -> None:
    artifacts = sorted(
        str(path.relative_to(repo))
        for path in repo.rglob("*")
        if path.is_file() and (path.suffix == ".pyc" or "__pycache__" in path.parts)
    )
    if artifacts:
        raise AssertionError(f"Operator execution wrote Python bytecode into repository: {artifacts}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qiven-operator-test-") as temp:
        repo = Path(temp) / "repo"
        generate(repo)
        for relative in (
            ".qiven/operator.json",
            "tools/qiven.cmd",
            "tools/qiven.py",
            "tools/qiven_operator.py",
        ):
            if not (repo / relative).is_file():
                raise AssertionError(f"missing generated Operator file: {relative}")

        git(repo, "init", "-b", "main")
        git(repo, "add", "--all")
        run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=QivenFixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "baseline",
            ]
        )
        head = git(repo, "rev-parse", "HEAD").stdout.strip()

        info = run([sys.executable, "tools/qiven.py", "--json", "info"], cwd=repo)
        payload = json.loads(info.stdout)
        assert payload["status"] == "ok"
        assert payload["repository"] == "operator-fixture"
        assert payload["head"] == head
        assert "[ RUN]" not in info.stdout and "[ OK ]" not in info.stdout
        assert_no_repo_bytecode(repo)

        config_path = repo / ".qiven" / "operator.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        marker_a = repo / "a.marker"
        marker_c = repo / "c.marker"
        parallel_a = repo / "parallel-a.marker"
        parallel_b = repo / "parallel-b.marker"
        child_only = "QIVEN_OPERATOR_CHILD_ONLY_7F31B2"

        if os.name == "nt":
            leak_script = repo / "tools" / "fixture-env-leak.cmd"
            leak_script.write_text(
                "@echo off\r\n"
                f"set \"{child_only}=leaked\"\r\n"
                "cd /d \"%TEMP%\"\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )
            isolation_set_argv = ["tools/fixture-env-leak.cmd"]
        else:
            isolation_set_argv = [
                sys.executable,
                "-c",
                f"import os, tempfile; os.environ[{child_only!r}]='leaked'; os.chdir(tempfile.gettempdir())",
            ]

        isolation_check = (
            "import os\n"
            "from pathlib import Path\n"
            f"expected = Path({str(repo)!r}).resolve()\n"
            f"leaked = os.environ.get({child_only!r})\n"
            "raise SystemExit(11 if leaked else (12 if Path.cwd().resolve() != expected else 0))\n"
        )

        config["tasks"].update(
            {
                "fixture-pass": {
                    "argv": [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path(r'{marker_a}').write_text('ok')",
                    ]
                },
                "fixture-fail": {"argv": [sys.executable, "-c", "raise SystemExit(7)"]},
                "fixture-must-not-run": {
                    "argv": [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path(r'{marker_c}').write_text('bad')",
                    ]
                },
                "fixture-isolation-set": {"argv": isolation_set_argv},
                "fixture-isolation-check": {"argv": [sys.executable, "-c", isolation_check]},
                "fixture-slow": {"argv": [sys.executable, "-c", "import time; time.sleep(0.18)"]},
                "fixture-parallel-a": {"argv": [sys.executable, "-c", parallel_code(parallel_a, parallel_b)]},
                "fixture-parallel-b": {"argv": [sys.executable, "-c", parallel_code(parallel_b, parallel_a)]},
            }
        )
        config["gates"]["fixture-fail-fast"] = [
            "fixture-pass",
            "fixture-fail",
            "fixture-must-not-run",
        ]
        config["gates"]["fixture-isolation"] = [
            "fixture-isolation-set",
            "fixture-isolation-check",
        ]
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        failed = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-fail-fast"],
            cwd=repo,
            expect=1,
        )
        failed_payload = json.loads(failed.stdout)
        assert failed_payload["status"] == "fail"
        assert marker_a.is_file()
        assert not marker_c.exists(), "fail-fast gate executed a later stage"
        assert "[ RUN]" not in failed.stdout and "[FAIL]" not in failed.stdout

        isolation = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-isolation"],
            cwd=repo,
        )
        isolation_payload = json.loads(isolation.stdout)
        assert isolation_payload["status"] == "pass", isolation.stdout
        assert os.environ.get(child_only) is None, "child task environment leaked into test process"

        parallel = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "run",
                "--parallel",
                "fixture-parallel-a",
                "fixture-parallel-b",
            ],
            cwd=repo,
        )
        parallel_payload = json.loads(parallel.stdout)
        assert parallel_payload["status"] == "pass", parallel.stdout
        assert {item["name"] for item in parallel_payload["results"]} == {
            "fixture-parallel-a",
            "fixture-parallel-b",
        }
        assert_no_repo_bytecode(repo)

        operator = load_operator(repo)
        operator.HEARTBEAT_SECONDS = 0.05
        operator.POLL_SECONDS = 0.01
        human_output = io.StringIO()
        with contextlib.redirect_stdout(human_output):
            human_rc = operator.main(["--no-color", "run", "fixture-slow"])
        rendered = human_output.getvalue()
        assert human_rc == 0, rendered
        assert "[ RUN] fixture-slow" in rendered
        assert "[WAIT] fixture-slow:" in rendered
        assert "[ OK ] fixture-slow" in rendered
        assert "[ OK ] run: PASS" in rendered
        assert "\x1b[" not in rendered, "--no-color emitted ANSI escapes"

        wrong_head = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "gate",
                "--name",
                "fixture-head",
                "--expect-head",
                "0" * 40,
            ],
            cwd=repo,
            expect=2,
        )
        assert json.loads(wrong_head.stdout)["status"] == "error"

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["gates"]["fixture-head"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        exact_fail = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "gate",
                "--name",
                "fixture-head",
                "--expect-head",
                "0" * 40,
            ],
            cwd=repo,
            expect=1,
        )
        assert json.loads(exact_fail.stdout)["status"] == "fail"

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["gates"]["fixture-clean"] = ["clean-tree"]
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        dirty = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-clean"],
            cwd=repo,
            expect=1,
        )
        dirty_payload = json.loads(dirty.stdout)
        assert dirty_payload["status"] == "fail"
        assert "working tree is not clean" in dirty_payload["results"][0]["detail"]

        ci_config = {
            "ci": {
                "full": {
                    "workflow": "ci.yml",
                    "inputs": {"jobs": "full"},
                }
            }
        }
        ci_console = operator.Console(json_mode=True, no_color=True)
        local_head = "a" * 40
        remote_mismatch = "b" * 40
        dispatch_calls: list[list[str]] = []

        operator.shutil.which = lambda name: "gh" if name == "gh" else None
        operator._current_branch = lambda: "fixture-branch"
        operator._head = lambda: local_head
        operator._remote_repo = lambda: "example/operator-fixture"
        operator._remote_branch_head = lambda branch: remote_mismatch

        def fake_run_capture(argv: list[str], *, cwd: Path = operator.ROOT) -> subprocess.CompletedProcess[str]:
            dispatch_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "")

        operator._run_capture = fake_run_capture
        try:
            operator._ci_start(ci_config, "full", ci_console)
        except operator.OperatorError as exc:
            assert "match local HEAD" in str(exc)
        else:
            raise AssertionError("CI dispatch accepted a stale remote branch")
        assert not dispatch_calls, "CI dispatch ran before exact remote-head verification"

        operator._remote_branch_head = lambda branch: local_head
        ci_payload = operator._ci_start(ci_config, "full", ci_console)
        assert len(dispatch_calls) == 1
        assert ci_payload["status"] == "dispatched"
        assert ci_payload["head"] == local_head
        assert ci_payload["remote_head"] == local_head
        assert ci_payload["branch"] == "fixture-branch"

    print("Qiven Operator tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
