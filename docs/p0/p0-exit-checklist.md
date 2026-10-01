# P0 exit checklist — fixture-class coverage, evidence, budgets (ADR-0060 E closeout)

Owner-adjudication INPUT for the P0-complete declaration. Factual
register only: every row names the test that proves it at the heads of
this batch (qiven-devkit + qiven-context, branch
`jason-extended-cognition/v57-p0-e`). No advocacy.

## 1. D15 fixture-class coverage matrix

ADR-0060 D15 names the required P0 fixture classes; this batch (E)
closes the ones earlier batches had not landed. "Earlier" rows name the
existing tests that already cover the class (no new fixture needed).

| # | D15 fixture class | Landed where (test:cases) | Notes |
| --- | --- | --- | --- |
| 1 | Independent invalid fields across files, public constraint/exemplar parity | qiven-context `tools/test.py::ValidatorTests::test_two_schema_errors_yield_two_distinct_findings`, `test_two_views_each_with_a_finding_are_both_reported` | Earlier (P0-A R4 / A2 view aggregation): distinct findings, no first-error masking |
| 2 | Parse-blocked file + unrelated checks | qiven-context `tools/test.py::ValidatorTests::test_missing_front_matter`, `test_bad_jsonl_event` | Earlier: a front-matter/JSONL parse failure is one finding; unrelated checks still run and report |
| 3 | Partial gates | qiven-devkit `tools/operator-test.py` R3.* (`R3.not-run-coverage`, `R3.parallel-not-run-coverage`, `R3.first-fail-all-later-not-run`, ...) | Earlier (P0-A R3): not_run stages reported with reasons, never guessed exit codes |
| 4 | Exit-zero report mode with findings | qiven-context `tools/test_p0_closeout.py` CX2 (+ qiven-devkit `tools/p0_closeout_test.py` EC11) | E: `check_references --report` exits 0 with findings visible and says so; the findings record class is `findings`, never `passed` (D3) |
| 5 | Large/localized/invalid-byte diagnostics (serialized bytes obey limits, useful excerpts retained) | qiven-devkit `tools/operator-test.py` R1.*/R2.* (byte budgets, CJK boundaries, excerpts); E: `tools/p0_closeout_test.py` EC1/EC2, qiven-context `tools/test_p0_closeout.py` CX1 | E closes invalid-UTF-8: raw bytes retained byte-exact, replacement-char bounded render, honest record (digest/byte-count/completeness), recovery via `evidence-read` |
| 6 | Artifact write/read/expiry errors | qiven-devkit `tools/operator-test.py` EVR.* (byte range, cursor, cap, typed missing/traversal/outside) + R2 copy-failure degradation; E: `tools/p0_closeout_test.py` EC8 (`.expired` marker: typed expired error naming the original locator; bytes win when both exist), EC9 (unreadable, directory) | E adds the minimal honest expiry-marker contract (D6) |
| 7 | Unknown running operations | qiven-devkit `tools/p0_closeout_test.py` EC10 | E: unknown exec id -> typed CLI answer (exit 2) + one record with completion=unknown, observation=unavailable, FIX naming `qiven exec list` |
| 8 | Malformed bootstrap receipts | qiven-context `tools/test.py::LauncherReceiptTests::test_unreadable_receipt_refuses_operator_import`, `test_nondict_receipt_refuses_operator_import` | Earlier (P0-A R6b); workspace B-suite validates embedded records |
| 9 | Useful success/status data | qiven-devkit `tools/operator-test.py` G1.info-status/info-head/json-purity, G2l.list-visible, C9/C10 (custody identity + heartbeat freshness) | Earlier: status retains requested data, never content-free PASS |
| 10 | Known grep/head/tail projections retaining class/action/reference | E: qiven-devkit `tools/p0_closeout_test.py` EC3 (gate human summary), EC4 (record projection view); qiven-context `tools/test_p0_closeout.py` CX3 (validator report summary line; selector retention asserted) | E producer fix: the gate FAIL/PASS human summary is ONE line carrying class + action + reference; projection line 1 + footer carry verdict/next/locator; post-E follow-up producer fix: the context validator's stdout summary line carries class + action + reference as BOTH first and last line (CX3/CX4) |
| 11 | Router carrier, raw Bash, custody, proof, public JSON under named profiles | qiven-devkit `tools/hook_exec_router_test.py` (classification + carriers), `tools/router_record_adapter_test.py` RA/RB (denial carrier byte-stability, profile router-denial-legacy-v1); `tools/operator-test.py` G2/G3 (custody laws C1-C10); E: `tools/p0_closeout_test.py` EC5 (raw-Bash passthrough: exit code + verdict line), EC6 (gate_proof: exact head + gate name + digest, fails closed tampered/missing), EC7 (merge_proof receipt row shape: byte-exact publication sample + live receipt); G1 json purity rows (public JSON) | D7: carrier bytes unchanged; adapter is a pure additive view |

## 2. Exit-checklist rows (E-batch scope)

| Row | Requirement | Landed where |
| --- | --- | --- |
| 5 | Invalid-UTF-8 end-to-end through the capture->render seam | EC1 (operator `_run_process` capture: b'\xff\xfe bad' retained raw, bounded replacement render, honest record, evidence-read recovery), EC2 (projection excerpt seam), CX1 (validator file-capture path: typed finding, no traceback) |
| 8 | Known grep/head/tail projections retain class/action/reference | EC3, EC4, CX3, CX4 (+ the summary-line producer fix in `qiven_operator.py` / projection enrichment in `record_projection.py` / validator summary line + guarded non-record reads in qiven-context `tools/validate_context.py`) |
| 10 | Raw-Bash passthrough + gate_proof/merge_proof named profiles | EC5, EC6, EC7 (+ RA/RB carrier suite) |

## 3. Coverage / evidence / budget statement

- **Coverage**: every entry of `qiven-context runtime/p0-producer-inventory.yaml`
  (47 producers) carries an explicit `emits_common_record` key: `v1` for
  the three emitting producers (devkit-qiven-operator, ctx-validator,
  workspace-bootstrap-preflight), `planned` for the remaining 44 due in
  later program phases; excluded borderline surfaces are `not-planned`
  (outside P0 per D2).
- **Evidence**: records at `.generated-temp/operator/records/`
  (<gate>-<head>-<opid>.json, exec-* and context-validation-*), gate
  PASS receipts at `.generated-temp/operator/receipts/<gate>-<head>.json`,
  retained task evidence under `<OS temp>/qiven-operator/` (readable via
  `qiven evidence-read`), expiry via `.expired` sibling markers.
- **Budgets** (frozen constants, `tools/common_record.py`):
  MODEL_VIEW_MAX_BYTES 8192, CONTROL_IDENTITY_MAX_BYTES 2048,
  INLINE_FINDINGS_MAX 8, BOUNDED_READ_MAX_BYTES 16384 — enforced on the
  EXACT serialized bytes by `tools/record_projection_test.py` (PJ1-PJ12)
  and the excerpt laws of `tools/operator-test.py` (R1/R2: head+tail+
  omitted == total, byte- not char-budgets, CJK boundary exactness).
- **Cross-repo conformance**: qiven-devkit
  `tools/context_records_crosscheck_test.py` — byte-exact checked-in
  samples (XC1) + live builder leg (XC2) validate the context
  validator's emitted records against the FROZEN
  `common_record.validate`/`read`/`serialize` (mirror-drift closure).
- **Ordinary-transaction observation** (the "observe remaining cost in
  ordinary transactions" step): three real transactions driven through
  the devkit checkout at the batch head; summary at
  `.generated-temp/p0-observation/p0-e-observation.md` (evidence
  capture in the gitignored area, not a commit).

## 4. Honest residual list (known, documented, not closed by P0-E)

1. Router deliberate-evasion class: unparseable hook input fails OPEN
   (documented backstop limit; register: devkit-hook-exec-router).
2. Serialize dict-reorder: `common_record.serialize` canonicalizes key
   order (sort_keys) — producer construction order is not preserved in
   bytes; determinism is per byte-identical input (documented choice).
3. CV in-repo mirror law: the context suite's structural mirror
   (`tools/test_common_records.py`) is context-local law, not the frozen
   devkit validator; narrowed by XC1/XC2, not replaced.
4. ~~Validator summary line carries class only~~ CLOSED post-E by the
   producer fix in qiven-context `tools/validate_context.py`: the stdout
   summary line now carries class + action + reference as BOTH the first
   and last line (fixtures CX3/CX4; the inventory `public_contract` for
   ctx-validator is updated to the enriched shape).
5. ~~Validator unguarded reads~~ CLOSED post-E by the same producer fix:
   the non-record content reads (README, BOOTSTRAP, session checkpoint,
   collaboration contracts, ledger events/README, repositories.yaml) go
   through a decode-guarded reader — invalid UTF-8 is a typed finding
   naming the file, dependent content checks are skipped for that file
   (D4), never a traceback (fixture CX4).
6. `check_references` (the exit-zero report surface) does not yet emit
   Common Records (`planned` in the inventory).
7. `qiven run` emits no Common Record (gate/exec/status emit; observed
   truthfully in the E observation, not claimed otherwise).
8. PASSED/FINDINGS/UNKNOWN-class projections carry no `FAIL`/`OK`
   token: a case-sensitive `grep -E "FAIL|OK"` misses them (documented
   selector limit; compensating carrier: the operator `[ OK ]` summary
   line of the same transaction).
9. `head`-of-output on a streaming gate shows progress lines
   (`[ RUN]`/`[WAIT]`), never the verdict (progress-first contract; the
   one-line verdict summary at the end is the carrier).
10. XC2's live cross-repo leg SKIPs visibly when the sibling
    qiven-context checkout/.venv is absent (hermetic fallback: XC1
    byte-exact samples).

## 5. Suites at the batch heads

| Repo | Command | Result |
| --- | --- | --- |
| qiven-devkit | `python tools/common_record_test.py` | CR1-CR10 OK |
| qiven-devkit | `python tools/record_projection_test.py` | PJ1-PJ12 OK |
| qiven-devkit | `python tools/router_record_adapter_test.py` | RA/RB OK |
| qiven-devkit | `python tools/p0_closeout_test.py` | EC1-EC11 OK (73 named checks) |
| qiven-devkit | `python tools/context_records_crosscheck_test.py` | XC1 + live XC2 OK |
| qiven-devkit | `python tools/operator-test.py` | G1-G4/G2/G3 + R1-R3 + EVR + ER1-ER4 OK (140 named checks) |
| qiven-context | `./.venv/Scripts/python.exe tools/test_all.py` | all groups OK (incl. the p0-closeout suite CX1-CX4) |

Gate registration: devkit gate `local` runs `p0-closeout-tests` and
`context-records-crosscheck-tests` (`.qiven/operator.json`); context
gate `context-tools` runs the `p0-closeout` suite via
`tools/test_all.py --group tools` (`tools/test_all_impl.py` SUITES).
