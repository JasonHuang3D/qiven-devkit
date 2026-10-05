from __future__ import annotations

"""WR-8 forbidden resolver-pattern gate (ADR-0052 doc 02 section WR-8).

Static checks that the retired dependency-resolution architecture cannot
be reintroduced through normal paths:

  R1  CMake sibling discovery      - ../qiven-* or QIVEN_DEVKIT_ROOT /
      QIVEN_DRAFT_ROOT in CMake files outside comment lines; the same
      env-var/sibling-fallback class in .cmd/.bat launchers (rem/::
      comments stripped; the qiven.cmd thin-launcher exception honored)
  R2  consumer-local workspace pins - devkit_pin / QIVEN_DEVKIT_PIN keys
  R3  Devkit sibling import fallback - ../qiven-devkit on Python import
      paths outside the documented exceptions
  R4  toolchain selection outside the lock - a Python file referencing
      qiven-toolchain-win as a path without the workspace.lock.json
      identity check
  R5  vendored operator copies      - qiven_operator.py outside the
      devkit home and the two documented repository-owned instances
  R6  process-global handler installs in the I0-declared gap trees -
      the C++ diagnostics I0 census (qiven-runtime
      docs/design/cpp-diagnostics-i0-census.md section 2.5) could not
      line-audit qiven-third-party-win (vendored sqlite3) or
      qiven-context-draft (compiled first-party code linked into every
      governed executable); this class scans their tracked-tree C/C++
      sources for the census's process-wide handler-install vocabulary
      and fails typed on any site outside the admitted map, so "zero
      unknown process-global handler sites for linked images" is
      mechanically proven instead of declared. Raw-text scan (git-grep
      parity with the census method - a commented mention fires and is
      classified by a human); the Foundation/runtime install surfaces
      are census-covered and stay outside R6 scope (their mechanical
      duplicate-installer gate arrives with the I1/I3 diagnostics work).

Narrowly documented exceptions (doc 02 WR-8: "with narrowly documented
bootstrap exceptions"): the control-repository bootstrap + thin launcher
(the locator mechanism itself) and the runtime/foundation full operator
instances (repository-owned tooling predating the managed-template
class; the workspace-root launcher consolidation is the recorded
follow-up - wr6-report residual). Everything else fails typed.

Standard library only, Python 3.9+. Exit 0 clean / 1 findings / 2 usage.
"""

import argparse
import re
import sys
from pathlib import Path

SCANNED_REPOS = [
    "qiven-context",
    "qiven-context-draft",
    "qiven-foundation",
    "qiven-math",
    "qiven-runtime",
    "qiven-docs",
    "qiven-toolchain-win",
    "qiven-third-party-win",
    "qiven-workspace",
]

# R3/R5 exceptions: the bootstrap/launcher mechanism and the two recorded
# repository-owned operator instances (wr6-report: post-window
# consolidation with the workspace-root launcher).
PATH_EXCEPTIONS = {
    "bootstrap/qiven-bootstrap.py",
    "qiven.cmd",
    "tools/qiven_operator.py",  # only honored for foundation/runtime (below)
}
OPERATOR_INSTANCE_REPOS = {"qiven-foundation", "qiven-runtime"}

CMAKE_FILES = ("cmakelists.txt",)
CMAKE_SUFFIX = ".cmake"
CONFIG_SUFFIXES = (".json", ".yaml", ".yml", ".cmake", ".props", ".vsixmanifest")
LAUNCHER_SUFFIXES = (".cmd", ".bat")
PIN_KEYS = re.compile(r"devkit_pin|QIVEN_DEVKIT_PIN|QIVEN_DRAFT_PIN", re.I)
SIBLING_PATH = re.compile(r"\.\./qiven-[a-z-]+|\"qiven-(?:devkit|draft)-root\"", re.I)
BATCH_SIBLING_PATH = re.compile(r"\.\.[\\/]qiven-[a-z-]+", re.I)
CMAKE_ENV_VARS = re.compile(r"QIVEN_(?:DEVKIT|DRAFT)_ROOT", re.I)
# R3: a devkit sibling reference in Python is the sanctioned launcher
# shape ONLY when the same file carries the bootstrap identity-check
# marker; an unguarded import path (literal or Path-composed) is the
# forbidden fallback class. Adjacency: the reference must sit on a line
# with path/import machinery - prose citations of law documents and
# kit-payload absolute locators are a recorded residual, not imports.
DEVKIT_REF_LINE = re.compile(
    r"[^\n]*(?:qiven-devkit)[^\n]*", re.I)
PATH_MACHINERY = re.compile(r"Path|parent|sys\.path|importlib|\.\./", re.I)
IDENTITY_MARKER = re.compile(
    r"bootstrap|_bootstrap_identity|BootstrapDevkitMismatch|gate-configure", re.I)
TOOLCHAIN_REF = re.compile(r"qiven-toolchain-win", re.I)
LOCK_REF = re.compile(r"workspace\.lock\.json", re.I)

# R6 (I0 census section 2.5 gap closure): process-global handler-install
# vocabulary over the two census-declared unaudited trees. Admitted sites
# map repo -> {relative posix paths}; empty today (both trees scan clean
# at adoption - the gate's first run is the classification proof).
HANDLER_REPOS = ("qiven-third-party-win", "qiven-context-draft")
CPP_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx", ".inl")
HANDLER_INSTALL = re.compile(
    r"SetConsoleCtrlHandler|SetUnhandledExceptionFilter|"
    r"_set_invalid_parameter_handler|_set_abort_behavior|"
    r"set_terminate|_set_purecall_handler|AddVectoredExceptionHandler|"
    r"SetErrorMode|_CrtSetReportMode|_set_se_translator|"
    r"\bsignal\s*\(")
HANDLER_ADMITTED = {
    "qiven-third-party-win": set(),
    "qiven-context-draft": set(),
}


def is_config(path: Path) -> bool:
    return path.suffix.lower() in CONFIG_SUFFIXES or path.name.lower() in CMAKE_FILES


def strip_batch_comments(text: str) -> str:
    # batch launchers: drop rem lines and :: label comments; keep the rest
    # (the R1 launcher class lives in set/if/echo-active lines)
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip().lower()
        if stripped.startswith("rem ") or stripped == "rem" or stripped.startswith("::"):
            out_lines.append("")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def strip_cmake_comments(text: str) -> str:
    # bracket comments at ANY level (#[[ .. ]], #[=[ .. ]=], ...) are
    # stripped as blocks; line comments at the first # (F4: law text
    # inside comments is not a pattern)
    out_lines: list[str] = []
    closer = ""
    for line in text.splitlines():
        if closer:
            if closer in line:
                line = line.split(closer, 1)[1]
                closer = ""
            else:
                out_lines.append("")
                continue
        stripped = line.lstrip()
        opened = re.match(r"#\[=*\[", stripped)
        if opened:
            opener = opened.group(0)  # "#[[" or "#=[" or "#==[" ...
            closer = "]" + "=" * opener.count("=") + "]"
            line = line.split(opener, 1)[0]
        out_lines.append(line.split("#", 1)[0])
    return "\n".join(out_lines)


def iter_files(repo: Path):
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(repo).parts
        if parts[0] in {".git", "build", ".generated-temp", "__pycache__"}:
            continue
        # .qiven is CONFIG (the historical pin home) - only its live
        # runtime-state subdir and generated cache are excluded
        if parts[:2] == (".qiven", "runtime"):
            continue
        yield path


def scan_repo(repo: Path, repo_name: str, findings: list[str]) -> None:
    for path in iter_files(repo):
        rel = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = path.name
        lowered = name.lower()
        if lowered in CMAKE_FILES or lowered.endswith(CMAKE_SUFFIX):
            functional = strip_cmake_comments(text)
            for match in CMAKE_ENV_VARS.finditer(functional):
                findings.append(f"R1 {repo_name}/{rel}: CMake env var {match.group(0)}")
            for match in SIBLING_PATH.finditer(functional):
                findings.append(f"R1 {repo_name}/{rel}: CMake sibling path {match.group(0)}")
        # R2 scoping: a live pin lives in configuration (the historical
        # mechanism was operator.json/CMake) - prose records (ADR/session/
        # memory/audit history) and tests that BAN the key by naming it
        # are documentation, not pins; CMake-family configs are searched
        # with their comments stripped (law text is not a pattern).
        if is_config(path) and PIN_KEYS.search(text):
            if lowered.endswith(CMAKE_SUFFIX) or lowered in CMAKE_FILES:
                if not PIN_KEYS.search(strip_cmake_comments(text)):
                    continue
            findings.append(f"R2 {repo_name}/{rel}: consumer-local workspace pin key")
        if lowered.endswith(".py"):
            if rel not in PATH_EXCEPTIONS and not IDENTITY_MARKER.search(text):
                for line_match in DEVKIT_REF_LINE.finditer(text):
                    if PATH_MACHINERY.search(line_match.group(0)):
                        findings.append(f"R3 {repo_name}/{rel}: devkit sibling reference without"
                                        " the bootstrap identity-check marker")
                        break
            if TOOLCHAIN_REF.search(text) and not LOCK_REF.search(text):
                findings.append(f"R4 {repo_name}/{rel}: toolchain path without the lock check"
                                " (co-occurrence marker; constructed-name evasion is a recorded"
                                " residual)")
        if lowered == "qiven_operator.py":
            allowed = repo_name in OPERATOR_INSTANCE_REPOS and rel == "tools/qiven_operator.py"
            if not allowed and repo_name != "qiven-devkit":
                findings.append(f"R5 {repo_name}/{rel}: vendored operator copy "
                                "(outside the documented instances)")
        # R1 launcher class: batch transport wrappers carrying the retired
        # env-var/sibling-fallback resolution (the 2026-09-28 v44 finding:
        # a deploy.cmd resolved devkit via QIVEN_DEVKIT_ROOT with no
        # identity-check). rem/:: comments are documentation, not patterns;
        # the documented thin-launcher exception (qiven.cmd) is honored.
        if lowered.endswith(LAUNCHER_SUFFIXES):
            if rel in PATH_EXCEPTIONS:
                pass
            else:
                functional = strip_batch_comments(text)
                for match in CMAKE_ENV_VARS.finditer(functional):
                    findings.append(f"R1 {repo_name}/{rel}: launcher env var {match.group(0)}")
                for match in BATCH_SIBLING_PATH.finditer(functional):
                    findings.append(f"R1 {repo_name}/{rel}: launcher sibling path {match.group(0)}")
        # R6: process-global handler-install vocabulary in the two
        # I0-census-declared gap trees (vendored sqlite3 + linked
        # context-draft); any site outside the admitted map fails typed.
        if repo_name in HANDLER_REPOS and lowered.endswith(CPP_SUFFIXES):
            if rel not in HANDLER_ADMITTED.get(repo_name, set()):
                match = HANDLER_INSTALL.search(text)
                if match:
                    token = match.group(0).strip()
                    findings.append(f"R6 {repo_name}/{rel}: process-global handler "
                                    f"install vocabulary ({token}) outside the "
                                    f"admitted map")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="routine-advance forbidden resolver-pattern gate")
    parser.add_argument("--workspace-root", default=str(Path(__file__).resolve().parent.parent.parent))
    parser.add_argument("--repo", action="append",
                        help="scan a single repository root instead of the workspace siblings")
    args = parser.parse_args(argv)

    targets: list[tuple[Path, str]] = []
    if args.repo:
        for repo in args.repo:
            path = Path(repo).resolve()
            targets.append((path, path.name))
    else:
        root = Path(args.workspace_root).resolve()
        for name in SCANNED_REPOS:
            path = root / name
            if path.is_dir():
                targets.append((path, name))

    findings: list[str] = []
    for path, name in targets:
        scan_repo(path, name, findings)

    if findings:
        for finding in findings:
            print(f"[FAIL] {finding}")
        print(f"[FAIL] forbidden resolver patterns: {len(findings)} finding(s) - rule "
              "letter + repo-relative site on every line above; taxonomy R1-R6: this "
              "file's docstring (ADR-0052 doc 02 WR-8)")
        print("[FAIL] forbidden resolver patterns: NEXT: FIX - remove the forbidden "
              "pattern at each listed site (restore the workspace-lock resolution "
              "path; the narrowly documented exceptions are in the docstring), then "
              "re-run: python tools/check_resolver_patterns.py")
        return 1
    print(f"[ OK ] resolver patterns clean ({len(targets)} repos scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
