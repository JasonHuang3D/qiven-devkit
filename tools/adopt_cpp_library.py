from __future__ import annotations

"""Adopt an existing C++ repository into Devkit management.

Was tools/adopt-cpp-library.cmd. MODE is case-sensitive: check | apply.
usage:
  adopt_cpp_library.py MODE REPOSITORY REPOSITORY_NAME PROJECT TARGET ALIAS NAMESPACE TEST_OPTION [SOLUTION]
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from toolchain import resolve

USAGE = ("usage: adopt_cpp_library.py MODE REPOSITORY REPOSITORY_NAME PROJECT TARGET "
         "ALIAS NAMESPACE TEST_OPTION [SOLUTION]; MODE must be exactly check or apply")


def usage_failure(argv: list[str]) -> int:
    # B7a four-element carrier for the usage/mode rejection (register row
    # devkit-tool-adopt-cpp-library): what + why + evidence + the FIX route.
    print(f"[FAIL] adopt_cpp_library.py: usage rejected - {USAGE}")
    why = ("MODE is case-sensitive and must be exactly 'check' or 'apply'"
           if argv and argv[0] not in ("check", "apply")
           else "the positional contract is fixed (8 required arguments)")
    print(f"  why: {why} (docs/conventions/cross-repo-cmake.md)")
    print(f"  evidence: got {len(argv)} argument(s): {argv}")
    print("  NEXT: FIX - re-run with MODE check first (read-only plan), then MODE "
          "apply to materialize the adoption")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 8 or argv[0] not in ("check", "apply"):
        return usage_failure(argv)
    mode = argv[0]
    keys = ("REPOSITORY", "REPOSITORY_NAME", "CMAKE_PROJECT_NAME", "CMAKE_TARGET_NAME",
            "CMAKE_ALIAS", "CPP_NAMESPACE", "TEST_OPTION_NAME")
    values = dict(zip(keys, argv[1:8]))
    values["VS_SOLUTION_NAME"] = argv[8] if len(argv) > 8 else argv[2]
    devkit = Path(__file__).resolve().parent.parent
    command = [resolve()["cmake"], f"-DDEVKIT_ROOT={devkit}", f"-DMODE={mode}"]
    command += [f"-D{key}={value}" for key, value in values.items()]
    command += ["-P", str(devkit / "cmake" / "QivenRepoAdopt.cmake")]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
