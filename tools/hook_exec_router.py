#!/usr/bin/env python3
"""ZCode PreToolUse hook: steer long-class, gate-class, interactive and
unmeasured-network raw shell commands away from the session shell
(hang-contract rule 5; collaboration/operating-contract.md; canonical
usage: qiven-devkit/docs/conventions/operator-usage.md; registry of
record: qiven-context collaboration/long-command-registry.md).

v4 (ADR-0051, 2026-09-24): the default reroute for in-session long work
is the HARNESS's run_in_background - one re-call, one completion
notification, zero polling. exec-detour + status-poll loops and
foreground sleep+tail loops are the anti-pattern being retired. The
Qiven Operator exec remains the sanctioned path ONLY for custody
classes: unbounded tree sweeps (lease-bounded ghost-process class),
runs that must survive the session, owner kits, and work past the
10-min Bash timeout ceiling.

v4.3 (owner direction 2026-09-26, token economy): sweeps split by
INHERENT BOUNDEDNESS. `git grep` / `git ls-files` walk tracked files
only (they structurally cannot enter .venv/node_modules/third-party
checkouts) and pass RAW - zero round-trips, zero context cost; a
sweep-class denial that pushes the model into whole-file Reads
pollutes the live context and compounds the compaction problem.
Recursive grep/find/dir sweeps whose explicit path arguments stay
strictly inside the workspace root (and name no heavy directory) are
seconds-class: deny -> run_in_background re-call, with the
--exclude-dir bounding carried in the command because the Bash timeout
parameter does not bind background tasks (P3). Sweeps without an
explicit in-scope path, escaping the root, or naming a heavy tree stay
exec-lease custody (the 2026-09-23 ghost-process class; OBL-D5E6F7
reframing: operational session end kills nothing, so an unbounded
background sweep can outlive the session).

Every denial is prefixed "[qiven-hook]" and, where a probe ran, states
the MEASUREMENT ("measured: 137 commits ahead") so the receiving agent
knows the verdict came from this hook's judgment, not a mystery
failure (owner direction 2026-09-23: no ambiguous denials).

Verdicts:
  allow         short read-only work, operator exec/info, or a
                backgrounded long-class call that satisfied its guard
  heredoc       shell heredoc authoring - ABSOLUTE denial (contract law
                MEM-20260921T203500Z-D2A7F4; owner direction 2026-09-23:
                the law was violated again after cold boot, so the hook
                now enforces it mechanically). Checked FIRST and inside
                exec payloads too: wrapping a heredoc in `qiven exec`
                does not launder it.
  gate-class    qiven gate/run/ci invoked raw (minutes-class, may build)
  build         builds/toolchains - background re-call AND the MSBuild
                node-reuse guard (ADR-0048 s3 defense in depth extended
                to the background path by ADR-0051)
  sweep-scoped filesystem tree sweep with explicit path arguments that
                stay strictly inside the workspace root and name no
                heavy directory - seconds-class: background re-call
                (v4.3); the bounding rides the command (P3)
  sweep-        unbounded filesystem tree sweep (no explicit in-scope
  unbounded     path, escapes the root, or names a heavy tree) - exec
                lease custody ONLY (the ghost-process class; OBL-D5E6F7
                reframing: session end kills nothing)
  repo-tool     repository gate/tool entrypoints - background re-call
  network       network acquisition - background re-call
  interactive   suspends the shell awaiting a human
  git-network   git push/fetch/pull - probed below; allow only when the
                measured transfer is small (owner direction 2026-09-23:
                pre-judge the network payload; deny oversized to a
                backgrounded re-call)

The hook is a backstop, never the contract: fail-open on unparseable
input. Text matching cannot catch indirection; the contract carries the
discipline.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROBE_BUDGET_S = 5.0
PUSH_COMMIT_THRESHOLD = 25

# Owner direction 2026-09-24: git-network routing is TEMPORARILY SUSPENDED.
# Raw `git push/fetch/pull` pass this hook unprobed while the exec child's
# credential path fails headless (GCM dialog auto-cancel + the obsolete
# 'manager-core' helper name in global gitconfig). The probe logic and its
# tests are unchanged underneath; flip this flag back to True to reinstate
# the measured judgment.
GIT_NETWORK_ROUTING_ENABLED = False

# ADR-0051 clause 3: build/gate classes re-called with run_in_background
# must disable MSBuild node reuse - worker nodes are deliberate survivors
# of the primary and the completion notification would strand them (the
# 2026-09-23 leak class). Accept the env prefix or the direct msbuild
# switches, anywhere in the command surface.
_NODE_REUSE_GUARD = re.compile(
    r"MSBUILDDISABLENODEREUSE\s*=" r"|/nr:false" r"|/nodeReuse:false",
    re.IGNORECASE,
)

_BUILD_CLASS = re.compile(
    # builds / build tools (long or unknown duration; heavy fan-out)
    r"cmake\s+(-S\b|-B\b|--preset\b|--build\b|--install\b)"
    r"|\bctest\b"
    r"|\bmsbuild\b"
    r"|\bdevenv\b"
    r"|\bcl\.exe\b"
    r"|\blink\.exe\b"
    r"|\bdotnet\s+(build|test)\b",
    re.IGNORECASE,
)

# Filesystem tree sweeps (2026-09-23 incident: a raw Git-Bash `find` over
# the workspace survived the session at 20%+ CPU; unbounded sweeps are
# minutes-class and belong under exec custody's lease). Path-argument forms
# (`find /d/...`, `find D:\...`, flags then path) sweep; the Windows
# text-FILTER form (`find /i "text" file` - slash-flag then quoted needle)
# does not. grep -r/--recursive and `dir /s` same class. v4.3: a match is
# then sub-classified by _sweep_scope (scoped -> background; unbounded ->
# exec lease); `git grep`/`git ls-files` never reach this class at all.
_SWEEP_CLASS = re.compile(
    r"\bg?find\s+(?:-[A-Za-z][A-Za-z0-9-]*\s+)*"
    r"(?:[A-Za-z]:[\\/]|/[A-Za-z0-9_.-]+[\\/]"
    r"|[A-Za-z0-9_.\-][A-Za-z0-9_.\-\\/]*(?:\s|$))"
    r"|\bgrep\s+(?:[^&|;]*\s)?(?:-r[A-Za-z]*\b|--recursive\b)"
    r"|\bdir\s+(?:[^&|;]*\s)?/[sb]\b",
    re.IGNORECASE,
)

# Heavy directory components: a sweep whose target names one of these is
# minutes-class regardless of scope (vendored trees, dependency forests,
# git object stores). Membership is owned by the canonical registry
# (qiven-context collaboration/long-command-registry.md).
_HEAVY_DIR_COMPONENTS = frozenset(
    {".venv", "node_modules", ".git", "third-party-win", "qiven-third-party-win"}
)

# Repository gate/tool entrypoints that sweep or build big trees.
_REPO_TOOL_CLASS = re.compile(
    r"format_sources\.py\b"
    r"|\bformat(-check)?\.cmd\b"
    r"|\bclang-format\b"
    r"|test_all\.py\b"
    r"|\bpytest\b"
    r"|python\s+-m\s+pytest\b"
    r"|deploy_bundle\.py\b"
    r"|\bdeploy\.cmd\b",
    re.IGNORECASE,
)

# Network acquisition (downloads can outlive any sane tool timeout).
_NETWORK_CLASS = re.compile(
    r"\bcurl\b"
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
    # GUI launchers (devenv is build-class: its /build form is a build)
    r"|cmake\s+--open\b",
    re.IGNORECASE,
)

# Heredoc authoring: `<<` / `<<-` at a command boundary followed by a
# delimiter word (bare or quoted). Applied to the quote-stripped segment
# surface, so heredoc SYNTAX matches while quoted PROSE ("use << EOF in
# docs") does not. Known accepted false positive: a shell bit-shift with
# a letter variable (`x << n`) - the denial message says to rewrite such
# expressions; strictness beats leaking heredoc authoring through a hook.
_HEREDOC = re.compile(
    r"(?:^|[\s;|&(<])<<-?\s*(?:[\"']\s*[\"']|[A-Za-z_][A-Za-z0-9_]*)"
)

# Segment-level patterns (each applied to ONE command segment, anchored
# at its start; see classify() for the splitting law). The launcher/env
# prefix tolerates BOTH orders - `python FOO=1 qiven ...` and
# `FOO=1 python qiven ...` (v4.2, 2026-09-26: the TAUGHT guard re-call
# form is `MSBUILDDISABLENODEREUSE=1 <same command>`, and when the same
# command uses the python launcher the env assignment lands BEFORE
# `python` - that form escaped classification entirely, so the guard
# check never fired for it; found by the ci-watch router test).
_SEGMENT_PREFIX = (
    r"^(?:cmd\s+/c\s+call\s+|cmd\s+/c\s+|call\s+)?"
    r"(?:python\s+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s\"']+)\s+)*"
    r"(?:python\s+)?"
)
_GATE_CLASS = re.compile(
    _SEGMENT_PREFIX + r"(?:tools[/\\])?qiven(?:\.cmd|\.py|\.sh)?\s+(?:gate|run|ci)\b",
    re.IGNORECASE,
)
_OPERATOR_EXEC = re.compile(
    _SEGMENT_PREFIX + r"(?:tools[/\\])?qiven(?:\.cmd|\.py|\.sh)?\s+(?:exec|info|status)\b",
    re.IGNORECASE,
)
# v4.3 (owner direction 2026-09-26): git's own tree walks are INHERENTLY
# BOUNDED - tracked files only, structurally unable to enter .venv/
# node_modules/third-party checkouts - so they pass raw: zero round-trips,
# zero context cost. Without this exemption `git grep -rn x` matched the
# sweep class through its -r flag and pushed the model toward whole-file
# Reads (the exact context-pollution compounding the owner flagged).
_GIT_BOUNDED_SEARCH = re.compile(
    _SEGMENT_PREFIX + r"git\s+(?:grep|ls-files)\b",
    re.IGNORECASE,
)
_GIT_NETWORK = re.compile(r"git\s+(push|fetch|pull)\b", re.IGNORECASE)

_HOOK_TAG = "[qiven-hook]"

# ADR-0051: the reroute instruction. One denied call is the entire
# overhead; the backgrounded re-call returns an output-file path
# immediately and the harness notifies once on completion.
_DENY_BG_TEMPLATE = (
    "{tag} {klass} invoked raw: re-issue THIS EXACT command with run_in_background: true\n"
    "(Bash tool parameter). It returns an output-file path immediately and notifies you ONCE on\n"
    "completion - do NOT poll (no exec status loops, no sleep+tail), do NOT detour through qiven\n"
    "exec (ADR-0051). Oversized output auto-persists to a file with a short preview returned.\n"
)
_DENY_BG_GUARD_LINE = (
    "This class also needs the MSBuild node-reuse guard on the re-call:\n"
    "  MSBUILDDISABLENODEREUSE=1 <same command>    (with run_in_background: true)"
)
# The guard denial (a backgrounded build/gate re-call arrived without it).
_DENY_BG_GUARD_TEMPLATE = (
    "{tag} {klass} under run_in_background must ALSO disable MSBuild node reuse - worker nodes\n"
    "deliberately survive their primary and the completion notification would strand them (the\n"
    "2026-09-23 leak class; ADR-0048 s3, ADR-0051 s3). Re-issue as:\n"
    "  MSBUILDDISABLENODEREUSE=1 <same command>    (with run_in_background: true)\n"
    "(/nr:false or /nodeReuse:false also satisfies the guard for direct msbuild calls)."
)
# v4.3 scoped sweep: seconds-class by construction (explicit in-scope
# path arguments), so the harness background path carries it; the
# bounding rides the command because the Bash timeout parameter does
# NOT bind background tasks (P3).
_DENY_SWEEP_SCOPED_TEMPLATE = (
    "{tag} repo-scoped filesystem sweep invoked raw: re-issue THIS EXACT command with\n"
    "run_in_background: true (Bash tool parameter) - the output auto-persists with a short\n"
    "preview, so the scan never floods your context. Background is NOT timeout-bounded (P3):\n"
    "bound the walk in the command, e.g. --exclude-dir=.venv --exclude-dir=node_modules\n"
    "--exclude-dir=build --exclude-dir=.git (grep), or prefer `git grep <pattern>` / `git\n"
    "ls-files` (tracked files only), which pass this hook raw (v4.3)."
)
# Unbounded sweeps stay under exec lease custody (ADR-0051 clause 5 as
# reframed by OBL-D5E6F7: operational session end kills nothing, so an
# unbounded background sweep can outlive the session - the ghost class).
_DENY_SWEEP_TEMPLATE = (
    "{tag} unbounded filesystem tree sweep (no explicit in-repo path, escapes the workspace\n"
    "root, or names a heavy tree like .venv/node_modules/third-party): this class runs under\n"
    "the Qiven Operator lease - custody must not depend on this session's lifetime (ghost-\n"
    "process class, ADR-0051 s5); run_in_background is NOT sufficient here. Route it:\n"
    "  tools\\qiven.cmd exec start --timeout 600 -- <your command>\n"
    "exit 124 = still running; re-attach then (and only then): tools\\qiven.cmd exec status <run-id>\n"
    "Better for your context budget: scope the sweep to an explicit in-repo subpath (then the\n"
    "run_in_background re-call passes), or use `git grep <pattern>` / `git ls-files` (tracked\n"
    "files only), which pass this hook raw (v4.3)."
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


def _background_from(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("run_in_background")
        if isinstance(value, bool):
            return value
    value = payload.get("run_in_background")
    return value if isinstance(value, bool) else False


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


_VERDICT_PRIORITY = (
    "heredoc",
    "gate-class",
    "git-network",
    "build",
    "sweep-unbounded",
    "sweep-scoped",
    "repo-tool",
    "network",
    "interactive",
)


def _argv(raw: str) -> list[str]:
    """Quote-aware tokenization that KEEPS backslashes (posix=False - the
    backslash-eating scar class, MEM-20260925T174500Z-E5F6A7) and strips
    one layer of matching surrounding quotes per token. Empty on
    unparseable input (caller treats that as unbounded)."""
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError:
        return []
    out: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            token = token[1:-1]
        out.append(token)
    return out


def _path_is_scoped(token: str, root_normalized: str) -> bool:
    """One path candidate is in-scope iff it is relative without any '..'
    or heavy component, or absolute, strictly inside the scope root, with
    no heavy component below it. '.' (the root wholesale) is NOT scoped.
    The bound is on the ENTRY POINT, not the subtree contents - the
    background teaching carries --exclude-dir (registry residual)."""
    match = re.match(r"^/([a-zA-Z])/(.+)$", token)
    if match:  # Git-Bash drive form /d/... -> D:\...
        token = f"{match.group(1).upper()}:\\{match.group(2)}"
    if re.match(r"^[a-zA-Z]:", token):
        normalized = os.path.normcase(os.path.normpath(token))
        if normalized == root_normalized:
            return False  # the workspace root wholesale = unbounded
        if not normalized.startswith(root_normalized + os.sep):
            return False  # escapes the scope root entirely
        below = [c for c in normalized[len(root_normalized):].split(os.sep) if c]
        return not any(c.lower() in _HEAVY_DIR_COMPONENTS for c in below)
    parts = [c for c in re.split(r"[\\/]+", token) if c not in ("", ".")]
    if not parts or any(c == ".." for c in parts):
        return False  # no real target ('.'/empty = root wholesale) or escape
    return not any(c.lower() in _HEAVY_DIR_COMPONENTS for c in parts)


def _sweep_scope(segment: str, scope_root: Path) -> str:
    """Sub-classify a segment that already matched _SWEEP_CLASS:
    'sweep-scoped' iff EVERY explicit path candidate is in-scope and at
    least one exists; else 'sweep-unbounded'. Path candidates are
    approximated from argv: leading env assignments and cd/cmd/call
    wrappers are skipped; '-' flags (and short '/x' dir-flags) are
    skipped; for grep the first non-flag token is the PATTERN and is
    dropped. The approximation fails toward 'unbounded' (friction, not
    danger)."""
    tokens = _argv(segment.strip())
    index = 0
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
        index += 1
    while index < len(tokens) and tokens[index].lower() in ("cmd", "/c", "call", "python"):
        index += 1
    tool = tokens[index].lower() if index < len(tokens) else ""
    candidates: list[str] = []
    dropped_pattern = False
    for token in tokens[index + 1:]:
        if token.startswith("-"):
            continue
        if token.startswith("/") and len(token) <= 3:
            continue  # dir-style flag (/s /b /x)
        if tool.endswith("grep") and not dropped_pattern:
            dropped_pattern = True  # grep's PATTERN positional
            continue
        candidates.append(token)
    root_normalized = os.path.normcase(str(scope_root.resolve()))
    if candidates and all(_path_is_scoped(c, root_normalized) for c in candidates):
        return "sweep-scoped"
    return "sweep-unbounded"


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


def _classify_segment(segment: str, scope_root: Path) -> str:
    """One command segment (no separators). exec/info segments (the
    sanctioned operator wrappers) are exempt from ROUTING classes — but
    not from heredoc: an absolute authoring prohibition cannot be
    laundered by wrapping it in `qiven exec`. git grep/ls-files segments
    are inherently bounded and pass raw (v4.3). Everything else by
    class, matched against the quote-stripped command surface. Segments
    are lstripped before matching: a segment following `&&`/`;`/`|`
    arrives with a leading space and the anchors are `^`-anchored
    (OBL-20260923T224500Z-A7B8C9: chained exec invocations denied)."""
    if not segment.strip():
        return "allow"
    surface = _strip_quoted(segment.lstrip())
    if _HEREDOC.search(surface):
        return "heredoc"
    if _OPERATOR_EXEC.match(surface):
        return "allow"
    if _GIT_BOUNDED_SEARCH.match(surface):
        return "allow"
    if _GATE_CLASS.match(surface):
        return "gate-class"
    if _GIT_NETWORK.search(surface):
        return "git-network"
    if _BUILD_CLASS.search(surface):
        return "build"
    if _SWEEP_CLASS.search(surface):
        return _sweep_scope(segment, scope_root)
    if _REPO_TOOL_CLASS.search(surface):
        return "repo-tool"
    if _NETWORK_CLASS.search(surface):
        return "network"
    if _INTERACTIVE_CLASS.search(surface):
        return "interactive"
    return "allow"


def classify(command: str, scope_root: Path | None = None) -> str:
    """Whole-command classification: split on command separators (quote-
    aware), judge each segment independently, and return the
    highest-priority denial (an exec wrapper in one segment never
    launders a raw long command in another). scope_root defaults to the
    hook process cwd (the workspace root in practice) and bounds the
    sweep-scoped subclass."""
    if not command:
        return "allow"
    root = scope_root if scope_root is not None else Path.cwd()
    verdicts = [_classify_segment(segment, root) for segment in _split_segments(command)]
    for candidate in _VERDICT_PRIORITY:
        if candidate in verdicts:
            return candidate
    return "allow"


def has_node_reuse_guard(command: str) -> bool:
    """ADR-0051 clause 3 guard check on the quote-stripped surface."""
    return bool(_NODE_REUSE_GUARD.search(_strip_quoted(command)))


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
    "{tag} git {kind} denied by measured judgment ({evidence}). Re-issue with\n"
    "run_in_background: true (ADR-0051). Small transfers pass this hook raw;\n"
    "only measured-oversized or unmeasurable ones are denied."
)


def verdict(command: str, probe_runner=_run_git, background: bool = False,
            scope_root: Path | None = None) -> tuple[int, str]:
    """Full decision: (exit_code, stderr_message). 0 = allow.

    `background` mirrors the Bash tool call's run_in_background flag
    (ADR-0051): the long/gate/network classes are satisfied by a
    backgrounded re-call; build/gate additionally require the MSBuild
    node-reuse guard; scoped sweeps are satisfied by a backgrounded
    re-call (v4.3) while unbounded sweeps always require exec lease
    custody."""
    kind = classify(command, scope_root)
    if kind == "allow":
        return 0, ""
    if kind == "heredoc":
        return 2, _DENY_HEREDOC
    if kind == "interactive":
        return 2, _DENY_INTERACTIVE
    if kind == "sweep-scoped":
        if not background:
            return 2, _DENY_SWEEP_SCOPED_TEMPLATE.format(tag=_HOOK_TAG)
        return 0, ""
    if kind == "sweep-unbounded":
        return 2, _DENY_SWEEP_TEMPLATE.format(tag=_HOOK_TAG)
    if kind in ("build", "gate-class"):
        if not background:
            message = _DENY_BG_TEMPLATE.format(tag=_HOOK_TAG, klass=kind) + _DENY_BG_GUARD_LINE
            return 2, message
        if not has_node_reuse_guard(command):
            return 2, _DENY_BG_GUARD_TEMPLATE.format(tag=_HOOK_TAG, klass=kind)
        return 0, ""
    if kind in ("repo-tool", "network"):
        if not background:
            return 2, _DENY_BG_TEMPLATE.format(tag=_HOOK_TAG, klass=kind)
        return 0, ""
    if kind == "git-network":
        if not GIT_NETWORK_ROUTING_ENABLED:
            return 0, ""  # suspended (owner direction 2026-09-24) — see flag
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
    code, message = verdict(
        _command_from(payload),
        background=_background_from(payload),
    )
    if message:
        sys.stderr.write(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
