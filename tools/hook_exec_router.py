#!/usr/bin/env python3
"""ZCode PreToolUse hook: steer long-class and interactive raw shell
commands away from the session shell (hang contract rule 5;
collaboration/operating-contract.md; canonical usage reference:
qiven-devkit/docs/conventions/operator-usage.md).

Matcher: the Bash tool; the command text is inspected HERE (a hook
matcher only sees the tool name).

Verdicts:
  - already operator-mediated (qiven exec/gate/run/ci/info, or a
    tools/qiven entrypoint at a command position) -> allow
  - LONG-CLASS raw command -> exit 2 deny, stderr carries the exact
    replacement pattern (qiven exec start/status/stop)
  - INTERACTIVE-CLASS raw command -> exit 2 deny (an interactive
    command suspends the tool call awaiting a human; the 2026-09-19
    modal CRT incident is the governing precedent)
  - everything else (short read-only work) -> silent allow

Long classes (2026-09-23 review; each entry earned its place — this is
a backstop, not a firewall, so unlisted fast commands stay raw):
  builds/toolchains   cmake (-S/-B/--preset/--build/--install), ctest,
                      msbuild, cl.exe, link.exe, devenv, dotnet build/test
  repo tool gates     format_sources.py, format/format-check entrypoints,
                      clang-format (multi-file runs), test_all.py,
                      pytest, deploy_bundle.py/deploy.cmd (they build)
  network/download    curl, wget, Invoke-WebRequest/iwr/irm, pip
                      install/download, npm install/ci/run build,
                      git clone, git submodule update/sync, gh run watch
  compilers invoked raw on large trees (cl/link) as above

The hook is a backstop, never the contract: fail-open on unparseable
input (a broken detector must not brick the session). Text matching
cannot catch indirection (BASE=cmake; $BASE ...) — the contract, not
the detector, carries the discipline.
"""

from __future__ import annotations

import json
import re
import sys

_LONG_CLASS = re.compile(
    # builds / build tools (long or unknown duration; heavy fan-out)
    r"cmake\s+(-S\b|-B\b|--preset\b|--build\b|--install\b)"
    r"|\bctest\b"
    r"|\bmsbuild\b"
    r"|\bdevenv\b"
    r"|\bcl\.exe\b"
    r"|\blink\.exe\b"
    r"|\bdotnet\s+(build|test)\b"
    # repository gate/tool entrypoints that build or sweep big trees
    r"|format_sources\.py\b"
    r"|\bformat(-check)?\.cmd\b"
    r"|\bclang-format\b"
    r"|test_all\.py\b"
    r"|\bpytest\b"
    r"|python\s+-m\s+pytest\b"
    r"|deploy_bundle\.py\b"
    r"|\bdeploy\.cmd\b"
    # network acquisition (downloads can outlive any sane tool timeout)
    r"|\bcurl\b"
    r"|\bwget\b"
    r"|Invoke-WebRequest\b"
    r"|\biwr\b"
    r"|\birm\b"
    r"|pip\s+(install|download)\b"
    r"|python\s+-m\s+pip\s+(install|download)\b"
    r"|npm\s+(install|ci)\b"
    r"|npm\s+run\s+build\b"
    r"|git\s+(clone|submodule\s+(update|sync))\b"
    r"|gh\s+run\s+watch\b",
    re.IGNORECASE,
)

_INTERACTIVE_CLASS = re.compile(
    r"\b(vim|nano|emacs|notepad)\b"
    r"|git\s+(rebase\s+(-i|-p)|add\s+(-i|-p)|clean\s+-i|checkout\s+-p|reset\s+(-p|--patch)|restore\s+-p|stash\s+(-p|--patch))\b"
    # GUI launchers (devenv is long-class: its /build form is a build)
    r"|cmake\s+--open\b",
    re.IGNORECASE,
)

# Operator-mediated allowance: the qiven CLI at a COMMAND position (start
# of the invocation or right after a command separator), or any explicit
# tools/qiven entrypoint. Matching the path anywhere in the text would let
# `echo tools/qiven && cmake --build ...` bypass (2026-09-23 rigor fix).
_OPERATOR_MEDIATED = re.compile(
    r"(?:^|[&|;]\s*|\b(?:cmd\s+/c\s+call|python)\s+)"
    r"(?:tools[/\\])?qiven(?:\.cmd|\.py|\.sh)?\s+(exec|gate|run|ci|info)\b"
    r"|(?:^|[&|;]\s*|\bcall\s+)tools[/\\]qiven(?:\.cmd)?\b"
    r"|(?:^|[&|;]\s*|\bpython\s+)tools[/\\]qiven\.py\b",
    re.IGNORECASE,
)

_DENY_LONG = (
    "long-class command invoked raw: route it through the Qiven Operator instead --\n"
    "  tools\\qiven.cmd exec start --timeout 600 -- <your command>\n"
    "then re-attach with:  tools\\qiven.cmd exec status <run-id>   (or stop <run-id>)\n"
    "exit 124 = still running (the child continues); see the canonical usage reference:\n"
    "qiven-devkit/docs/conventions/operator-usage.md  (hang-contract rule 5)"
)

_DENY_INTERACTIVE = (
    "interactive command invoked raw: an interactive/interactive-patch command suspends\n"
    "the shell awaiting a human and hangs the tool call (2026-09-19 modal incident class).\n"
    "Use the non-interactive form (e.g. git rebase --onto / apply_patch.py / git add <paths>),\n"
    "or route a bounded non-interactive equivalent through qiven exec."
)


def _command_from(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("command")
        if isinstance(value, str):
            return value
    value = payload.get("command")
    return value if isinstance(value, str) else ""


def classify(command: str) -> str:
    """Return 'allow' | 'long' | 'interactive' for a command text.

    Exposed for the self-test; the ordering is deliberate: mediated
    allowance wins first, then long-class (a long build wrapped in an
    interactive-looking invocation is still long), then interactive.
    """
    if not command or _OPERATOR_MEDIATED.search(command):
        return "allow"
    if _LONG_CLASS.search(command):
        return "long"
    if _INTERACTIVE_CLASS.search(command):
        return "interactive"
    return "allow"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable hook input: allow (fail-open detector)
    verdict = classify(_command_from(payload))
    if verdict == "long":
        sys.stderr.write(_DENY_LONG)
        return 2
    if verdict == "interactive":
        sys.stderr.write(_DENY_INTERACTIVE)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
