from __future__ import annotations

"""Scaffold a new Devkit-managed C++ library repository.

Was tools/new-cpp-library.cmd. usage:
  new_cpp_library.py DEST REPOSITORY PROJECT TARGET ALIAS NAMESPACE TEST_OPTION [SOLUTION]
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from toolchain import resolve

USAGE = ("usage: new_cpp_library.py DEST REPOSITORY PROJECT TARGET ALIAS "
         "NAMESPACE TEST_OPTION [SOLUTION]")


def usage_failure(argv: list[str]) -> int:
    # B7a four-element carrier for the usage rejection (register row
    # devkit-tool-new-cpp-library): what + why + evidence + the FIX route.
    print(f"[FAIL] new_cpp_library.py: usage rejected - {USAGE}")
    print("  why: the positional contract is fixed (DEST REPOSITORY PROJECT TARGET "
          "ALIAS NAMESPACE TEST_OPTION [SOLUTION] [TEMPLATE]; docs/conventions/"
          "cross-repo-cmake.md)")
    print(f"  evidence: got {len(argv)} argument(s): {argv}")
    print("  NEXT: FIX - re-run with the documented argument order; the generated "
          "repository then needs git init + a baseline commit before adoption-era "
          "syncs")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) < 7:
        return usage_failure(argv)
    keys = ("DESTINATION", "REPOSITORY_NAME", "CMAKE_PROJECT_NAME", "CMAKE_TARGET_NAME",
            "CMAKE_ALIAS", "CPP_NAMESPACE", "TEST_OPTION_NAME")
    values = dict(zip(keys, argv[:7]))
    values["VS_SOLUTION_NAME"] = argv[7] if len(argv) > 7 else argv[1]
    values["TEMPLATE"] = argv[8] if len(argv) > 8 else "cpp-library"
    devkit = Path(__file__).resolve().parent.parent
    command = [resolve()["cmake"], f"-DDEVKIT_ROOT={devkit}"]
    command += [f"-D{key}={value}" for key, value in values.items()]
    command += ["-P", str(devkit / "cmake" / "QivenRepoNew.cmake")]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
