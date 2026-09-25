#!/usr/bin/env python3
"""Self-test for hook_exec_router.py (gate task `router-tests`).

Case-table driven: static classification cases + injected-runner probe
cases for the git-network measured judgment + message-prefix checks +
v4 end-to-end background/guard semantics (ADR-0051: deny -> re-call
with run_in_background; build/gate classes require the MSBuild
node-reuse guard; sweeps stay under exec lease custody).
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
    # --- deny: gate-class (minutes-class; may build -> background+guard) -
    ("tools\\qiven.cmd gate", "gate-class"),
    ("tools/qiven.cmd gate --expect-head abc123", "gate-class"),
    ("call tools\\qiven.cmd gate", "gate-class"),
    ("tools/qiven.cmd run test-debug", "gate-class"),
    ("qiven ci start full", "gate-class"),
    # ci watch (OBL-F1A2B3 observation runner) is the same class: raw
    # foreground calls are denied with the background re-call + guard
    # teaching; the watch is inherently terminating so backgrounding it
    # is the designed shape (the MSBuild guard env prefix is required by
    # the class matcher and harmless - watch never builds).
    ("qiven ci watch full", "gate-class"),
    ("python tools/qiven.py ci watch --repo JasonHuang3D/qiven-runtime --workflow ci.yml --branch main --head 7b3ce51 --timeout 45 --receipt", "gate-class"),
    ("MSBUILDDISABLENODEREUSE=1 python tools/qiven.py ci watch full --receipt", "gate-class"),
    # env-prefixed invocations classify the same (v4.1: the taught guard
    # re-call form must not escape classification, and neither may an
    # arbitrary FOO=1 prefix bypass the gate class raw):
    ("MSBUILDDISABLENODEREUSE=1 tools/qiven.cmd gate", "gate-class"),
    ("FOO=1 qiven gate", "gate-class"),
    ("FOO=1 tools\\qiven.cmd run test-debug", "gate-class"),
    # v4.2: env BEFORE the python launcher is the TAUGHT guard re-call
    # form for python-launcher invocations - it must classify (and thus
    # carry the mechanically enforced guard), not escape raw:
    ("FOO=1 python tools/qiven.py gate", "gate-class"),
    ("MSBUILDDISABLENODEREUSE=1 python tools/qiven.py run test-debug", "gate-class"),
    # gate INSIDE exec is allowed (exec at command position; the gate
    # regex finds no command position for gate):
    ("tools/qiven.cmd exec start --timeout 900 -- cmd /c call tools/qiven.cmd gate", "allow"),
    # --- deny: build class (MSBuild node fanout -> background + guard) ---
    ("cmake --build build/vs2022-x64 --config Debug", "build"),
    ("cmake -S . -B build", "build"),
    ("ctest --test-dir build -C Debug", "build"),
    ("MSBuild.exe project.vcxproj /p:Configuration=Debug", "build"),
    ("dotnet build", "build"),
    # --- deny: repo-tool class (minutes-class -> background) --------------
    ("python tools/test_all.py --group repo", "repo-tool"),
    ("python tools/format_sources.py --fix", "repo-tool"),   # the sqlite3.c hang
    ("clang-format -i src/*.cpp", "repo-tool"),
    # --- deny: network class (acquisition -> background) ------------------
    ("pip install pyyaml", "network"),
    ("git clone https://github.com/x/y.git", "network"),     # unconditional: no local repo to probe
    ("git submodule update --init --recursive", "network"),
    ("gh run watch 12345", "network"),
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
    ("tools/qiven.cmd exec start -- x && ctest --test-dir b", "build"),
    ("echo a ; vim b.txt", "interactive"),
    # --- chained exec invocations (OBL-A7B8C9: segments after && arrive ---
    # --- with leading whitespace; the anchors must tolerate it) -----------
    ("git status --short && tools\\qiven.cmd exec start --timeout 600 -- cmake --build build", "allow"),
    ("cd /d/x && tools/qiven.cmd exec start --timeout 60 -- python t.py", "allow"),
    ("tools/qiven.cmd info && tools/qiven.cmd exec status abc", "allow"),
    ("git status && tools\\qiven.cmd gate", "gate-class"),
    ("git status &&    qiven run test-debug", "gate-class"),
    # --- tree sweeps are sweep-class: exec lease custody, NOT background --
    ("find /d/JasonWork -name '*.vcxproj'", "sweep"),
    ("find /d/JasonWork/qiven-runtime -type f -name '*.cpp'", "sweep"),
    ("find -L /d/JasonWork -name build", "sweep"),
    ("find D:\\JasonWork -name build", "sweep"),
    ("grep -r pattern .", "sweep"),
    ("grep --recursive foo src/", "sweep"),
    ("cmd /c dir /s /b", "sweep"),
    ("dir build /s", "sweep"),
    # the Windows text-FILTER find (slash-flag + quoted needle) stays raw:
    ("find /i \"marker\" out.log", "allow"),
    ("find \"needle\" file.txt", "allow"),
    # --- quote-awareness: quoted prose is not a command segment -----------
    ('git commit -m "text; qiven gate tools\\qiven.cmd gate --expect-head x" && git status', "allow"),
    ('git commit -m "mentions ctest inside quotes" && git log -1', "allow"),
    ("echo 'vim in single quotes' && git status", "allow"),
    # --- bypass tightening: qiven token NOT at a command position ---------
    ("echo tools/qiven && cmake --build build", "build"),
    ("cat qiven.cmd && python tools/test_all.py", "repo-tool"),
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


def background_cases() -> list[tuple[str, bool, bool]]:
    """(name, expect_denied, ...) encoded as closures below; each entry is
    (description, check) where check() returns an error string or None."""
    checks = []

    def check(desc, fn):
        checks.append((desc, fn))

    # raw build: one deny carries BOTH the background instruction and the
    # guard line (single round-trip teaching, ADR-0051).
    def raw_build():
        code, message = router.verdict("cmake --build build/vs2022-x64 --config Release")
        if code != 2:
            return "raw build must deny"
        if "run_in_background: true" not in message:
            return "raw build denial must instruct the background re-call"
        if "MSBUILDDISABLENODEREUSE=1" not in message:
            return "raw build denial must name the node-reuse guard"
        return None

    check("raw build deny teaches background + guard in one message", raw_build)

    def bg_build_no_guard():
        code, message = router.verdict(
            "cmake --build build/vs2022-x64 --config Release", background=True)
        if code != 2 or "node reuse" not in message:
            return "backgrounded build without guard must deny on node reuse"
        return None

    check("background build without guard denies", bg_build_no_guard)

    def bg_build_with_env_guard():
        code, _ = router.verdict(
            "MSBUILDDISABLENODEREUSE=1 cmake --build build/vs2022-x64 --config Release",
            background=True)
        if code != 0:
            return "backgrounded build with env-prefix guard must pass"
        return None

    check("background build with env guard passes", bg_build_with_env_guard)

    def bg_build_with_switch_guard():
        code, _ = router.verdict(
            "MSBuild.exe proj.vcxproj /nr:false", background=True)
        if code != 0:
            return "/nr:false must satisfy the guard"
        return None

    check("direct msbuild /nr:false satisfies the guard", bg_build_with_switch_guard)

    def guard_in_quotes_does_not_count():
        # a quoted -D value mentioning the env var is not a guard on the
        # command surface (quote-stripped before matching)
        code, _ = router.verdict(
            'cmake --build build -DFOO="MSBUILDDISABLENODEREUSE=1"', background=True)
        if code != 2:
            return "a guard inside quotes must not satisfy the check"
        return None

    check("quoted guard text does not satisfy the guard", guard_in_quotes_does_not_count)

    def raw_gate():
        code, message = router.verdict("tools/qiven.cmd gate --expect-head abc123")
        if code != 2 or "run_in_background: true" not in message or "MSBUILDDISABLENODEREUSE" not in message:
            return "raw gate deny must teach background + guard"
        return None

    check("raw gate deny teaches background + guard", raw_gate)

    def bg_gate_with_guard():
        code, _ = router.verdict(
            "MSBUILDDISABLENODEREUSE=1 tools/qiven.cmd gate --expect-head abc123",
            background=True)
        if code != 0:
            return "backgrounded gate with guard must pass"
        return None

    check("background gate with guard passes", bg_gate_with_guard)

    def env_prefixed_gate_raw_still_denies():
        # v4.1 regression: an env-prefixed gate call must NOT escape the
        # class (before the fix `FOO=1 qiven gate` ran raw - the prefix
        # broke the ^-anchored match and with it the entire teaching).
        code, message = router.verdict("FOO=1 tools/qiven.cmd gate local")
        if code != 2 or "run_in_background: true" not in message:
            return "env-prefixed raw gate must deny with the background teaching"
        return None

    check("env-prefixed raw gate denies (v4.1)", env_prefixed_gate_raw_still_denies)

    def env_prefixed_gate_bg_without_guard_denies():
        code, message = router.verdict("FOO=1 tools/qiven.cmd gate local", background=True)
        if code != 2 or "MSBUILDDISABLENODEREUSE" not in message:
            return "env-prefixed backgrounded gate without the guard must deny on node reuse"
        return None

    check("env-prefixed bg gate without guard denies (v4.1)",
          env_prefixed_gate_bg_without_guard_denies)

    def env_prefixed_operator_exec_stays_raw():
        # exec/info/status remain raw (no routing class) even env-prefixed
        code, _ = router.verdict("MSBUILDDISABLENODEREUSE=1 tools/qiven.cmd exec status abc123")
        if code != 0:
            return "env-prefixed operator exec/status must stay raw"
        return None

    check("env-prefixed operator exec stays raw (v4.1)", env_prefixed_operator_exec_stays_raw)

    def ci_watch_v31_usage_shape():
        # The exact OBL-F1A2B3 observation shape: cd + env guard +
        # explicit-identity watch, backgrounded. Raw (foreground) must
        # deny with the background+guard teaching; the guarded background
        # re-call must pass.
        raw = 'cd "D:\\JasonWork\\qiven-devkit" && python tools/qiven.py ci watch --repo JasonHuang3D/qiven-runtime --workflow ci.yml --branch main --head 7b3ce51 --timeout 45 --receipt'
        code, message = router.verdict(raw)
        if code != 2 or "run_in_background: true" not in message or "MSBUILDDISABLENODEREUSE" not in message:
            return "raw ci watch must deny with the background+guard teaching"
        guarded = 'cd "D:\\JasonWork\\qiven-devkit" && MSBUILDDISABLENODEREUSE=1 python tools/qiven.py ci watch --repo JasonHuang3D/qiven-runtime --workflow ci.yml --branch main --head 7b3ce51 --timeout 45 --receipt'
        code, _ = router.verdict(guarded, background=True)
        if code != 0:
            return "guarded backgrounded ci watch must pass"
        return None

    check("ci watch raw denies / guarded background passes (F1A2B3)", ci_watch_v31_usage_shape)

    def raw_network():
        code, message = router.verdict("pip install pyyaml")
        if code != 2 or "run_in_background: true" not in message:
            return "raw network deny must teach the background re-call"
        if "MSBUILDDISABLENODEREUSE" in message:
            return "network denial must not demand the node-reuse guard"
        return None

    check("raw network deny teaches background only", raw_network)

    def bg_network():
        code, _ = router.verdict("pip install pyyaml", background=True)
        if code != 0:
            return "backgrounded network must pass (no guard required)"
        return None

    check("background network passes without guard", bg_network)

    def bg_repo_tool():
        code, _ = router.verdict("python tools/test_all.py --group repo", background=True)
        if code != 0:
            return "backgrounded repo-tool must pass"
        return None

    check("background repo-tool passes", bg_repo_tool)

    def sweep_stays_exec_even_background():
        code, message = router.verdict("grep -r pattern .", background=True)
        if code != 2:
            return "sweep must deny even when backgrounded (exec lease custody)"
        if "qiven.cmd exec start" not in message or "re-issue THIS EXACT command" in message:
            return "sweep denial must route to exec lease, not a background re-call"
        return None

    check("sweep denies even backgrounded (exec lease)", sweep_stays_exec_even_background)

    def heredoc_denies_even_background():
        code, _ = router.verdict("cat << EOF", background=True)
        if code != 2:
            return "heredoc is absolute: background must not launder it"
        return None

    check("heredoc denies even when backgrounded", heredoc_denies_even_background)

    def payload_background_parsing():
        if not router._background_from({"tool_input": {"run_in_background": True}}):
            return "tool_input.run_in_background must parse True"
        if router._background_from({"tool_input": {"run_in_background": False}}):
            return "tool_input.run_in_background must parse False"
        if router._background_from({"tool_input": {"command": "x"}}):
            return "absent flag must parse False"
        if router._background_from("not-a-dict"):
            return "non-dict payload must parse False"
        return None

    check("payload run_in_background parsing", payload_background_parsing)

    return checks


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

    for desc, fn in background_cases():
        error = fn()
        if error:
            failures += 1
            print(f"[FAIL] v4 {desc}: {error}")

    # message provenance: every denial message carries the hook tag.
    # Git-network denial is exercised with routing force-enabled: the
    # shipped default is suspension (owner direction 2026-09-24).
    saved_git_flag = router.GIT_NETWORK_ROUTING_ENABLED
    router.GIT_NETWORK_ROUTING_ENABLED = True
    for command in ("cmake --build build", "tools/qiven.cmd gate", "vim x", "git push origin main",
                    "cat << EOF", "grep -r pattern ."):
        code, message = router.verdict(command, probe_runner=fake_runner([("origin/main\n", True, True), ("300\n", True, True)]))
        if code != 2 or "[qiven-hook]" not in message:
            failures += 1
            print(f"[FAIL] provenance tag missing in verdict for {command!r}")

    router.GIT_NETWORK_ROUTING_ENABLED = saved_git_flag

    # suspension sentinel: at the shipped default (suspended), a raw git
    # network command passes end-to-end. If this fails after flipping the
    # default back to True, update this test deliberately.
    code, message = router.verdict("git push origin main",
                                   probe_runner=fake_runner([("origin/main\n", True, True), ("3\n", True, True)]))
    if saved_git_flag:
        if code != 2:
            failures += 1
            print("[FAIL] git-network must deny when routing is enabled")
    elif code != 0 or message:
        failures += 1
        print("[FAIL] git-network must pass raw while routing is suspended (owner direction 2026-09-24)")

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
    print(f"[ OK ] router-tests: {len(CASES)} classification + {len(probe_cases())} probe + "
          f"{len(background_cases())} v4-background + provenance cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
