#!/usr/bin/env python3
"""Self-test for hook_exec_router.py (gate task `router-tests`).

Case-table driven: static classification cases + injected-runner probe
cases for the git-network measured judgment + message-prefix checks.
The table documents the 2026-09-23 v3 review (gate-exec routing,
measured git network, [qiven-hook] provenance tags).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_exec_router as router  # noqa: E402


CASES: list[tuple[str, str]] = [
    # --- allow: short, read-only, everyday session work -----------------
    ("git status --short", "allow"),
    ("git rev-parse HEAD", "allow"),
    ("git log --oneline -5", "allow"),
    ("git diff --stat", "allow"),
    ("ls -la build/", "allow"),
    ("python tools/third_party_verify.py", "allow"),
    ("echo hello", "allow"),
    # --- deny: heredoc authoring (absolute prohibition, 2026-09-23) -----
    ("cat << EOF", "heredoc"),
    ("cat <<EOF", "heredoc"),
    ("cat << 'EOF'", "heredoc"),
    ("cat <<- \"EOF\"", "heredoc"),
    ("cat << EOF > file.txt", "heredoc"),
    ("python - << 'PY'", "heredoc"),
    ("cat << EOF && git status", "heredoc"),
    # exec never launders a heredoc payload:
    ("tools/qiven.cmd exec start --timeout 60 -- python - << 'PY'", "heredoc"),
    # quoted PROSE mentioning heredoc syntax is not heredoc authoring:
    ('git commit -m "use << EOF style in docs"', "allow"),
    ("echo 'cat << EOF' explained", "allow"),
    # residual, same class as gate-class indirection: heredoc inside a
    # QUOTED bash -c payload is invisible to text matching — the contract
    # remains the backstop (docstring note):
    ("bash -c 'cat << EOF'", "allow"),
    # numeric bit-shift operands do not match (letter operands may —
    # documented accepted false positive; rewrite such expressions):
    ("echo $((1 << 4))", "allow"),
    # --- allow: operator exec/info (fast control plane) -------------------
    ("tools\\qiven.cmd exec start --timeout 600 -- cmake --build build", "allow"),
    ("python tools/qiven.py info", "allow"),
    ("qiven exec status 123", "allow"),
    ("call tools\\qiven.cmd exec status abc", "allow"),
    # --- deny: gate-class (minutes-class; must run detached) --------------
    ("tools\\qiven.cmd gate", "gate-class"),
    ("tools/qiven.cmd gate --expect-head abc123", "gate-class"),
    ("call tools\\qiven.cmd gate", "gate-class"),
    ("tools/qiven.cmd run test-debug", "gate-class"),
    ("qiven ci start full", "gate-class"),
    # gate INSIDE exec is allowed (exec at command position; the gate
    # regex finds no command position for gate):
    ("tools/qiven.cmd exec start --timeout 900 -- cmd /c call tools/qiven.cmd gate", "allow"),
    # --- deny: long class, builds ----------------------------------------
    ("cmake --build build/vs2022-x64 --config Debug", "long"),
    ("cmake -S . -B build", "long"),
    ("ctest --test-dir build -C Debug", "long"),
    ("MSBuild.exe project.vcxproj /p:Configuration=Debug", "long"),
    ("dotnet build", "long"),
    ("python tools/test_all.py --group repo", "long"),
    # --- deny: long class, the 2026-09-23 additions -----------------------
    ("python tools/format_sources.py --fix", "long"),          # the sqlite3.c hang
    ("clang-format -i src/*.cpp", "long"),
    ("pip install pyyaml", "long"),
    ("git clone https://github.com/x/y.git", "long"),          # unconditional: no local repo to probe
    ("git submodule update --init --recursive", "long"),
    ("gh run watch 12345", "long"),
    # --- deny: interactive class ------------------------------------------
    ("vim notes.txt", "interactive"),
    ("git checkout" + " -p src/main.cpp", "interactive"),
    ("git add" + " -p .", "interactive"),
    ("cmake --open build", "interactive"),
    # --- git-network: static classify only (probe decides) ----------------
    ("git push origin main", "git-network"),
    ("git push", "git-network"),
    ("git fetch origin", "git-network"),
    ("git pull --quiet", "git-network"),
    ("cd /d/JasonWork/qiven-runtime && git push", "git-network"),
    # --- segmentation: exec in one segment never launders another ---------
    ("git pull --quiet && tools/qiven.cmd exec status abc", "git-network"),
    ("tools/qiven.cmd exec start -- x && ctest --test-dir b", "long"),
    ("echo a ; vim b.txt", "interactive"),
    # --- chained exec invocations (OBL-A7B8C9: segments after && arrive ---
    # --- with leading whitespace; the anchors must tolerate it) -----------
    ("git status --short && tools\\qiven.cmd exec start --timeout 600 -- cmake --build build", "allow"),
    ("cd /d/x && tools/qiven.cmd exec start --timeout 60 -- python t.py", "allow"),
    ("tools/qiven.cmd info && tools/qiven.cmd exec status abc", "allow"),
    ("git status && tools\\qiven.cmd gate", "gate-class"),
    ("git status &&    qiven run test-debug", "gate-class"),
    # --- tree sweeps are long-class (2026-09-23 ghost find.exe incident) --
    ("find /d/JasonWork -name '*.vcxproj'", "long"),
    ("find /d/JasonWork/qiven-runtime -type f -name '*.cpp'", "long"),
    ("find -L /d/JasonWork -name build", "long"),
    ("find D:\\JasonWork -name build", "long"),
    ("grep -r pattern .", "long"),
    ("grep --recursive foo src/", "long"),
    ("cmd /c dir /s /b", "long"),
    ("dir build /s", "long"),
    # the Windows text-FILTER find (slash-flag + quoted needle) stays raw:
    ("find /i \"marker\" out.log", "allow"),
    ("find \"needle\" file.txt", "allow"),
    # --- quote-awareness: quoted prose is not a command segment -----------
    ('git commit -m "text; qiven gate tools\\qiven.cmd gate --expect-head x" && git status', "allow"),
    ('git commit -m "mentions ctest inside quotes" && git log -1', "allow"),
    ("echo 'vim in single quotes' && git status", "allow"),
    # --- bypass tightening: qiven token NOT at a command position ---------
    ("echo tools/qiven && cmake --build build", "long"),
    ("cat qiven.cmd && python tools/test_all.py", "long"),
]


def fake_runner(results):
    """results: list of (output, completed, ok) consumed per call."""
    calls: list[list[str]] = []
    state = {"index": 0}

    def runner(args, cwd):
        calls.append(args)
        item = results[state["index"]] if state["index"] < len(results) else ("", True, False)
        state["index"] += 1
        return item

    runner.calls = calls
    return runner


def probe_cases() -> list[tuple[str, str, str, list[tuple[str, bool, bool]]]]:
    """(name, command, expected_decision, runner_results)"""
    return [
        ("push small: 3 ahead, dry-run clean", "git push origin main", "allow",
         [("origin/main\n", True, True), ("3\n", True, True), ("Everything up-to-date\n", True, True)]),
        ("push large: 137 ahead", "git push origin main", "deny",
         [("origin/main\n", True, True), ("137\n", True, True)]),
        ("push: no upstream, falls back to origin/main (new-branch push)", "git push -u origin feature-x", "allow",
         [("fatal: no upstream\n", True, False), ("origin/main\n", True, True), ("3\n", True, True)]),
        ("push: no upstream, large vs origin/main", "git push -u origin feature-x", "deny",
         [("fatal: no upstream\n", True, False), ("origin/main\n", True, True), ("137\n", True, True)]),
        ("push: no upstream and no remote base", "git push -u origin feature-x", "deny",
         [("fatal: no upstream\n", True, False), ("fatal: bad rev\n", True, False),
          ("fatal: bad rev\n", True, False), ("fatal: bad rev\n", True, False)]),
        ("push: dry-run exceeds budget", "git push origin main", "deny",
         [("origin/main\n", True, True), ("2\n", True, True), ("", False, False)]),
        ("fetch: up to date", "git fetch origin", "allow", [("", True, True)]),
        ("fetch: refs changing", "git fetch origin", "deny",
         [("  abc..def  main -> origin/main\n  111..222  next -> origin/next\n", True, True)]),
        ("fetch: probe timeout", "git pull --quiet", "deny", [("", False, False)]),
    ]


def main() -> int:
    failures = 0
    for command, expected in CASES:
        actual = router.classify(command)
        if actual != expected:
            failures += 1
            print(f"[FAIL] {command!r}: expected {expected}, got {actual}")

    for name, command, expected_decision, results in probe_cases():
        decision, evidence = router.probe_git_network(command, runner=fake_runner(results))
        if decision != expected_decision:
            failures += 1
            print(f"[FAIL] probe {name}: expected {expected_decision}, got {decision} ({evidence})")

    # message provenance: every denial message carries the hook tag
    for command in ("cmake --build build", "tools/qiven.cmd gate", "vim x", "git push origin main",
                    "cat << EOF"):
        code, message = router.verdict(command, probe_runner=fake_runner([("origin/main\n", True, True), ("300\n", True, True)]))
        if code != 2 or "[qiven-hook]" not in message:
            failures += 1
            print(f"[FAIL] provenance tag missing in verdict for {command!r}")

    # the heredoc denial names the native-tool law (actionable denial)
    _, heredoc_message = router.verdict("cat << EOF")
    if "Read/Write/Edit" not in heredoc_message or "heredoc" not in heredoc_message:
        failures += 1
        print("[FAIL] heredoc denial must name the native read/write/edit law")

    # gate-inside-exec stays allowed end-to-end
    code, _ = router.verdict("tools/qiven.cmd exec start --timeout 900 -- cmd /c call tools/qiven.cmd gate")
    if code != 0:
        failures += 1
        print("[FAIL] gate inside exec must be allowed")

    if failures:
        print(f"[FAIL] router-tests: {failures} case(s)")
        return 1
    print(f"[ OK ] router-tests: {len(CASES)} classification + {len(probe_cases())} probe + provenance cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
