#!/usr/bin/env python
"""Attribution subject-position lint (pit P-51; A1 in the activation inventory).

The accepted commit-identity convention places the role/LLM attribution
block in the TRAILER position, after the conventional subject; a subject
line beginning with "role:" renders every commit listing as the role line
instead of the engineering summary. That defect was published twice
(2026-09-19: fourteen commits; 2026-09-20: eighteen commits across five
repositories; MEM-20260919T135930Z-F1C2A9, MEM-20260920T100100Z-A7D3E9),
each time requiring an owner-directed history rewrite. This lint makes the
third occurrence a gate failure instead.

Checks every commit reachable from HEAD (a full-history scan is cheap at
Qiven repository sizes and catches reintroductions anywhere in ancestry).
Pre-convention commits without attribution trailers pass by construction:
the lint only fails on the role-FIRST layout.

Usage:
    python tools/check_commit_subjects.py          # scan HEAD ancestry
    python tools/check_commit_subjects.py --selftest
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "role:"


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def scan(repo: Path) -> list[str]:
    # HEAD ancestry only: preserved evidence branches (pre-rewrite history)
    # are lawful to keep; the gate governs what this repository publishes.
    out = run_git(repo, "log", "--pretty=format:%H%x00%s%x00%b")
    offenders = []
    for record in out.split("\n"):
        if not record:
            continue
        _sha, subject, _body = (record.split("\x00") + ["", ""])[:3]
        if subject.startswith(MARKER):
            offenders.append(f"{subject[:80]}")
    return offenders


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "r"
        repo.mkdir()
        run_git(repo, "init", "-q", "--initial-branch=main")
        run_git(repo, "config", "user.email", "t@example.com")
        run_git(repo, "config", "user.name", "t")

        def commit(message: str) -> None:
            (repo / "f.txt").write_text(message, encoding="utf-8")
            run_git(repo, "add", "-A")
            run_git(repo, "commit", "-q", "-m", message)

        commit("feat(x): good subject\n\nbody\n\nrole: jason-worker\nLLM: m  reasoning high")
        assert scan(repo) == [], "clean commit wrongly flagged"

        commit("role: jason-worker\nLLM: m  reasoning high\n\nfeat(x): regressed layout")
        offenders = scan(repo)
        assert len(offenders) == 1 and offenders[0].startswith("role:"), offenders

        # merge-style message with attribution header (the 2026-09-20 shape)
        commit("role: jason-extended-cognition\nLLM: m\n\nmerge(x): y\n\nH2: owner")
        assert len(scan(repo)) == 2
    print("[ OK ] check_commit_subjects selftest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    repo = Path(__file__).resolve().parents[1]
    offenders = scan(repo)
    if offenders:
        print(f"[FAIL] {len(offenders)} commit subject(s) start with 'role:' "
              "(attribution block must be the trailer, not the subject):")
        for line in offenders:
            print(f"  {line}")
        return 1
    print("[ OK ] commit subjects clean (attribution in trailer position)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
