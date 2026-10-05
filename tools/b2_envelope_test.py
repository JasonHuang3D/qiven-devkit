"""B2 envelope fixture suite (ADR-0060 D3; P0 repair batch B2, 2026-10-02).

Covers the B2 four-element carrier upgrades (register rows
devkit-resolver-* all 7 subcommands, workspace-bootstrap-gate-configure,
workspace-launcher-qiven-cmd; structural gaps SG-3 + SG-4):
  b2-1..2    resolver typed error envelopes carry next_action (FIX with
             supported_by naming the exact flag; human-mode NEXT line)
  b2-3..5    success receipts carry honest NONE; git-environment
             failures DIAGNOSE with supported_by absent
  b2-6       lock-update receipts mechanize the transaction law (NEXT ->
             --apply -> NEXT commit the control repository)
  b2-7..8    candidate failures FIX / validated NONE; adapter NEXT names
             the QIVEN_RESOLUTION_FILE configure binding
  b2-9       golden-vectors FAIL carries the FIX route; OK carries NONE
  b2-10      law pin: every ResolutionError kind has a class assignment
             (table entry or per-site override); FIX/NEXT entries carry
             supported_by, DIAGNOSE entries never do
  b2-11..13  gate-configure return-1 paths emit the SAME typed envelope
             + record machinery as preflight (AdapterFailed DIAGNOSE,
             GenerationMismatch FIX naming lock-update,
             ConfigureFailed DIAGNOSE), gate producer identity, pinned
             banner bytes intact (B11-B13 behavioral pins live in
             workspace_bootstrap_test)
  b2-17..19  preflight child-interaction return-1 paths carry the typed
             envelope too (PreflightFailed DIAGNOSE, PreflightNoReceipt
             DIAGNOSE, PreflightGenerationMismatch FIX naming
             lock-update) with the compliant v1 preflight producer
             identity and pinned stderr banner bytes intact
  b2-14      preflight records keep the compliant v1 shape (producer
             discrimination against gate records)
  b2-15      workspace qiven.cmd: typed interpreter-failure carriers
             (exit 2) + verbatim argv/exit-code forwarding
  b2-16      byte-stability structural pins on the real bootstrap source

Cross-repo legs (b2-11..16) SKIP visibly when the real qiven-workspace
sibling is absent (same honesty law as workspace_bootstrap_test).

Each case id rides in the assertion message. Disposable temp fixtures
only (testing law: tests never touch developer repositories; the
lock-update --apply leg writes a TEMP fixture control, never the real
workspace lock).
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common_record as cr  # noqa: E402
import workspace_bootstrap_test as wbt  # noqa: E402
import workspace_resolver as wr  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tools" / "workspace_resolver.py"
CHECKS = 0

WORKSPACE_ROOT = ROOT.parent / "qiven-workspace"
BOOTSTRAP = wbt.BOOTSTRAP
WORKSPACE_CMD = WORKSPACE_ROOT / "qiven.cmd"


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AssertionError(f"fixture git {args}: {result.stderr}")
    return result.stdout.strip()


def _envelope(stdout: str) -> dict:
    at = stdout.find('{\n  "schema"')
    if at < 0:
        at = stdout.find('{"schema"')
    check(at >= 0, "b2.envelope-present", stdout[:300])
    return json.loads(stdout[at:])


def resolver_cli(*args: str,
                 env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(RESOLVER), *args]
    full_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env is not None:
        full_env.update(env)
    return subprocess.run(argv, capture_output=True, text=True, timeout=180,
                          encoding="utf-8", errors="replace", env=full_env)


def resolver_legs(temp: Path) -> None:
    control, devkit, lock = wbt._fixture(temp / "w")
    control = control.resolve()
    devkit = devkit.resolve()

    # b2-1: typed error envelope carries next_action FIX + exact flag
    done = resolver_cli("validate", "--control", str(temp / "no-such-control"), "--json")
    check(done.returncode == 1, "b2-1.exit", done.stdout)
    envelope = json.loads(done.stdout)
    error = envelope["error"]
    check(error["type"] == "WorkspaceNotFound", "b2-1.kind", done.stdout)
    check(error["next_action"]["action"] == "FIX", "b2-1.fix-class", done.stdout)
    check("--control" in error["next_action"]["supported_by"], "b2-1.flag-named", done.stdout)

    # b2-2: human-mode failure carries the NEXT carrier line
    done = resolver_cli("overlay", "--control", str(control), "--overlay", "badpair")
    check(done.returncode == 1, "b2-2.exit", done.stdout)
    check("[FAIL] SchemaViolation" in done.stdout, "b2-2.what", done.stdout)
    check("NEXT: FIX - " in done.stdout and "NODE=CHECKOUT" in done.stdout,
          "b2-2.next-line", done.stdout)

    # b2-3: clean resolve receipt carries honest NONE
    receipt = wr.resolve(control, {}, None, "shadow", None)
    check(receipt["next_action"] == {"action": "NONE"}, "b2-3.none",
          json.dumps(receipt["next_action"]))

    # b2-4: preflight end-to-end through the fixture devkit's own resolver
    # binary (its DEVKIT_ROOT is the fixture, so the identity check passes)
    argv = [sys.executable, str(devkit / "tools" / "workspace_resolver.py"),
            "preflight", "--control", str(control), "--devkit", str(devkit),
            "--mode", "shadow", "--json"]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace",
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check(done.returncode == 0, "b2-4.exit", done.stdout + done.stderr)
    preflight_receipt = json.loads(done.stdout)
    check(preflight_receipt["next_action"] == {"action": "NONE"}, "b2-4.none",
          json.dumps(preflight_receipt.get("next_action")))

    # b2-5: git-environment failure DIAGNOSEs with supported_by ABSENT
    # (PATH without git: the child OSError site, never an invented retry)
    done = resolver_cli("validate", "--control", str(control), "--json",
                        env={"PATH": str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                                           / "System32")})
    check(done.returncode == 1, "b2-5.exit", done.stdout)
    envelope = json.loads(done.stdout)
    check(envelope["error"]["type"] == "RevisionUnavailable", "b2-5.kind", done.stdout)
    check(envelope["error"]["next_action"] == {"action": "DIAGNOSE"}, "b2-5.diagnose-no-supported",
          json.dumps(envelope["error"]["next_action"]))

    # b2-6: lock-update mechanizes the transaction law into the receipt
    record = {
        "schema": "qiven-dependencies-v1",
        "repository": "qiven-devkit",
        "supported_platforms": ["windows"],
        "provides": [{"contract": "qiven-devkit-operator-v2"}],
        "dependencies": [],
    }
    moved = temp / "moved-devkit"
    (moved / ".qiven").mkdir(parents=True)
    (moved / ".qiven" / "dependencies.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    (moved / "README.md").write_text("moved\n", encoding="utf-8", newline="\n")
    _git(["init", "-q", "-b", "main"], moved)
    _git(["add", "-A"], moved)
    _git(["commit", "-q", "-m", "fixture moved devkit"], moved)
    transaction = wr.lock_update(control, {"qiven-devkit": moved}, "shadow", None)
    check(transaction["next_action"]["action"] == "NEXT", "b2-6.next",
          json.dumps(transaction["next_action"]))
    check("--apply" in transaction["next_action"]["supported_by"], "b2-6.apply-named",
          json.dumps(transaction["next_action"]))
    # publish-first precondition (AD6): the shadow form gates the commit on
    # the moved revisions' publications being accepted first
    check("publications are accepted" in transaction["next_action"]["supported_by"],
          "b2-6.shadow-publish-first", json.dumps(transaction["next_action"]))
    # the APPLIED form names the commit step (temp fixture control only)
    apply_control = temp / "apply-control"
    shutil.copytree(control, apply_control)
    done = resolver_cli("lock-update", "--control", str(apply_control),
                        "--move", f"qiven-devkit={moved}", "--apply", "--json")
    check(done.returncode == 0, "b2-6.apply-exit", done.stdout + done.stderr)
    applied = json.loads(done.stdout)
    check(applied["next_action"]["action"] == "NEXT", "b2-6.applied-next", done.stdout)
    check("commit the control repository" in applied["next_action"]["supported_by"],
          "b2-6.commit-law", done.stdout)
    # publish-first precondition (AD6): the applied form carries it too
    check("publications are accepted" in applied["next_action"]["supported_by"],
          "b2-6.applied-publish-first", done.stdout)
    check("applied_to" in applied, "b2-6.applied-to", done.stdout)

    # b2-7: candidate failures FIX, validated NONE
    good_candidate = temp / "candidate-good.json"
    good_candidate.write_text(json.dumps({
        "schema": "qiven-dependencies-v1",
        "repository": "fixture-candidate",
        "supported_platforms": ["windows"],
        "provides": [{"contract": "qiven-candidate-api-v1"}],
        "dependencies": [{"id": "qiven-devkit", "kind": "tooling",
                          "contract": "qiven-devkit-operator-v2"}],
    }), encoding="utf-8", newline="\n")
    validated = wr.validate_candidate(control, good_candidate)
    check(validated["candidate_validated"] is True, "b2-7.validated", json.dumps(validated))
    check(validated["next_action"] == {"action": "NONE"}, "b2-7.none",
          json.dumps(validated["next_action"]))
    bad_candidate = temp / "candidate-bad.json"
    bad_candidate.write_text(json.dumps({
        "schema": "qiven-dependencies-v1",
        "repository": "fixture-candidate",
        "supported_platforms": ["windows"],
        "provides": [],
        "dependencies": [{"id": "qiven-devkit", "kind": "tooling",
                          "contract": "qiven-not-provided-v9"}],
    }), encoding="utf-8", newline="\n")
    rejected = wr.validate_candidate(control, bad_candidate)
    check(rejected["candidate_validated"] is False, "b2-7.rejected", json.dumps(rejected))
    check(rejected["next_action"]["action"] == "FIX", "b2-7.fix",
          json.dumps(rejected["next_action"]))
    check("failure edge" in rejected["next_action"]["supported_by"], "b2-7.pointer",
          json.dumps(rejected["next_action"]))

    # b2-8: adapter receipt NEXT names the QIVEN_RESOLUTION_FILE binding
    adapter_receipt = wr.emit_adapter(control, "qiven-devkit", devkit, "shadow",
                                      None, {}, None, temp / "adapter-out")
    check(adapter_receipt["next_action"]["action"] == "NEXT", "b2-8.next",
          json.dumps(adapter_receipt["next_action"]))
    check("QIVEN_RESOLUTION_FILE" in adapter_receipt["next_action"]["supported_by"],
          "b2-8.binding-named", json.dumps(adapter_receipt["next_action"]))

    # b2-9: golden vectors - OK carries NONE; a tampered vector FAILs with
    # the FIX route (pinned vectors are the contract, never the edit target)
    done = resolver_cli("golden-vectors")
    check(done.returncode == 0, "b2-9.ok-exit", done.stdout)
    check("[ OK ] golden vectors" in done.stdout, "b2-9.ok", done.stdout)
    check("next NONE" in done.stdout, "b2-9.ok-none", done.stdout)
    tampered_root = temp / "tampered-devkit"
    (tampered_root / "tools").mkdir(parents=True)
    for name in ("workspace_resolver.py", "workspace_schemas.py"):
        (tampered_root / "tools" / name).write_text(
            (ROOT / "tools" / name).read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n")
    schemas_dst = tampered_root / "docs" / "schemas"
    schemas_dst.mkdir(parents=True)
    import workspace_schemas as ws
    for name in ("qiven-workspace-v1.schema.json", "qiven-workspace-lock-v1.schema.json",
                 "qiven-dependencies-v1.schema.json",
                 "workspace-generation-golden-vectors.json"):
        (schemas_dst / name).write_text(
            (ws.SCHEMA_DIR / name).read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n")
    vectors_path = schemas_dst / "workspace-generation-golden-vectors.json"
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    vectors["jcs_vectors"][0]["expected"] = "tampered"
    vectors_path.write_text(json.dumps(vectors, indent=2), encoding="utf-8", newline="\n")
    done = subprocess.run(
        [sys.executable, str(tampered_root / "tools" / "workspace_resolver.py"),
         "golden-vectors"],
        capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check(done.returncode == 1, "b2-9.fail-exit", done.stdout)
    check("[FAIL] jcs" in done.stdout, "b2-9.fail-what", done.stdout)
    check("NEXT: FIX -" in done.stdout and "never the vectors" in done.stdout,
          "b2-9.fail-fix-route", done.stdout)

    # b2-10: law pin - every raised kind has a class assignment, and the
    # class law holds (FIX/NEXT carry supported_by; DIAGNOSE never does)
    source = ast.parse(RESOLVER.read_text(encoding="utf-8"))
    raised_kinds: set[str] = set()
    for node in ast.walk(source):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ResolutionError"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        kind = node.args[0].value
        raised_kinds.add(kind)
        has_override = any(keyword.arg == "next_action" for keyword in node.keywords)
        check(has_override or kind in wr._NEXT_ACTIONS, f"b2-10.kind-{kind}",
              "raised kind has neither a table entry nor a per-site override")
    check(raised_kinds, "b2-10.collected", "no ResolutionError sites found")
    for kind, (action, supported_by) in wr._NEXT_ACTIONS.items():
        check(action in wr.NEXT_ACTIONS, f"b2-10.vocab-{kind}", action)
        if action in ("FIX", "NEXT"):
            check(bool(supported_by.strip()), f"b2-10.fix-supported-{kind}",
                  "FIX/NEXT table entry lacks supported_by")
        else:
            check(not supported_by.strip(), f"b2-10.diagnose-unsupported-{kind}",
                  "DIAGNOSE table entry carries an invented correction")


def gate_configure_legs(temp: Path) -> None:
    control, devkit, lock = wbt._fixture(temp / "g")
    control, devkit = control.resolve(), devkit.resolve()

    def gate_run(*extra: str) -> subprocess.CompletedProcess:
        argv = [sys.executable, str(BOOTSTRAP), "gate-configure",
                "--control", str(control), "--devkit", str(devkit)]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(argv + list(extra), capture_output=True, text=True,
                              timeout=180, encoding="utf-8", errors="replace", env=env)

    # b2-11: adapter child failure -> unified envelope + gate record
    resolver = devkit / "tools" / "workspace_resolver.py"
    saved_resolver = resolver.read_text(encoding="utf-8")
    try:
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b2-11-adapter-out\\n')\n"
            "sys.stderr.write('b2-11-adapter-err\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n")
        done = gate_run("--repo", "qiven-devkit", "--repo-root", str(devkit),
                        "--preset", "default", "--cmake", "cmake")
        check(done.returncode == 1, "b2-11.exit", done.stdout)
        check("[FAIL] resolver-adapter failed; both captured streams follow" in done.stdout,
              "b2-11.pinned-banner", done.stdout[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "AdapterFailed", "b2-11.kind", done.stdout[-400:])
        check("record" in envelope, "b2-11.record-present", done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-11.record-valid",
              json.dumps(cr.validate(record)))
        check(record["producer"]["id"] == "workspace-bootstrap-gate-configure",
              "b2-11.producer", record["producer"]["id"])
        check(record["findings"][0]["rule_id"] == "gate-configure/adapter-failed",
              "b2-11.rule-id", record["findings"][0]["rule_id"])
        check(record["next_action"] == {"action": "DIAGNOSE"}, "b2-11.diagnose",
              json.dumps(record["next_action"]))

        # b2-12: generation mismatch -> FIX naming the lock-update route
        stub_receipt = json.dumps({"workspace_generation": "sha256:" + "0" * 64,
                                   "adapter_path": "", "adapter_sha256": "",
                                   "target_revision": ""})
        resolver.write_text(
            "import sys\n"
            f"sys.stdout.write({stub_receipt!r})\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        done = gate_run("--repo", "qiven-devkit", "--repo-root", str(devkit),
                        "--preset", "default", "--cmake", "cmake")
        check(done.returncode == 1, "b2-12.exit", done.stdout)
        check("adapter generation does not match the lock" in done.stderr,
              "b2-12.pinned-banner", done.stderr[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "GenerationMismatch", "b2-12.kind",
              done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-12.record-valid",
              json.dumps(cr.validate(record)))
        check(record["next_action"]["action"] == "FIX", "b2-12.fix",
              json.dumps(record["next_action"]))
        check("lock-update" in record["next_action"]["supported_by"], "b2-12.route-named",
              json.dumps(record["next_action"]))

        # b2-13: configure rc failure -> ConfigureFailed DIAGNOSE (a valid
        # adapter receipt first; --cmake is the failing interpreter probe)
        adapter_file = temp / "b2-13-adapter.cmake"
        adapter_file.write_text("# b2-13 fixture adapter\n", encoding="utf-8")
        valid_receipt = json.dumps({
            "workspace_generation": lock["generation"],
            "adapter_path": str(adapter_file),
            "adapter_sha256": "sha256:" + "a" * 64,
            "target_revision": "b" * 40,
        })
        resolver.write_text(
            "import sys\n"
            f"sys.stdout.write({valid_receipt!r})\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        done = gate_run("--repo", "qiven-devkit", "--repo-root", str(devkit),
                        "--preset", "default", "--cmake", sys.executable)
        check(done.returncode == 1, "b2-13.exit", done.stdout)
        check("[FAIL] cmake --preset default rc=" in done.stderr, "b2-13.pinned-banner",
              done.stderr[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "ConfigureFailed", "b2-13.kind",
              done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-13.record-valid",
              json.dumps(cr.validate(record)))
        check(record["next_action"] == {"action": "DIAGNOSE"}, "b2-13.diagnose",
              json.dumps(record["next_action"]))
        check(record["findings"][0]["rule_id"] == "gate-configure/configure-failed",
              "b2-13.rule-id", record["findings"][0]["rule_id"])

        # b2-17..19: preflight child-interaction return-1 paths carry the
        # typed envelope with the compliant v1 preflight producer identity
        # (README layout law: EVERY typed failure - preflight AND
        # gate-configure - emits the envelope; the three resolver-preflight
        # child sites were the un-enveloped gap).
        def preflight_run() -> subprocess.CompletedProcess:
            argv = [sys.executable, str(BOOTSTRAP),
                    "--control", str(control), "--devkit", str(devkit)]
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            return subprocess.run(argv, capture_output=True, text=True,
                                  timeout=180, encoding="utf-8", errors="replace",
                                  env=env)

        # b2-17: preflight child failure -> PreflightFailed DIAGNOSE
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b2-17-preflight-out\\n')\n"
            "sys.stderr.write('b2-17-preflight-err\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n")
        done = preflight_run()
        check(done.returncode == 1, "b2-17.exit", done.stdout)
        check("[FAIL] resolver-preflight failed; both captured streams follow"
              in done.stdout, "b2-17.pinned-banner", done.stdout[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "PreflightFailed", "b2-17.kind",
              done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-17.record-valid",
              json.dumps(cr.validate(record)))
        check(record["producer"]["id"] == "workspace-bootstrap-preflight",
              "b2-17.producer", record["producer"]["id"])
        check(record["findings"][0]["rule_id"] == "bootstrap/preflight-failed",
              "b2-17.rule-id", record["findings"][0]["rule_id"])
        check(record["next_action"] == {"action": "DIAGNOSE"}, "b2-17.diagnose",
              json.dumps(record["next_action"]))

        # b2-18: preflight exit-0 with no parseable receipt -> PreflightNoReceipt
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b2-18-garbage-not-json\\n')\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        done = preflight_run()
        check(done.returncode == 1, "b2-18.exit", done.stdout)
        check("[FAIL] resolver preflight emitted no receipt" in done.stderr,
              "b2-18.pinned-banner", done.stderr[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "PreflightNoReceipt", "b2-18.kind",
              done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-18.record-valid",
              json.dumps(cr.validate(record)))
        check(record["findings"][0]["rule_id"] == "bootstrap/preflight-no-receipt",
              "b2-18.rule-id", record["findings"][0]["rule_id"])
        check(record["next_action"] == {"action": "DIAGNOSE"}, "b2-18.diagnose",
              json.dumps(record["next_action"]))

        # b2-19: preflight generation mismatch -> FIX naming the lock-update route
        stub_receipt = json.dumps({"workspace_generation": "sha256:" + "0" * 64})
        resolver.write_text(
            "import sys\n"
            f"sys.stdout.write({stub_receipt!r})\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        done = preflight_run()
        check(done.returncode == 1, "b2-19.exit", done.stdout)
        check("preflight generation does not match the lock" in done.stderr,
              "b2-19.pinned-banner", done.stderr[:300])
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "PreflightGenerationMismatch",
              "b2-19.kind", done.stdout[-400:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-19.record-valid",
              json.dumps(cr.validate(record)))
        check(record["findings"][0]["rule_id"]
              == "bootstrap/preflight-generation-mismatch",
              "b2-19.rule-id", record["findings"][0]["rule_id"])
        check(record["next_action"]["action"] == "FIX", "b2-19.fix",
              json.dumps(record["next_action"]))
        check("lock-update" in record["next_action"]["supported_by"],
              "b2-19.route-named", json.dumps(record["next_action"]))

        # b2-14: preflight records keep the compliant v1 producer shape
        (devkit / "README.md").write_text("b2-14 advanced\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], devkit)
        _git(["commit", "-q", "-m", "b2-14 advance"], devkit)
        argv = [sys.executable, str(BOOTSTRAP), "--control", str(control),
                "--devkit", str(devkit)]
        done = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                              encoding="utf-8", errors="replace",
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        check(done.returncode == 1, "b2-14.exit", done.stdout)
        envelope = _envelope(done.stdout)
        check(envelope["error"]["type"] == "BootstrapDevkitMismatch", "b2-14.kind",
              done.stdout[-300:])
        record = envelope["record"]
        check(cr.validate(record) == [], "b2-14.record-valid",
              json.dumps(cr.validate(record)))
        check(record["producer"]["id"] == "workspace-bootstrap-preflight",
              "b2-14.preflight-producer", record["producer"]["id"])
        check(record["findings"][0]["rule_id"] == "bootstrap/devkit-mismatch",
              "b2-14.preflight-rule", record["findings"][0]["rule_id"])
    finally:
        resolver.write_text(saved_resolver, encoding="utf-8", newline="\n")


def launcher_legs(temp: Path) -> None:
    # b2-15: typed interpreter-failure carriers (exit 2) + forwarding
    env = {**os.environ,
           "QIVEN_PYTHON": str(Path(tempfile.gettempdir()) / "b2-no-such-python.exe")}
    done = subprocess.run(["cmd.exe", "/d", "/c", "call", str(WORKSPACE_CMD)],
                          capture_output=True, text=True, timeout=60,
                          encoding="utf-8", errors="replace",
                          cwd=str(WORKSPACE_ROOT), env=env)
    check(done.returncode == 2, "b2-15.invalid-python-exit", done.stdout)
    check("[FAIL] QIVEN_PYTHON must point to Python 3.9 or newer:" in done.stdout,
          "b2-15.invalid-python-what", done.stdout)
    check("evidence: the configured interpreter reports Python" in done.stdout,
          "b2-15.invalid-python-evidence", done.stdout)
    check("NEXT: FIX - point QIVEN_PYTHON at a Python 3.9 or newer executable" in done.stdout,
          "b2-15.invalid-python-fix", done.stdout)

    env = {**os.environ, "PATH": str(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                                     / "System32")}
    env.pop("QIVEN_PYTHON", None)
    done = subprocess.run(["cmd.exe", "/d", "/c", "call", str(WORKSPACE_CMD)],
                          capture_output=True, text=True, timeout=60,
                          encoding="utf-8", errors="replace",
                          cwd=str(WORKSPACE_ROOT), env=env)
    check(done.returncode == 2, "b2-15.no-python-exit", done.stdout)
    check("[FAIL] Qiven workspace bootstrap requires Python 3.9 or newer." in done.stdout,
          "b2-15.no-python-what", done.stdout)
    check("every candidate failed the 3.9+ probe" in done.stdout, "b2-15.no-python-evidence",
          done.stdout)
    check("NEXT: FIX - set QIVEN_PYTHON to a Python 3.9+ executable path" in done.stdout,
          "b2-15.no-python-fix", done.stdout)

    # forwarding: a real preflight through the launcher releases (exit 0)
    control, devkit, _lock = wbt._fixture(temp / "l")
    done = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(WORKSPACE_CMD),
         "--control", str(control), "--devkit", str(devkit), "preflight"],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
        cwd=str(WORKSPACE_ROOT),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check(done.returncode == 0, "b2-15.forward-ok-exit", done.stdout + done.stderr)
    check(json.loads(done.stdout)["released"] is True, "b2-15.forward-ok-receipt", done.stdout)

    # forwarding: a typed bootstrap failure reaches the caller as exit 1 +
    # the envelope (verbatim argv + exit-code forwarding)
    done = subprocess.run(
        ["cmd.exe", "/d", "/c", "call", str(WORKSPACE_CMD),
         "preflight", "--control", str(temp / "b2-no-such-control")],
        capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
        cwd=str(WORKSPACE_ROOT),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check(done.returncode == 1, "b2-15.forward-fail-exit", done.stdout)
    envelope = _envelope(done.stdout)
    check(envelope["error"]["type"] == "WorkspaceNotFound", "b2-15.forward-fail-kind",
          done.stdout)


def structural_legs() -> None:
    # b2-16: byte-stability pins - the pinned banner bytes the bootstrap
    # contract test drives behaviorally (B11-B13, B15) stay verbatim in the
    # real bootstrap source after the envelope unification
    text = BOOTSTRAP.read_text(encoding="utf-8")
    check("[FAIL] {stage} failed; both captured streams follow" in text,
          "b2-16.adapter-banner")
    check(text.count("_print_captured_failure(") >= 2, "b2-16.both-streams-relay",
          "the both-streams relay sites must remain")
    check("emitted no receipt" in text, "b2-16.no-receipt-banner")
    check("adapter receipt names no adapter file" in text, "b2-16.no-file-banner")
    check("received adapter_path=" in text, "b2-16.received-value")
    check("timed out after" in text and "classify before retrying" in text,
          "b2-16.timeout-law")
    check("qiven-workspace-bootstrap-error-v1" in text, "b2-16.envelope-schema")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qiven-b2-envelope-") as temp_name:
        temp = Path(temp_name)
        resolver_legs(temp)
    if BOOTSTRAP is None or not WORKSPACE_CMD.is_file():
        print("[SKIP] b2-11..16: real qiven-workspace not found "
              "(QIVEN_WORKSPACE_BOOTSTRAP unset, no sibling qiven-workspace)")
        print("[SKIP] b2-11..16: evidence: sibling probe "
              f"{WORKSPACE_CMD} and env probe both came up empty; resolver legs ran")
        print("[SKIP] b2-11..16: NEXT: NEXT - run inside the qiven workspace for the "
              "cross-repo legs (no FIX applies: absence is environment, not a defect)")
    else:
        with tempfile.TemporaryDirectory(prefix="qiven-b2-envelope-gate-") as temp_name:
            gate_configure_legs(Path(temp_name))
        with tempfile.TemporaryDirectory(prefix="qiven-b2-envelope-cmd-") as temp_name:
            launcher_legs(Path(temp_name))
        structural_legs()
    print(f"[ OK ] b2-envelope: {CHECKS} checks")
    return 0


if __name__ == "__main__":
    import selftest_carrier
    raise SystemExit(selftest_carrier.run(__file__, main))
