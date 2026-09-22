#!/usr/bin/env python3
"""ZCode PreToolUse hook: steer long-class, gate-class, interactive and
unmeasured-network raw shell commands away from the session shell
(hang-contract rule 5; collaboration/operating-contract.md; canonical
usage: qiven-devkit/docs/conventions/operator-usage.md; registry of
record: qiven-context collaboration/long-command-registry.md).

Every denial is prefixed "[qiven-hook]" and, where a probe ran, states
the MEASUREMENT ("measured: 137 commits ahead") so the receiving agent
knows the verdict came from this hook's judgment, not a mystery
failure (owner direction 2026-09-23: no ambiguous denials).

Verdicts:
  allow         short read-only work, or operator exec/info
  heredoc       shell heredoc authoring — ABSOLUTE denial (contract law
                MEM-20260921T203500Z-D2A7F4; owner direction 2026-09-23:
                the law was violated again after cold boot, so the hook
                now enforces it mechanically). Checked FIRST and inside
                exec payloads too: wrapping a heredoc in `qiven exec`
                does not launder it.
  long          unconditional long-class (builds, downloads, clone...)
  gate-class    qiven gate/run/ci invoked raw (minutes-class; exec them)
  interactive   suspends the shell awaiting a human
  git-network   git push/fetch/pull — probed below; allow only when the
                measured transfer is small (owner direction 2026-09-23:
                pre-judge the network payload; deny oversized to exec)

The hook is a backstop, never the contract: fail-open on unparseable
input. Text matching cannot catch indirection; the contract carries the
discipline.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

PROBE_BUDGET_S = 5.0
PUSH_COMMIT_THRESHOLD = 25

_LONG_CLASS = re.compile(
    # builds / build tools (long or unknown duration; heavy fan-out)
    r"cmake\s+(-S\b|-B\b|--preset\b|--build\b|--install\b)"
    r"|\bctest\b"
    r"|\bmsbuild\b"
    r"|\bdevenv\b"
    r"|\bcl\.exe\b"
    r"|\blink\.exe\b"
    r"|\bdotnet\s+(build|test)\b"
    # repository gate/tool entrypoints that sweep or build big trees
    r"|format_sources\.py\b"
    r"|\bformat(-check)?\.cmd\b"
    r"|\bclang-format\b"
    r"|test_all\.py\b"
    r"|\bpytest\b"
    r"|python\s+-m\s+pytest\b"
    r"|deploy_bundle\.py\b"
    r"|\bdeploy\.cmd\b"
    # filesystem tree sweeps (2026-09-23 incident: a raw Git-Bash `find`
    # over the workspace survived the session at 20%+ CPU; sweeps are
    # minutes-class and belong under exec custody). Path-argument forms
    # (`find /d/...`, `find D:\...`, flags then path) sweep; the Windows
    # text-FILTER form (`find /i "text" file` — slash-flag then quoted
    # needle) does not. grep -r/--recursive and `dir /s` same class.
    r"|\bg?find\s+(?:-[A-Za-z][A-Za-z0-9-]*\s+)*(?:[A-Za-z]:[\\/]|/[A-Za-z0-9_.-]+[\\/])"
    r"|\bgrep\s+(?:[^&|;]*\s)?(?:-r[A-Za-z]*\b|--recursive\b)"
    r"|\bdir\s+(?:[^&|;]*\s)?/[sb]\b"
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

# Heredoc authoring: `<<` / `<<-` at a command boundary followed by a
# delimiter word (bare or quoted). Applied to the quote-stripped segment
# surface, so heredoc SYNTAX matches while quoted PROSE ("use << EOF in
# docs") does not. Known accepted false positive: a shell bit-shift with
# a letter variable (`x << n`) — the denial message says to rewrite such
# expressions; strictness beats leaking heredoc authoring through a hook.
_HEREDOC = re.compile(
    r"(?:^|[\s;|&(<])<<-?\s*(?:[\"']\s*[\"']|[A-Za-z_][A-Za-z0-9_]*)"
)

# Segment-level patterns (each applied to ONE command segment, anchored
# at its start; see classify() for the splitting law).
_SEGMENT_PREFIX = r"^(?:cmd\s+/c\s+call\s+|cmd\s+/c\s+|call\s+|python\s+)?"
_GATE_CLASS = re.compile(
    _SEGMENT_PREFIX + r"(?:tools[/\\])?qiven(?:\.cmd|\.py|\.sh)?\s+(?:gate|run|ci)\b",
    re.IGNORECASE,
)
_OPERATOR_EXEC = re.compile(
    _SEGMENT_PREFIX + r"(?:tools[/\\])?qiven(?:\.cmd|\.py|\.sh)?\s+(?:exec|info|status)\b",
    re.IGNORECASE,
)
_GIT_NETWORK = re.compile(r"git\s+(push|fetch|pull)\b", re.IGNORECASE)

_HOOK_TAG = "[qiven-hook]"
_DENY_LONG = (
    f"{_HOOK_TAG} long-class command invoked raw: route it through the Qiven Operator instead --\n"
    "  tools\\qiven.cmd exec start --timeout 600 -- <your command>\n"
    "then re-attach with:  tools\\qiven.cmd exec status <run-id>   (or stop <run-id>)\n"
    "exit 124 = still running (the child continues); see the canonical usage reference:\n"
    "qiven-devkit/docs/conventions/operator-usage.md  (hang-contract rule 5)"
)
_DENY_GATE = (
    f"{_HOOK_TAG} qiven gate/run/ci are minutes-class and block the session shell -- run them detached:\n"
    "  tools\\qiven.cmd exec start --timeout 900 -- cmd /c call tools\\qiven.cmd gate --expect-head <sha>\n"
    "then poll:  tools\\qiven.cmd exec status <run-id>\n"
    "(short `qiven run` tasks are still covered by this rule while the per-task timers\n"
    "accumulate duration evidence in .generated-temp/operator/; the class split will be\n"
    "refined from that data, not by guesswork)"
)
_DENY_INTERACTIVE = (
    f"{_HOOK_TAG} interactive command invoked raw: it suspends the shell awaiting a human\n"
    "and hangs the tool call (2026-09-19 modal incident class). Use the non-interactive\n"
    "form (e.g. apply_patch.py / git add <paths>), or route a bounded non-interactive\n"
    "equivalent through qiven exec."
)
_DENY_HEREDOC = (
    f"{_HOOK_TAG} heredoc authoring DENIED (contract: collaboration/operating-contract.md\n"
    "File-authoring tool discipline; MEM-20260921T203500Z-D2A7F4; MEM-20260923T183000Z-A1B2C3).\n"
    "严厉禁止使用 heredoc：文件创作必须使用原生 Read/Write/Edit 工具；请勿尝试绕路。\n"
    "(A genuine bit-shift expression can match this pattern — rewrite it, e.g. compute via python.)"
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


def _split_segments(command: str) -> list[str]:
    """Split on command separators OUTSIDE single/double quotes (a quoted
    commit message containing ';' or a tool name must not become its own
    'segment' — found live 2026-09-23 when a commit message's semicolon
    produced a phantom gate-class segment)."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            continue
        if char in "&|;":
            lookahead = command[index + 1] if index + 1 < len(command) else ""
            if char in "&|" and lookahead in "&|":
                index += 1  # consume the second char of && or ||
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment for segment in segments if segment.strip()]


_VERDICT_PRIORITY = ("heredoc", "gate-class", "git-network", "long", "interactive")


def _strip_quoted(text: str) -> str:
    """Replace quoted spans with spaces so class regexes match only the
    COMMAND surface, not quoted prose (commit messages, PR bodies)."""
    out: list[str] = []
    quote: str | None = None
    for char in text:
        if quote is not None:
            out.append(" " if char != quote else char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
            continue
        out.append(char)
    return "".join(out)


def _classify_segment(segment: str) -> str:
    """One command segment (no separators). exec/info segments (the
    sanctioned operator wrappers) are exempt from ROUTING classes — but
    not from heredoc: an absolute authoring prohibition cannot be
    laundered by wrapping it in `qiven exec`. Everything else by class,
    matched against the quote-stripped command surface. Segments are
    lstripped before matching: a segment following `&&`/`;`/`|` arrives
    with a leading space and the anchors are `^`-anchored
    (OBL-20260923T224500Z-A7B8C9: chained exec invocations denied)."""
    if not segment.strip():
        return "allow"
    surface = _strip_quoted(segment.lstrip())
    if _HEREDOC.search(surface):
        return "heredoc"
    if _OPERATOR_EXEC.match(surface):
        return "allow"
    if _GATE_CLASS.match(surface):
        return "gate-class"
    if _GIT_NETWORK.search(surface):
        return "git-network"
    if _LONG_CLASS.search(surface):
        return "long"
    if _INTERACTIVE_CLASS.search(surface):
        return "interactive"
    return "allow"


def classify(command: str) -> str:
    """Whole-command classification: split on command separators (quote-
    aware), judge each segment independently, and return the
    highest-priority denial (an exec wrapper in one segment never
    launders a raw long command in another)."""
    if not command:
        return "allow"
    verdicts = [_classify_segment(segment) for segment in _split_segments(command)]
    for candidate in _VERDICT_PRIORITY:
        if candidate in verdicts:
            return candidate
    return "allow"


# --- git-network probe (bounded; injectable for tests) -------------------

def _workdir_from(command: str) -> str | None:
    """Best-effort repo dir: the last `cd <dir>` before the git command
    (git-bash /x/ paths mapped to X:\\). None = use the hook's cwd."""
    dirs = re.findall(r"(?:^|[&|;]\s*)cd\s+([^\s&;|]+)", command)
    if not dirs:
        return None
    raw = dirs[-1]
    match = re.match(r"^/([a-zA-Z])/(.*)$", raw)
    if match:
        return f"{match.group(1).upper()}:\\{match.group(2)}"
    return raw


def _run_git(args: list[str], cwd: str | None) -> tuple[str, bool, bool]:
    """Returns (output, completed, ok). completed=False -> probe budget hit."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=PROBE_BUDGET_S, check=False,
        )
        return (done.stdout or "") + (done.stderr or ""), True, done.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False, False
    except OSError:
        return "", True, False


def probe_git_network(command: str, runner=_run_git, workdir=None) -> tuple[str, str]:
    """Measured judgment for git push/fetch/pull. Returns (verdict, evidence)
    where verdict is 'allow' | 'deny'."""
    cwd = workdir if workdir is not None else _workdir_from(command)
    sub = _GIT_NETWORK.search(command)
    kind = sub.group(1).lower() if sub else "push"

    if kind == "push":
        out, completed, ok = runner(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd)
        if not completed:
            return "deny", f"probe exceeded {PROBE_BUDGET_S:.0f}s (upstream resolution)"
        upstream = out.strip().splitlines()[-1] if ok and out.strip() else None
        used_fallback = False
        if upstream is None:
            # new-branch first push (no upstream yet): measure against the
            # repository's default remote base instead of denying unmeasured
            used_fallback = True
            for fallback in ("origin/HEAD", "origin/main", "origin/master"):
                out, completed, ok = runner(["rev-parse", "--abbrev-ref", "--symbolic-full-name", fallback], cwd)
                if completed and ok and out.strip():
                    upstream = fallback
                    break
            if upstream is None:
                return "deny", "neither an upstream nor a default remote base resolvable (new repository?)"
        out, completed, ok = runner(["rev-list", "--count", f"{upstream}..HEAD"], cwd)
        if not completed or not ok:
            return "deny", "ahead-count not measurable"
        ahead = int(out.strip() or "0")
        if ahead > PUSH_COMMIT_THRESHOLD:
            return "deny", f"measured: {ahead} commits ahead of {upstream} (threshold {PUSH_COMMIT_THRESHOLD})"
        if used_fallback:
            # no upstream to negotiate a dry-run against; the count vs the
            # remote base IS the measurement
            return "allow", f"measured: {ahead} commits vs {upstream} (new-branch push; dry-run n/a)"
        out, completed, ok = runner(["push", "--dry-run"], cwd)
        if not completed:
            return "deny", f"measured: push dry-run exceeded {PROBE_BUDGET_S:.0f}s"
        if not ok:
            return "deny", "push dry-run failed (remote/auth); route through exec for the real attempt"
        return "allow", f"measured: {ahead} commits ahead; dry-run clean"

    # fetch / pull: only a fast, changeless dry-run may pass raw
    out, completed, ok = runner(["fetch", "--dry-run"], cwd)
    if not completed:
        return "deny", f"measured: fetch dry-run exceeded {PROBE_BUDGET_S:.0f}s"
    if not ok:
        return "deny", "fetch dry-run failed; route through exec"
    updates = [line for line in out.splitlines() if ".." in line and "->" in line]
    if updates:
        return "deny", f"measured: {len(updates)} remote ref change(s) pending (pack size unknown)"
    return "allow", "measured: remote up to date"


_DENY_GIT_NETWORK_TEMPLATE = (
    "{tag} git {kind} denied by measured judgment ({evidence}). Route through the operator:\n"
    "  tools\\qiven.cmd exec start --timeout 300 -- <your git command>\n"
    "then poll:  tools\\qiven.cmd exec status <run-id>. Small transfers pass this hook raw;\n"
    "only measured-oversized or unmeasurable ones are denied."
)


def verdict(command: str, probe_runner=_run_git) -> tuple[int, str]:
    """Full decision: (exit_code, stderr_message). 0 = allow."""
    kind = classify(command)
    if kind == "allow":
        return 0, ""
    if kind == "heredoc":
        return 2, _DENY_HEREDOC
    if kind == "long":
        return 2, _DENY_LONG
    if kind == "gate-class":
        return 2, _DENY_GATE
    if kind == "interactive":
        return 2, _DENY_INTERACTIVE
    if kind == "git-network":
        decision, evidence = probe_git_network(command, runner=probe_runner)
        if decision == "allow":
            return 0, ""
        sub = _GIT_NETWORK.search(command)
        word = sub.group(1).lower() if sub else "network"
        return 2, _DENY_GIT_NETWORK_TEMPLATE.format(tag=_HOOK_TAG, kind=word, evidence=evidence)
    return 0, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable hook input: allow (fail-open detector)
    code, message = verdict(_command_from(payload))
    if message:
        sys.stderr.write(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
