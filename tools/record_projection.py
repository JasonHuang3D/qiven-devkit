"""Bounded model-view projection for Common Record v1 (ADR-0060 D3; the
B+D semantics + projection batch, 2026-10-02).

``project(record) -> str`` renders the unified bounded model view: the
versioned record projected over the ten D3 dimensions as ASCII-safe
control-syntax lines (localized content stays literal inside values).
``project_json(record) -> dict`` is the machine variant carrying the same
view plus the exact byte/counter accounting.

Budget law (D3, quoted; enforced here on the EXACT serialized projection,
never loose character counts):

    entire serialized model-visible result 8 KiB UTF-8;
    control/identity/locator portion <= 2 KiB within it;
    <= 8 inline findings (also byte-budget bound);
    explicit bounded evidence read <= 16 KiB with cursor/range and EOF.

Assembly order honors "reserve actionable control + evidence locator
FIRST": the control block (identity, admission/completion/outcome,
coverage counts, next action, primary evidence locator) is rendered
first and never dropped; findings follow (sorted deterministically by
(rule, location), which the record already guarantees); the bounded
evidence excerpt takes the remaining budget; the footer repeats a small
bounded locator (a large projection may repeat a small bounded
header/footer locator) and reports returned/total/omitted counts
(complete) or discovered + blocked/unexecuted (partial).

Purity: projection is a VIEW - the input record (dataclass or dict) is
deep-copied before any normalization and never mutated.
"""

from __future__ import annotations

import copy
from typing import Any

import common_record as cr


def _flatten(text: Any) -> str:
    """One single-line value: str() with newlines flattened to spaces."""
    if text is None:
        return "-"
    return str(text).replace("\r", " ").replace("\n", " ").strip() or "-"


def _clip(text: str, budget: int) -> str:
    """Longest character-boundary prefix of ``text`` fitting ``budget``
    UTF-8 bytes; longer values end with an ASCII '...' marker."""
    if budget <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    return encoded[: max(0, budget - 3)].decode("utf-8", errors="ignore") + "..."


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


# --- control block ----------------------------------------------------------

_DEF = "-"


def _render_control(doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(control text, control counters). Self-bounded to
    CONTROL_IDENTITY_MAX_BYTES by iteratively clipping value budgets -
    identity fields can carry long invocations/paths; the control block
    is reserved FIRST and must always fit."""
    op = doc.get("operation") or {}
    producer = doc.get("producer") or {}
    observation = doc.get("observation") or {}
    admission = doc.get("admission") or {}
    completion = doc.get("completion") or {}
    outcome = doc.get("domain_outcome") or {}
    coverage = doc.get("coverage") or {}
    next_action = doc.get("next_action") or {}
    evidence = doc["evidence"][0] if doc.get("evidence") else {}

    executed = coverage.get("executed") or []
    blocked = coverage.get("blocked") or []
    not_executed = coverage.get("not_executed") or []
    coverage_value = (
        f"{coverage.get('collection', _DEF)} exec={len(executed)}"
        f" blocked={len(blocked)} not_exec={len(not_executed)}"
    )
    if coverage.get("collection") != "complete" and (blocked or not_executed):
        names = [str(item.get("name", "?")) for item in (blocked + not_executed)[:4]]
        coverage_value += " blocked/unexec: " + ",".join(names)

    digest = evidence.get("digest")
    evidence_value = " ".join(
        part
        for part in (
            _flatten(evidence.get("locator")) if evidence.get("locator") else None,
            f"[{evidence.get('completeness', _DEF)}]",
            f"{evidence.get('byte_count')}B" if evidence.get("byte_count") is not None else None,
            str(digest)[:19] if digest else None,
        )
        if part
    ) or _DEF

    next_value = _flatten(next_action.get("action", _DEF))
    if next_action.get("supported_by"):
        next_value += " | " + _flatten(next_action["supported_by"])

    value_budget = 240
    while True:
        # line 1 is the selector summary (ADR-0060 D3/E closeout): the
        # known grep/head/tail fragments of this view must still expose
        # class + next action + primary evidence locator. The verdict
        # token is the uppercase outcome enum (FAILED/PASSED/FINDINGS/
        # UNKNOWN/NOT_APPLICABLE); a case-sensitive `grep -E "FAIL|OK"`
        # catches FAILED-class views here, and the operator's `[ OK ]`
        # summary line carries the passing class in the same transaction
        # (PASSED-class projections deliberately carry no FAIL/OK token).
        first_line = (
            f"QIVEN-RECORD v1 verdict={_clip(_flatten(outcome.get('outcome') or 'unknown'), 20).upper()}"
            f" next={_clip(_flatten(next_action.get('action') or '-'), 12)}"
        )
        if evidence.get("locator"):
            first_line += f" evidence={_clip(_flatten(evidence.get('locator')), 120)}"
        lines = [
            first_line + (
                f" kind={_clip(_flatten(doc.get('record_kind')), 60)}"
                f" op={_clip(_flatten(op.get('id')), 80)}"
            ),
            f"producer: {_clip(_flatten(producer.get('id')), 60)}"
            f"@{_clip(_flatten(producer.get('version')), 60)}",
            f"repo: {_clip(_flatten(op.get('repository')), 80)}"
            f" cwd: {_clip(_flatten(op.get('cwd')), value_budget)}",
            f"gate: {_clip(_flatten(op.get('gate')), 60)}"
            f" task: {_clip(_flatten(op.get('task')), 60)}"
            f" invocation: {_clip(_flatten(op.get('invocation')), value_budget)}",
            "head: "
            + _clip(_flatten(op.get("executing_revision") or cr.UNAVAILABLE), 40)
            + " selected: "
            + _clip(_flatten(op.get("selected_revision") or cr.UNAVAILABLE), 40)
            + " gen: "
            + _clip(_flatten(op.get("workspace_generation") or cr.UNAVAILABLE), 71),
            f"observation: {_clip(_flatten(observation.get('coherence')), 20)}"
            f" transport: {_clip(_flatten(observation.get('transport_classification')), value_budget)}",
            f"admission: {_clip(_flatten(admission.get('state')), 20)}"
            f" reason: {_clip(_flatten(admission.get('reason')), value_budget)}",
            f"completion: {_clip(_flatten(completion.get('state')), 30)}",
            f"outcome: {_clip(_flatten(outcome.get('outcome')), 20)}"
            f" exit={_clip(_flatten(outcome.get('exit_code')), 20)}",
            f"coverage: {_clip(coverage_value, value_budget * 2)}",
            f"next: {_clip(next_value, value_budget * 2)}",
            f"evidence: {_clip(evidence_value, value_budget * 2)}",
        ]
        control = "\n".join(lines)
        if _bytes(control) <= cr.CONTROL_IDENTITY_MAX_BYTES or value_budget <= 16:
            break
        value_budget = max(16, value_budget // 2)
    return control, {
        "bytes": _bytes(control),
        "budget": cr.CONTROL_IDENTITY_MAX_BYTES,
    }


# --- findings block ---------------------------------------------------------

_FINDING_PER_VALUE_BYTES = 240
_FOOTER_RESERVE_BYTES = 320


def _render_finding(item: dict[str, Any], index: int, value_budget: int) -> str:
    location = item.get("location") or {}
    loc = _flatten(location.get("path"))
    if location.get("json_pointer"):
        loc += "@" + _flatten(location["json_pointer"])
    if location.get("line"):
        loc += f":{location['line']}"
    actual = _clip(_flatten(item.get("actual")), value_budget)
    expected = _clip(_flatten(item.get("expected")), value_budget)
    return (
        f"[{index}] rule={_clip(_flatten(item.get('rule_id')), 120)}"
        f" loc={_clip(loc, value_budget)}\n"
        f"    actual: {actual} | expected: {expected}"
    )


def _render_findings(
    doc: dict[str, Any], budget: int
) -> tuple[str, dict[str, int]]:
    """(findings text, counts). Sorted (rule, location) order comes from
    the record; at most INLINE_FINDINGS_MAX shown AND byte-bound - the
    last shown finding is dropped first when the budget pinches, moving
    it to the omitted count (never an invented complete count)."""
    findings = list(doc.get("findings") or [])
    total = len(findings)
    if total == 0:
        return "findings: 0", {"returned": 0, "total": 0, "omitted": 0}
    shown = findings[: cr.INLINE_FINDINGS_MAX]
    omitted_seed = total - len(shown)
    while shown:
        header = (
            f"findings: {len(shown)}/{total} shown, "
            f"{total - len(shown)} omitted (order: rule,location)"
        )
        body = "\n".join(
            _render_finding(item, position + 1, _FINDING_PER_VALUE_BYTES)
            for position, item in enumerate(shown)
        )
        block = f"{header}\n{body}"
        if _bytes(block) <= budget:
            return block, {
                "returned": len(shown),
                "total": total,
                "omitted": total - len(shown),
            }
        shown = shown[:-1]
    # budget too small for even one finding: counts still reported
    header = f"findings: 0/{total} shown, {total} omitted (byte budget)"
    return header, {"returned": 0, "total": total, "omitted": total}


# --- evidence excerpt block ---------------------------------------------------

def _excerpt_view(excerpt: str, cap: int) -> tuple[str, int]:
    """(display text, original excerpt bytes covered). When clipped, the
    ASCII '...' marker (and any partial trailing character dropped at the
    byte cut) rides OUTSIDE the covered count, so a continue cursor built
    from the covered count points at the first original byte never shown
    - evidence continuation is lossless, never a silent skip."""
    encoded = excerpt.encode("utf-8")
    if len(encoded) <= cap:
        return excerpt, len(encoded)
    prefix = encoded[: max(0, cap - 3)].decode("utf-8", errors="ignore")
    covered = len(prefix.encode("utf-8"))
    if covered == 0:
        return "", 0
    return prefix + "...", covered


def _render_excerpt(
    doc: dict[str, Any], budget: int
) -> tuple[str, dict[str, Any]]:
    """Bounded excerpt of the first evidence entry that carries one, with
    byte range, EOF marker and a continue cursor naming the bounded read
    route. The excerpt itself is schema-capped at BOUNDED_READ_MAX_BYTES;
    inside the model view it additionally fits the remaining budget."""
    empty = {
        "shown_bytes": 0,
        "excerpt_bytes": 0,
        "eof": None,
        "continue_offset": None,
        "read_command": None,
    }
    if budget <= 0:
        return "", empty
    entry = next(
        (item for item in (doc.get("evidence") or []) if item.get("excerpt")), None
    )
    if entry is None:
        return "", empty
    locator = _flatten(entry.get("locator"))
    excerpt: str = entry["excerpt"]
    excerpt_bytes = _bytes(excerpt)
    cap = min(budget, cr.BOUNDED_READ_MAX_BYTES)
    shown, covered = _excerpt_view(excerpt, cap)
    # the header/footer markers ride INSIDE the budget: shrink the body
    # until the assembled block fits exactly (markers carry the covered
    # count, so a small fixed-point loop converges in a few steps).
    while True:
        eof = covered >= excerpt_bytes
        header = (
            f"--- evidence excerpt bytes=0..{covered}/{excerpt_bytes}"
            f" locator={_clip(locator, 200)} ---"
        )
        if eof:
            footer = "--- EOF (excerpt complete within this view) ---"
            continue_offset = None
            read_command = None
        else:
            continue_offset = covered
            read_command = f"qiven evidence-read {locator} --offset {continue_offset}"
            footer = f"--- more evidence bytes remain; continue: {read_command} ---"
        if _bytes(header) + _bytes(shown) + _bytes(footer) + 2 <= budget or covered == 0:
            break
        excess = (_bytes(header) + _bytes(shown) + _bytes(footer) + 2) - budget
        shown, covered = _excerpt_view(excerpt, max(0, covered - excess))
    block = f"{header}\n{shown}\n{footer}" if shown else ""
    return block, {
        "shown_bytes": covered,
        "excerpt_bytes": excerpt_bytes,
        "eof": eof,
        "continue_offset": continue_offset,
        "read_command": read_command,
    }


# --- footer ------------------------------------------------------------------

def _render_footer(
    locator: str, findings_counts: dict[str, int], evidence_counts: dict[str, Any],
    verdict: str = "UNKNOWN", next_action: str = "-",
) -> str:
    repeat = f" locator={_clip(locator, 160)}" if locator else ""
    evidence_note = (
        f" evidence-view={evidence_counts['shown_bytes']}/{evidence_counts['excerpt_bytes']}B"
        if evidence_counts.get("excerpt_bytes")
        else ""
    )
    # the footer repeats the verdict class AND the next action so
    # tail-only fragments of the view still know pass/fail and what to do
    # next (E closeout selector law; D3 authorizes bounded header/footer
    # repeats of the same record's locator)
    return (
        "== qiven-record end:"
        f" verdict={_clip(_flatten(verdict), 20).upper()}"
        f" next={_clip(_flatten(next_action), 12)}"
        f" findings={findings_counts['returned']}/{findings_counts['total']}"
        f" (omitted {findings_counts['omitted']}){evidence_note}{repeat} =="
    )


# --- public API ---------------------------------------------------------------

def _record_doc(record: cr.CommonRecord | dict[str, Any]) -> dict[str, Any]:
    """Normalized deep copy - the projection never mutates its input."""
    doc = cr._as_record_dict(record)
    return copy.deepcopy(doc)


def project_json(record: cr.CommonRecord | dict[str, Any]) -> dict[str, Any]:
    """Machine variant: the bounded view plus exact accounting."""
    doc = _record_doc(record)
    if isinstance(doc.get("findings"), list):
        doc["findings"] = sorted(doc["findings"], key=cr._finding_sort_key)

    control, control_counts = _render_control(doc)
    primary_locator = _flatten(
        (doc.get("evidence") or [{}])[0].get("locator")
        if doc.get("evidence")
        else ""
    )

    # total budget: control (reserved first) + footer reserve + findings
    # take precedence over the excerpt (diagnostic excerpts use the
    # remaining budget - D3).
    findings_budget = (
        cr.MODEL_VIEW_MAX_BYTES
        - _bytes(control)
        - _FOOTER_RESERVE_BYTES
    )
    findings_block, findings_counts = _render_findings(doc, findings_budget)
    verdict = str((doc.get("domain_outcome") or {}).get("outcome") or "unknown")
    next_word = str((doc.get("next_action") or {}).get("action") or "-")
    footer = _render_footer(
        primary_locator, findings_counts, {"excerpt_bytes": 0, "shown_bytes": 0},
        verdict, next_word,
    )
    excerpt_budget = (
        cr.MODEL_VIEW_MAX_BYTES
        - _bytes(control)
        - _bytes(findings_block)
        - _bytes(footer)
        - 2  # blank separators
    )
    # the final footer carries the evidence-view accounting, so its width
    # grows with the excerpt counts; converge by shrinking the excerpt
    # budget by any excess (footer width is stable within a few passes).
    view = ""
    for _ in range(4):
        excerpt_block, evidence_counts = _render_excerpt(doc, excerpt_budget)
        footer = _render_footer(
            primary_locator, findings_counts, evidence_counts, verdict, next_word
        )
        parts = [part for part in (control, findings_block, excerpt_block, footer) if part]
        view = "\n\n".join(parts) + "\n"
        excess = _bytes(view) - cr.MODEL_VIEW_MAX_BYTES
        if excess <= 0:
            break
        excerpt_budget -= excess
    # final exact-budget guard: by construction the sections fit; if a
    # pathological input still overflows, the excerpt body is the section
    # that yields (its locator already lives in control and footer).
    if _bytes(view) > cr.MODEL_VIEW_MAX_BYTES:
        view = _clip(view, cr.MODEL_VIEW_MAX_BYTES - 1) + "\n"

    return {
        "view": view,
        "model_view_bytes": _bytes(view),
        "model_view_budget": cr.MODEL_VIEW_MAX_BYTES,
        "control": control_counts,
        "findings": findings_counts,
        "evidence": evidence_counts,
        "coverage_collection": (doc.get("coverage") or {}).get("collection"),
        "projection": "qiven-record-model-view-v1",
    }


def project(record: cr.CommonRecord | dict[str, Any]) -> str:
    """The bounded model view (UTF-8 text; ASCII-safe control syntax with
    localized content allowed inside values)."""
    return project_json(record)["view"]
