from __future__ import annotations

"""WR-6 launcher (ADR-0052 doc 02 stage WR-6): this repository's operator
entry invokes the WORKSPACE BOOTSTRAP identity-check BEFORE any Devkit
code is imported - a wrong local Devkit revision (or an unreadable
workspace lock) fails typed here, before operator execution. The
launcher identifies the repository (QIVEN_TARGET_ROOT) and the control
checkout (QIVEN_WORKSPACE_CONTROL or the sibling control locator); it
contains NO Devkit path fallback and NO consumer-local Devkit pin, and
the vendored operator copy is retired (the lock's qiven-devkit node is
the single implementation - template drift can no longer silently
select an older one)."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

TARGET_ROOT = Path(__file__).resolve().parents[1]
DEVKIT_CHECKOUT = Path(os.environ.get("QIVEN_DEVKIT_CHECKOUT", TARGET_ROOT.parent / "qiven-devkit"))


def _bootstrap_identity() -> None:
    control = Path(os.environ.get("QIVEN_WORKSPACE_CONTROL",
                                  TARGET_ROOT.parent / "qiven-workspace")).resolve()
    bootstrap = control / "bootstrap" / "qiven-bootstrap.py"
    if not bootstrap.is_file():
        raise SystemExit(
            f"[FAIL] workspace bootstrap not found at {bootstrap}; set "
            "QIVEN_WORKSPACE_CONTROL to the control checkout (the Devkit "
            "revision is the lock's qiven-devkit node - WR-6, no local pin)."
        )
    completed = subprocess.run(
        [sys.executable, str(bootstrap), "preflight",
         "--control", str(control), "--devkit", str(DEVKIT_CHECKOUT)],
        capture_output=True, text=True, timeout=180,
    )
    if completed.returncode != 0:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(
            "[FAIL] workspace bootstrap rejected the local Devkit (WR-6: "
            "wrong local Devkit revision fails before Operator code executes)"
        )
    try:
        receipt = json.loads(completed.stdout)
        for note in receipt.get("bootstrap_notes", []):
            print(f"[wr6] devkit identity note: {note}", file=sys.stderr)
    except json.JSONDecodeError:
        print("[wr6] preflight receipt unreadable (notes not surfaced)",
              file=sys.stderr)


os.environ["QIVEN_TARGET_ROOT"] = str(TARGET_ROOT)
_bootstrap_identity()
sys.path.insert(0, str(DEVKIT_CHECKOUT / "tools"))
main = importlib.import_module("qiven_operator").main


if __name__ == "__main__":
    raise SystemExit(main())
