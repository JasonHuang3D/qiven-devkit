#!/usr/bin/env python3
"""ZCode PreToolUse hook: steer long-class raw shell commands to qiven exec.

Installed per the hang-contract execution path (collaboration/
operating-contract.md rule 5; canonical usage reference: qiven-devkit/
docs/conventions/operator-usage.md). Matcher: the Bash tool; the command
text is inspected HERE (a hook matcher only sees the tool name).

Verdicts:
  - already operator-mediated (qiven exec/gate/run/ci/info) -> allow
  - long-class raw command (builds, test suites, installs, toolchains)
    -> exit 2 deny, stderr carries the exact replacement pattern
  - everything else (short read-only work) -> silent allow

The hook is a backstop, never the contract: fail-open on unparseable
input (a broken detector must not brick the session).
"""

from __future__ import annotations

import json
import re
import sys

_LONG_CLASS = re.compile(
    r"cmake\s+(-S\b|--preset|--build)"
    r"|ctest\b"
    r"|msbuild\b"
    r"|\bcl\.exe\b"
    r"|\blink\.exe\b"
    r"|test_all\.py\b"
    r"|\bpytest\b"
    r"|python\s+-m\s+pytest\b"
    r"|pip\s+install\b"
    r"|npm\s+(install|ci)\b"
    r"|npm\s+run\s+build\b"
    r"|dotnet\s+(build|test)\b",
    re.IGNORECASE,
)

_OPERATOR_MEDIATED = re.compile(r"qiven(?:\.cmd|\.py|\.sh)?\s+(exec|gate|run|ci|info)\b|tools[/\\]qiven", re.IGNORECASE)

_DENY_REASON = (
    "long-class command invoked raw: route it through the Qiven Operator instead --\n"
    "  tools\\qiven.cmd exec start --timeout 600 -- <your command>\n"
    "then re-attach with:  tools\\qiven.cmd exec status <run-id>   (or stop <run-id>)\n"
    "exit 124 = still running (the child continues); see the canonical usage reference:\n"
    "qiven-devkit/docs/conventions/operator-usage.md  (hang-contract rule 5)"
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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable hook input: allow (fail-open detector)
    command = _command_from(payload)
    if not command or _OPERATOR_MEDIATED.search(command):
        return 0
    if _LONG_CLASS.search(command):
        sys.stderr.write(_DENY_REASON)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
