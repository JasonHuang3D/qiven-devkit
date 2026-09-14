from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CMAKE = os.environ.get("QIVEN_CMAKE")
if not CMAKE:
    raise SystemExit("QIVEN_CMAKE is required")


def run(argv: list[str], *, cwd: Path | None = None, expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
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

        config_path = repo / ".qiven" / "operator.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        marker_a = repo / "a.marker"
        marker_c = repo / "c.marker"
        config["tasks"].update(
            {
                "fixture-pass": {
                    "argv": [sys.executable, "-c", f"from pathlib import Path; Path(r'{marker_a}').write_text('ok')"]
                },
                "fixture-fail": {"argv": [sys.executable, "-c", "raise SystemExit(7)"]},
                "fixture-must-not-run": {
                    "argv": [sys.executable, "-c", f"from pathlib import Path; Path(r'{marker_c}').write_text('bad')"]
                },
            }
        )
        config["gates"]["fixture-fail-fast"] = [
            "fixture-pass",
            "fixture-fail",
            "fixture-must-not-run",
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
        # Add a tiny gate after exercising parser/error behavior.
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

    print("Qiven Operator tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
