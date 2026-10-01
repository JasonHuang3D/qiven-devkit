"""Router denial -> Common Record v1 adapter (ADR-0060 B+D batch, D7).

A PURE function mapping one ADR-0051 router denial to a Common Record:
admission rejected (the router's judgment is a coherent, mechanically
known policy/invocation rejection - never an uncertainty), completion
not_started (the denied command never executed), domain outcome
not_applicable, and next_action FIX whose supported_by IS the denial's
own re-call instruction (the carrier already teaches the exact lawful
next call; the adapter derives from it, it never rewrites it).

CARRIER LAW (ADR-0051 / ADR-0060 D7, normative): the denial output bytes
of tools/hook_exec_router.py are the named legacy profile
router-denial-legacy-v1 and stay BYTE-STABLE until an explicit
public-carrier amendment. This module therefore imports NOTHING from the
router and is wired NOWHERE by default - the adapter is a derivable,
tested view (``denial_to_record(command, denial_text)``), not a routing
stage. Byte-stability is proven by router_record_adapter_test.py against
the actual verdict() outputs with this module imported.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any

import common_record as cr

#: The router's named legacy carrier profile (ADR-0060 D7 declaration in
#: qiven-context runtime/p0-producer-inventory.yaml).
ROUTER_PROFILE = "router-denial-legacy-v1"

#: supported_by byte budget: the denial's own re-call instruction body,
#: bounded on the UTF-8 serialization (character-boundary clip).
SUPPORTED_BY_MAX_BYTES = 1200

#: Lines that are panic-guard framing, not the instruction itself (the
#' 别慌张' guard line precedes the teaching by design).
_GUARD_MARKERS = ("别慌张",)


def _operation_id() -> str:
    """Collision-resistant operation id (D6: stamp + pid + random)."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{os.getpid():08d}-{os.urandom(3).hex()}"


def _instruction_from(denial_text: str) -> str:
    """The denial's own re-call instruction: the full carrier minus the
    panic-guard framing lines, byte-bounded on a character boundary."""
    kept = [
        line
        for line in denial_text.splitlines()
        if line.strip() and not any(marker in line for marker in _GUARD_MARKERS)
    ]
    body = "\n".join(kept)
    encoded = body.encode("utf-8")
    if len(encoded) <= SUPPORTED_BY_MAX_BYTES:
        return body
    return encoded[: SUPPORTED_BY_MAX_BYTES - 3].decode("utf-8", errors="ignore") + "..."


def denial_to_record(command: str, denial_text: str) -> dict[str, Any]:
    """Map one router denial to a Common Record v1 document (dict).

    Pure: reads only its two arguments; never imports or invokes the
    router; never writes anything. The returned document is a plain dict
    in the envelope's canonical shape (validates against
    qiven-common-record-v1 via common_record.validate).
    """
    supported_by = _instruction_from(denial_text)
    finding = {
        "rule_id": "router/admission-denied",
        "location": {"path": "hook_exec_router.py verdict()"},
        "actual": "command denied by the hook router (carrier: "
                  f"{ROUTER_PROFILE})",
        "expected": "re-call per the denial instruction (the carrier "
                    "teaches the exact lawful next call)",
        "contract_revision": ROUTER_PROFILE,
    }
    return {
        "schema_version": cr.SCHEMA_VERSION,
        "record_kind": "router-denial",
        "producer": {"id": "devkit-hook-exec-router", "version": ROUTER_PROFILE},
        "operation": {
            "id": _operation_id(),
            "invocation": command,
        },
        "observation": {
            "coherence": "coherent",
            "transport_classification": "PreToolUse hook exit 2 (denial)",
        },
        "admission": {
            "state": "rejected",
            "reason": "hook router policy/invocation class (coherent judgment)",
        },
        "completion": {"state": "not_started"},
        "domain_outcome": {"outcome": "not_applicable", "exit_code": cr.UNAVAILABLE},
        "coverage": {"collection": "complete", "executed": ["classify", "verdict"]},
        "findings": [finding],
        "next_action": asdict(cr.next_action_for("policy-rejected", supported_by)),
        "evidence": [
            {
                "locator": "hook stderr (session transcript)",
                "excerpt": denial_text,
                "layout": "stderr",
                "completeness": "complete",
            }
        ],
        "retry_state": {"side_effects": "not_started"},
        "payload": {
            "kind": "router-denial-stderr",
            "locator": f"[qiven-hook] carrier ({ROUTER_PROFILE})",
        },
    }
