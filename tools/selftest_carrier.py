from __future__ import annotations

"""Four-element FAIL carrier rendering for devkit self-test scripts (B7a).

A self-test's failure is itself a producer surface (register rows
devkit-task-*-tests): the FAIL carrier must carry WHAT happened (the
case id + detail), WHY it violates (the case text names the violated
law; the case registry is the script's own docstring/case table), useful
evidence (the verbatim traceback - and, when the script runs as a
`qiven run` task, the operator wrapper retains the complete captured
output as a durable artifact), and a mechanical NEXT action
(ADR-0060 D3; budgets 8192/2048/8/16384 on the serialized result).

Wiring law: a script replaces its `raise SystemExit(main())` tail with
`raise SystemExit(run(__file__, main))`. The exit contract is unchanged
(0 pass / 1 assertion failure); the traceback prints VERBATIM first
(evidence law - failure text is never rewritten), and the actionable
summary is the LAST thing on the stream (the operator's excerpt keeps
head/tail; recency law, B1).
"""

import sys
import traceback
from pathlib import Path
from typing import Callable

# Bounded WHAT excerpt: the assertion text can be long (dict reprs); the
# full text already lives in the traceback above, so the summary line
# carries a UTF-8-safe prefix.
WHAT_PREFIX_BYTES = 240


def _bounded(text: str, budget: int) -> str:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= budget:
        return text
    return raw[:budget].decode("utf-8", errors="replace").rstrip() + " [...]"


def render_failure(script: Path, exc: BaseException,
                   file_handle=None) -> None:
    """Emit the four-element summary for a failed self-test assertion.
    The traceback itself must already have been printed (evidence law).
    file_handle=None lets print() resolve the CURRENT sys.stdout at call
    time (a bound default would freeze the import-time stream and break
    under redirect_stdout in-process drivers)."""
    name = script.name
    message = str(exc)
    what = _bounded(message or exc.__class__.__name__, WHAT_PREFIX_BYTES)
    print(f"[FAIL] {name}: self-test case failed - {what}", file=file_handle)
    if not message.strip():
        # carrier-law guard: a message-less assert cannot carry the WHY;
        # the case itself is defective alongside whatever it caught
        print(f"  why-gap: the assert carried no message - every case MUST "
              f"name its law in the assertion (fix the case while fixing the "
              f"failure)", file=file_handle)
    print(f"  why: the case text names the violated law; case registry: "
          f"tools/{name} (docstring + the case id sites)", file=file_handle)
    print("  evidence: complete traceback above; when this runs as a "
          "`qiven run` task the operator retains the full captured output "
          "(evidence locator on the run FAIL summary line)", file=file_handle)
    print(f"  NEXT: DIAGNOSE - re-run `python tools/{name}`; fix the "
          "machinery the failed case names; never weaken, skip or split "
          "the case to keep moving", file=file_handle)


def run(script_path: str, main_fn: Callable[[], int]) -> int:
    """Self-test entry choke point: pass through success, render the
    four-element FAIL carrier for an assertion failure (exit 1)."""
    script = Path(script_path)
    try:
        return main_fn()
    except AssertionError:
        # same stream as the summary below: the operator task capture
        # merges stdout+stderr, so one stream keeps the order verbatim
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        render_failure(script, sys.exc_info()[1])
        return 1
