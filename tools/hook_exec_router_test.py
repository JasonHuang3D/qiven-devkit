#!/usr/bin/env python3
"""Self-test for hook_exec_router.py (gate task `router-tests`).

Case-table driven: every (command, expected verdict) pair asserts
classify(); the table documents the 2026-09-23 rigor review (format
hang, raw curl slip-through, bypass tightening) and pins future edits.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_exec_router  # noqa: E402

CASES: list[tuple[str, str]] = [
    # --- allow: short, read-only, everyday session work -----------------
    ("git status --short", "allow"),
    ("git rev-parse HEAD", "allow"),
    ("git log --oneline -5", "allow"),
    ("git diff --stat", "allow"),
    ("ls -la build/", "allow"),
    ("python tools/third_party_verify.py", "allow"),
    ("echo hello", "allow"),
    ("grep -rn foo src/", "allow"),
    # --- allow: operator-mediated ----------------------------------------
    ("tools\\qiven.cmd exec start --timeout 600 -- cmake --build build", "allow"),
    ("tools/qiven.cmd run test-debug", "allow"),
    ("python tools/qiven.py gate", "allow"),
    ("qiven exec status 123", "allow"),
    ("call tools\\qiven.cmd gate", "allow"),
    ("git pull --quiet && tools/qiven.cmd gate", "allow"),
    # --- deny: long class, builds ----------------------------------------
    ("cmake --build build/vs2022-x64 --config Debug", "long"),
    ("cmake -S . -B build", "long"),
    ("cmake --preset vs2022-x64", "long"),
    ("ctest --test-dir build -C Debug", "long"),
    ("MSBuild.exe project.vcxproj /p:Configuration=Debug", "long"),
    ("devenv solution.sln /build Debug", "long"),
    ("dotnet build", "long"),
    ("pytest", "long"),
    ("python tools/test_all.py --group repo", "long"),
    # --- deny: long class, the 2026-09-23 additions -----------------------
    ("python tools/format_sources.py --fix", "long"),          # the sqlite3.c hang
    ("tools\\format.cmd", "long"),
    ("call tools\\format-check.cmd", "long"),
    ("clang-format -i src/*.cpp", "long"),
    ("python D:/JasonWork/qiven-devkit/tools/deploy_bundle.py --repo .", "long"),
    ("cmd /c call tools\\deploy.cmd", "long"),
    ("curl -sS -o archive.zip https://example.invalid/x.zip", "long"),  # the raw-curl slip
    ("wget https://example.invalid/x.tar.gz", "long"),
    ("Invoke-WebRequest -Uri x -OutFile y", "long"),
    ("pip install pyyaml", "long"),
    ("python -m pip install requests", "long"),
    ("npm install", "long"),
    ("git clone https://github.com/x/y.git", "long"),
    ("git submodule update --init --recursive", "long"),
    ("gh run watch 12345", "long"),
    # --- deny: interactive class ------------------------------------------
    ("vim notes.txt", "interactive"),
    ("git rebase -i HEAD~3", "interactive"),
    ("git checkout -p src/main.cpp", "interactive"),
    ("git add -p .", "interactive"),
    ("cmake --open build", "interactive"),
    # --- deny: wrapped forms (text is scanned whole) ----------------------
    ("bash -c 'cmake --build build'", "long"),
    ("echo x && ctest", "long"),
    # --- bypass tightening: qiven token NOT at a command position ---------
    ("echo tools/qiven && cmake --build build", "long"),
    ("cat qiven.cmd && python tools/test_all.py", "long"),
]


def main() -> int:
    failures = 0
    for command, expected in CASES:
        actual = hook_exec_router.classify(command)
        if actual != expected:
            failures += 1
            print(f"[FAIL] {command!r}: expected {expected}, got {actual}")
    if failures:
        print(f"[FAIL] router-tests: {failures} case(s)")
        return 1
    print(f"[ OK ] router-tests: {len(CASES)} classification cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
