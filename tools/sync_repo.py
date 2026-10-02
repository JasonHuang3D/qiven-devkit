from __future__ import annotations

"""Roll the Devkit-managed file set into a managed repository.

Was tools/sync-repo.cmd. usage: sync_repo.py REPOSITORY
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from toolchain import resolve


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        # B7a four-element carrier (register row devkit-tool-sync-repo)
        print("[FAIL] sync_repo.py: usage rejected - usage: sync_repo.py REPOSITORY")
        print("  why: exactly one argument - the root path of a qiven-managed "
              "repository (docs/conventions/cross-repo-cmake.md)")
        print(f"  evidence: got {len(argv)} argument(s): {argv}")
        print("  NEXT: FIX - re-run as: python tools/sync_repo.py <repository-root>")
        return 2
    devkit = Path(__file__).resolve().parent.parent
    command = [resolve()["cmake"], f"-DDEVKIT_ROOT={devkit}",
               f"-DREPOSITORY={Path(argv[0]).resolve()}",
               "-P", str(devkit / "cmake" / "QivenRepoSync.cmake")]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
