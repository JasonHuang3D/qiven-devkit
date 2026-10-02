from __future__ import annotations

"""Self-test for the WR-8 forbidden resolver-pattern gate (P1-P6).

Fixture trees carry the forbidden shapes; the gate must flag each and
pass a clean tree. Exit 0 pass / 1 fail."""

import subprocess
import sys
import tempfile
from pathlib import Path

GATE = Path(__file__).resolve().parent / "check_resolver_patterns.py"


def run_gate(repo: Path) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(GATE), "--repo", str(repo)],
        capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout + result.stderr


def build_fixture(tmp: Path, name: str, files: dict[str, str]) -> Path:
    repo = tmp / name
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return repo


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)

        # P1: CMake sibling discovery in functional (non-comment) lines
        repo = build_fixture(tmp, "r1", {
            "CMakeLists.txt": "# never resolves siblings (law text)\n"
                              "set(QIVEN_DEVKIT_ROOT \"${CMAKE_SOURCE_DIR}/../qiven-devkit\")\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R1" in out, f"P1: {code} {out}"

        # P2: a consumer-local pin in configuration
        repo = build_fixture(tmp, "r2", {
            ".qiven/config.json": "{\"devkit_pin\": {\"sha\": \"deadbeef\"}}\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R2" in out, f"P2: {code} {out}"

        # P3: devkit sibling import fallback in Python - both the literal
        # path form and the Path-composed form WITHOUT the identity marker
        repo = build_fixture(tmp, "r3", {
            "tools/launch.py": "import sys\nsys.path.insert(0, '../qiven-devkit')\n",
            "tools/launch2.py": "import importlib\n"
                                "CHECKOUT = ROOT.parent / 'qiven-devkit'\n"
                                "main = importlib.import_module('qiven_operator').main\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and out.count("R3") == 2, f"P3: {code} {out}"

        # P4: toolchain path without the lock identity check
        repo = build_fixture(tmp, "r4", {
            "tools/toolchain.py": "ROOT = '../qiven-toolchain-win'\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R4" in out, f"P4: {code} {out}"

        # P5: a vendored operator copy outside the documented instances
        repo = build_fixture(tmp, "r5", {
            "tools/qiven_operator.py": "def main():\n    pass\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R5" in out, f"P5: {code} {out}"

        # P6: the documented exceptions and the lock-bound shape pass (the
        # operator instance exception is keyed on the repository name);
        # the guarded launcher (identity marker present) and bracket-
        # comment law text also pass
        repo = build_fixture(tmp, "qiven-foundation", {
            "tools/qiven_operator.py": "LOCK = 'workspace.lock.json'\n"
                                       "TOOLCHAIN = 'qiven-toolchain-win'\n",
            "CMakeLists.txt": "#[[\nLaw text: the retired ../qiven-devkit sibling discovery.\n]]\n"
                              "# siblings or checks a consumer-local pin (comment-only)\n",
            "docs/history.md": "the devkit_pin era (prose record)\n",
            "tools/launcher.py": "import importlib\n"
                                 "CHECKOUT = ROOT.parent / 'qiven-devkit'\n"
                                 "_bootstrap_identity(CHECKOUT, node)  # the guard\n"
                                 "main = importlib.import_module('qiven_operator').main\n",
            "tools/citation.py": "LAW = 'qiven-devkit docs/engineering/law.md (docstring)'\n",
        })
        code, out = run_gate(repo)
        assert code == 0, f"P6: {code} {out}"

        # P7: a batch launcher carrying the retired env-var/sibling
        # fallback fails typed (the 2026-09-28 v44 finding class);
        # rem/:: comment law text does NOT trip it
        repo = build_fixture(tmp, "r7", {
            "tools/deploy.cmd": "@echo off\n"
                                "rem resolves via QIVEN_DEVKIT_ROOT (law text only)\n"
                                ":: ../qiven-devkit sibling fallback (comment)\n"
                                "if \"%QIVEN_DEVKIT_ROOT%\"==\"\" (\n"
                                "  set \"QIVEN_DEVKIT_ROOT=%~dp0..\\..\\qiven-devkit\"\n"
                                ")\n"
                                "python \"%QIVEN_DEVKIT_ROOT%\\tools\\deploy_bundle.py\"\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and out.count("R1") >= 2, f"P7: {code} {out}"

        # P8: a WR-6-shaped launcher passes - the bootstrap identity-check
        # wrapper named like the documented thin launcher, a comment-only
        # mention, and the python guard form with the identity marker
        repo = build_fixture(tmp, "r8", {
            "qiven.cmd": "@echo off\n"
                         "python \"%~dp0tools\\launch.py\" %*\n",
            "tools/deploy.cmd": "@echo off\n"
                                "rem WR-6: no env var, no sibling fallback -\n"
                                "rem the lock's qiven-devkit node is the only source\n"
                                "python \"%~dp0deploy.py\" %*\n",
            "tools/deploy.py": "CHECKOUT = ROOT.parent / 'qiven-devkit'\n"
                               "_bootstrap_identity()  # WR-6 guard\n",
        })
        code, out = run_gate(repo)
        assert code == 0, f"P8: {code} {out}"

        # P9: R6 - process-global handler-install vocabulary in the two
        # I0-census-declared gap trees fails typed (vendored sqlite3 and
        # linked context-draft; the "zero unknown sites" claim is
        # mechanically proven, not declared)
        repo = build_fixture(tmp / "p9a", "qiven-third-party-win", {
            "packages/sqlite3/src/evil_patch.c": "#include <signal.h>\n"
                                                 "signal(SIGINT, my_handler);\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R6" in out, f"P9a: {code} {out}"
        repo = build_fixture(tmp / "p9b", "qiven-context-draft", {
            "src/legacy.cpp": "_set_invalid_parameter_handler(my_handler);\n",
        })
        code, out = run_gate(repo)
        assert code == 1 and "R6" in out, f"P9b: {code} {out}"

        # P10: R6 scoping - clean gap trees pass, and the same vocabulary
        # in a NON-R6 repository (foundation's legitimate installer class)
        # does not fire (R6 covers only the census-declared gap trees)
        repo = build_fixture(tmp / "p10a", "qiven-third-party-win", {
            "packages/sqlite3/src/sqlite3.c": "int sqlite3_open(const char *f, void **db)\n"
                                              "{ return 0; }\n",
        })
        code, out = run_gate(repo)
        assert code == 0, f"P10a: {code} {out}"
        repo = build_fixture(tmp / "p10b", "qiven-foundation", {
            "src/crt_failure.cpp": "_set_invalid_parameter_handler(qiven_invalid_parameter);\n"
                                   "SetConsoleCtrlHandler(console_handler, TRUE);\n",
        })
        code, out = run_gate(repo)
        assert code == 0, f"P10b: {code} {out}"

    print("[ OK ] resolver-patterns self-test (P1-P10)")
    return 0


if __name__ == "__main__":
    import selftest_carrier
    raise SystemExit(selftest_carrier.run(__file__, main))
