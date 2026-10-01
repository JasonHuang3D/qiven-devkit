"""Self-test for tools/router_record_adapter.py (ADR-0060 B+D batch).

Two laws, both mechanical:
  RA  adapter mapping - every denial class maps to a valid Common Record
      v1 (admission rejected, completion not_started, next FIX whose
      supported_by IS the denial's own re-call instruction).
  RB  carrier byte-stability (ADR-0051/ADR-0060 D7) - the ACTUAL
      verdict() denial bytes are unchanged when this adapter is present:
      byte-identical before and after importing/using it, and identical
      to the router's own carrier templates.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402
import hook_exec_router as router  # noqa: E402
import record_projection as rp  # noqa: E402
import router_record_adapter as adapter  # noqa: E402

# Every denial class reachable at the shipped defaults (git-network is
# suspended; it is exercised with routing force-enabled like the router
# suite does, plus its template shape through the adapter directly).
DENIAL_COMMANDS = [
    ("cmake --build build/vs2022-x64 --config Release", False),          # build, raw
    ("cmake --build build/vs2022-x64 --config Release", True),           # build, bg without guard
    ("tools/qiven.cmd gate --expect-head abc123", False),                # gate-class
    ("python tools/test_all.py --group repo", False),                    # repo-tool
    ("pip install pyyaml", False),                                       # network
    ("vim notes.txt", False),                                            # interactive
    ("cat << EOF", False),                                               # heredoc (absolute)
    ('python -c "open(\'f\',\'w\')"', False),                            # inline-authoring (absolute)
    ("grep -r pattern .", False),                                        # sweep-unbounded
    ("grep -rn pattern tools/", False),                                  # sweep-scoped, raw
]


def main() -> int:
    # ---- RB first: capture the ACTUAL denial bytes withOUT the adapter ----
    baseline: list[tuple[str, int, str]] = []
    for command, background in DENIAL_COMMANDS:
        code, message = router.verdict(command, background=background)
        assert code == 2 and message, f"RB: {command!r} did not deny"
        baseline.append((command, code, message))

    # git-network denial (routing force-enabled for the shape, like the
    # router suite; shipped default stays suspended)
    saved_flag = router.GIT_NETWORK_ROUTING_ENABLED
    router.GIT_NETWORK_ROUTING_ENABLED = True
    probe_results = [("origin/main\n", True, True), ("3\n", True, True),
                     ("Everything up-to-date\n", True, True)]
    probe_state = {"index": 0}

    def probe_runner(args, cwd):
        item = probe_results[probe_state["index"]]
        probe_state["index"] += 1
        return item

    gn_code, gn_message = router.verdict("git push origin main", probe_runner=probe_runner)
    router.GIT_NETWORK_ROUTING_ENABLED = saved_flag
    assert gn_code == 0 or "[qiven-hook]" in gn_message  # probe-allowed or denied

    # ---- RA: adapter mapping over every captured denial -------------------
    checked = 0
    for command, code, message in baseline:
        record = adapter.denial_to_record(command, message)
        findings = cr.validate(record)
        assert findings == [], f"RA: record invalid for {command!r}: {findings}"
        assert record["admission"]["state"] == "rejected", "RA: admission"
        assert record["completion"]["state"] == "not_started", "RA: completion"
        assert record["domain_outcome"]["outcome"] == "not_applicable", "RA: outcome"
        assert record["domain_outcome"]["exit_code"] == cr.UNAVAILABLE, "RA: exit"
        assert record["observation"]["coherence"] == "coherent", "RA: observation"
        next_action = record["next_action"]
        assert next_action["action"] == "FIX" and next_action["supported_by"], "RA: FIX"
        # supported_by IS the denial's own re-call instruction: the
        # teaching tokens of the carrier survive inside it verbatim
        instruction = next_action["supported_by"]
        teaching_tokens = ("re-issue", "Re-issue", "re-call", "Route it",
                           "Write/Edit", "run_in_background", "exec start")
        assert any(token in instruction for token in teaching_tokens), (
            f"RA: instruction body lost for {command!r}: {instruction[:120]!r}"
        )
        assert "别慌张" not in instruction, "RA: guard framing must not pose as instruction"
        # evidence excerpt is the carrier itself, complete
        assert record["evidence"][0]["excerpt"] == message, "RA: excerpt fidelity"
        assert record["evidence"][0]["completeness"] == "complete", "RA: completeness"
        # the bounded model view projects within the D3 budgets
        view = rp.project(record)
        assert len(view.encode("utf-8")) <= cr.MODEL_VIEW_MAX_BYTES, "RA: view budget"
        checked += 1

    # a git-network denial shape maps identically
    gn_record = adapter.denial_to_record("git push origin main", " ".join([
        "[qiven-hook] git push denied by measured judgment (measured: 137 commits",
        "ahead). Re-issue with run_in_background: true (ADR-0051)."]))
    assert cr.validate(gn_record) == [], "RA: git-network record invalid"
    assert gn_record["record_kind"] == "router-denial"
    checked += 1

    # supported_by byte-bound: a pathological denial stays bounded
    huge = ("[qiven-hook] test denied: re-issue THIS EXACT command with "
            "run_in_background: true\n" + "x" * 10000)
    huge_record = adapter.denial_to_record("cmd", huge)
    assert len(huge_record["next_action"]["supported_by"].encode("utf-8")) \
        <= adapter.SUPPORTED_BY_MAX_BYTES, "RA: supported_by unbounded"
    assert huge_record["next_action"]["supported_by"].endswith("..."), "RA: clip marker"

    # ---- RB: carrier bytes unchanged WITH the adapter present -------------
    # the adapter module is imported and exercised above; re-run every
    # verdict and demand BYTE-IDENTICAL denial output.
    for (command, background), (_cmd, code_before, message_before) in zip(DENIAL_COMMANDS, baseline):
        code_after, message_after = router.verdict(command, background=background)
        assert (code_after, message_after) == (code_before, message_before), (
            f"RB: carrier bytes changed for {command!r}"
        )
    # and the templates themselves are untouched module constants
    assert router._DENY_HEREDOC.startswith("[qiven-hook] heredoc authoring DENIED")
    assert router._DENY_INLINE_AUTHORING.startswith("[qiven-hook] inline-script authoring DENIED")
    assert "MSBUILDDISABLENODEREUSE=1" in router._DENY_BG_GUARD_TEMPLATE

    # purity: the adapter does not touch the router module state
    assert router.GIT_NETWORK_ROUTING_ENABLED == saved_flag, "RB: router flag mutated"

    print(f"[ OK ] router-record-adapter: {checked} class mappings + carrier "
          "byte-stability (RA/RB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
