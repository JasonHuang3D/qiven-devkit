"""Bootstrap contract test (WR-1; the budget's "standard-library bootstrap"
devkit PR).

Exercises the REAL qiven-workspace bootstrap script end to end against
temp git fixtures: lock-subset validation, Devkit identity check BEFORE
any resolver import, preflight-only execution, and the typed failure
classes (BootstrapDevkitMismatch, RevisionUnavailable, DuplicateKey,
UntrustedControlRevision). Also asserts the WG-5 launcher laws on the
script text (no sibling discovery, preflight-only resolver execution)
and re-classifies the new workspace launcher command forms against the
deployed hook router (census entrypoint-integration duty, same batch).

The real bootstrap lives in the qiven-workspace control repository, not
in devkit (it must be loadable before Devkit exists). It is located via
QIVEN_WORKSPACE_BOOTSTRAP or the workspace sibling path; when absent
(managed snapshots, standalone devkit checkouts) the cross-repo legs
SKIP visibly and the router leg still runs, keeping the gate honest
without coupling devkit self-containment to an untracked sibling.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# locator legs assume the machine has no ambient devkit-locator override
os.environ.pop("QIVEN_DEVKIT_CHECKOUT", None)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_exec_router as router  # noqa: E402
import workspace_resolver as wr  # noqa: E402
import workspace_schemas as ws  # noqa: E402

_DEVKIT_ROOT = Path(__file__).resolve().parent.parent
_BOOTSTRAP_CANDIDATES = [
    Path(os.environ["QIVEN_WORKSPACE_BOOTSTRAP"]) if os.environ.get("QIVEN_WORKSPACE_BOOTSTRAP") else None,
    _DEVKIT_ROOT.parent / "qiven-workspace" / "bootstrap" / "qiven-bootstrap.py",
]
BOOTSTRAP = next((p for p in _BOOTSTRAP_CANDIDATES if p and p.is_file()), None)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=15,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise AssertionError(f"fixture git {args}: {result.stderr}")
    return result.stdout.strip()


def _fixture(root: Path) -> tuple[Path, Path, dict]:
    """Control checkout + locked devkit checkout carrying the resolver."""
    devkit = root / "qiven-devkit"
    (devkit / "tools").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], devkit)
    (devkit / "README.md").write_text("fixture devkit\n", encoding="utf-8", newline="\n")
    for name in ("workspace_resolver.py", "workspace_schemas.py"):
        (devkit / "tools" / name).write_text(
            (_DEVKIT_ROOT / "tools" / name).read_text(encoding="utf-8"),
            encoding="utf-8", newline="\n")
    schemas_dst = devkit / "docs" / "schemas"
    schemas_dst.mkdir(parents=True)
    for name in ("qiven-workspace-v1.schema.json", "qiven-workspace-lock-v1.schema.json",
                 "qiven-dependencies-v1.schema.json", "workspace-generation-golden-vectors.json"):
        (schemas_dst / name).write_text(
            (ws.SCHEMA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    _git(["add", "-A"], devkit)
    _git(["commit", "-q", "-m", "fixture devkit"], devkit)

    record = {
        "schema": "qiven-dependencies-v1",
        "repository": "qiven-devkit",
        "supported_platforms": ["windows"],
        "provides": [{"contract": "qiven-devkit-operator-v2"}],
        "dependencies": [],
    }
    declarations = {"schema": "qiven-wr0-census-declarations-v1",
                    "nodes": {"qiven-devkit": record}}
    control = root / "control"
    (control / "census").mkdir(parents=True)
    manifest = {"schema": "qiven-workspace-v1", "workspace_id": "fixture-ws",
                "repositories": {"qiven-devkit": {"url": "https://github.com/O/qiven-devkit.git"}}}
    (control / "workspace.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    (control / "census" / "wr0-declarations.json").write_text(
        json.dumps(declarations, indent=2) + "\n", encoding="utf-8", newline="\n")
    census_blob = _git(["hash-object", "census/wr0-declarations.json"], control)
    lock_sg = {
        "schema": "qiven-workspace-lock-v1",
        "workspace_id": "fixture-ws",
        "nodes": {"qiven-devkit": {
            "commit": _git(["rev-parse", "HEAD"], devkit),
            "tree": _git(["rev-parse", "HEAD^{tree}"], devkit),
            "declaration": {"origin": "census-wr0", "path": "census/wr0-declarations.json",
                            "blob": census_blob, "digest": wr.declaration_digest(record),
                            "shadow_only": True},
        }},
    }
    lock = dict(lock_sg)
    lock["generation"] = wr.generation_digest(manifest, lock_sg)
    (control / "workspace.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    _git(["init", "-q", "-b", "main"], control)
    _git(["add", "-A"], control)
    _git(["commit", "-q", "-m", "fixture control"], control)
    return control, devkit, lock


def _run_bootstrap(control: Path, devkit: Path | None, *extra: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(BOOTSTRAP), "--control", str(control)]
    if devkit is not None:
        argv += ["--devkit", str(devkit)]
    # bytecode stays OUT of the fixture devkit: the fixture carries no
    # .gitignore, so a tools/__pycache__/ dir reads as an untracked-dirty
    # checkout at the B5 strict-clean leg (found live 2026-10-01: B2's
    # add -A + reset --hard incidentally swallowed B1's pyc, masking the
    # class until B8 re-ran the resolver after the reset)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          timeout=180, encoding="utf-8", errors="replace", env=env)


def _error_type(result: subprocess.CompletedProcess) -> str:
    try:
        return json.loads(result.stdout)["error"]["type"]
    except (json.JSONDecodeError, KeyError):
        return f"<unparsed: rc={result.returncode} out={result.stdout[:200]} err={result.stderr[:200]}>"


def _router_leg() -> None:
    # census entrypoint-integration duty: the new workspace launcher forms
    # are short validation commands and must classify allow; the relative
    # devkit gate spelling must stay gate-class. FINDING recorded in the
    # WR-1 session (2026-09-25): path-prefixed qiven.cmd gate spellings
    # (absolute or nested) escape gate-class today - a pre-existing v4.1
    # scope limit surfaced by this re-test, routed as a follow-up batch,
    # not silently changed here.
    benign = [
        r'qiven-workspace\qiven.cmd --devkit D:\ws\qiven-devkit',
        r'python D:\ws\qiven-workspace\bootstrap\qiven-bootstrap.py --control D:\ws\qiven-workspace',
        r'python tools\workspace_resolver.py validate --control . --mode shadow',
    ]
    for command in benign:
        kind = router.classify(command)
        assert kind == "allow", f"B7: {command!r} classified {kind}, expected allow"
    assert router.classify(r'tools\qiven.cmd gate local') == "gate-class", (
        "B7: relative devkit gate spelling must stay gate-class"
    )
    assert router.classify(r'qiven.cmd gate local') == "gate-class", (
        "B7: bare devkit gate spelling must stay gate-class"
    )


def main() -> int:
    _router_leg()
    print("[ OK ] B7 router classification of workspace launcher forms")

    if BOOTSTRAP is None:
        print(f"[SKIP] B1-B6: real bootstrap not found (QIVEN_WORKSPACE_BOOTSTRAP unset, "
              f"no sibling qiven-workspace) - cross-repo legs not run")
        return 0

    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "workspace_resolver.py" in text and "preflight" in text, "B7a: bootstrap must be preflight-only"
    for forbidden in ("listdir", "glob(", "iterdir"):
        assert forbidden not in text, f"B7a: bootstrap performs sibling discovery ({forbidden})"

    # B7b: OBL-20260925T051500Z-A9B0C1 item (1) — the gate-configure cmake
    # subprocess must be timeout-bounded (a hung `cmake --preset` terminates
    # the gate with the typed ConfigureTimeout exit, never hangs it). Static
    # contract pin: a behavioral leg would burn the real 900 s budget.
    assert "timeout=CONFIGURE_TIMEOUT" in text, "B7b: configure subprocess is unbounded"
    assert "ConfigureTimeout" in text, "B7b: no typed configure-timeout branch"

    # B7c (P0 repair R6a): no failure relay may discard one captured
    # stream because the other is non-empty (`stdout or stderr`); both
    # sites must route through the labeled both-streams renderer.
    assert "result.stdout.strip() or result.stderr.strip()" not in text, (
        "B7c: a failure relay discards one captured stream"
    )
    assert text.count("_print_captured_failure(") >= 3, (
        "B7c: preflight and adapter failure paths must relay both streams"
    )

    with tempfile.TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        control, devkit, lock = _fixture(root)

        # B1: end-to-end release through the real bootstrap.
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 0, f"B1: rc={result.returncode} out={result.stdout} err={result.stderr}"
        receipt = json.loads(result.stdout)
        assert receipt["workspace_generation"] == lock["generation"], "B1: generation"
        assert receipt["released"] is True and receipt["shadow_only"] is True, "B1: release flags"

        # B2: wrong Devkit identity fails typed BEFORE any resolver import.
        (devkit / "README.md").write_text("advanced\n", encoding="utf-8", newline="\n")
        _git(["add", "-A"], devkit)
        _git(["commit", "-q", "-m", "advance"], devkit)
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1 and _error_type(result) == "BootstrapDevkitMismatch", (
            f"B2: {_error_type(result)}"
        )
        _git(["reset", "-q", "--hard", "HEAD~1"], devkit)

        # B3: no Devkit locator at all fails typed. Re-scoped 2026-10-01
        # (v53 owner-adjudicated locator symmetry): the fixture control's
        # sibling qiven-devkit now resolves by DEFAULT (see B8), so B3 runs
        # from a relocated control copy that has NO sibling and no mapping.
        lonely_root = root / "lonely"
        lonely_root.mkdir()
        lonely_control = lonely_root / "control"
        shutil.copytree(control, lonely_control)
        result = _run_bootstrap(lonely_control, None)
        assert result.returncode == 1 and _error_type(result) == "RevisionUnavailable", (
            f"B3: {_error_type(result)}"
        )

        # B8: sibling default locator (v53 locator symmetry, R3-F6): with no
        # flag/env/local mapping, the control checkout's sibling qiven-devkit
        # (probed by the resolver file) resolves and identity-checks — the
        # configure-task path and the WR-6 launcher path resolve identically.
        result = _run_bootstrap(control, None)
        assert result.returncode == 0 and json.loads(result.stdout)["released"] is True, (
            f"B8: {_error_type(result)}"
        )

        # B4: duplicate lock keys fail typed at the bootstrap subset stage.
        lock_text = (control / "workspace.lock.json").read_text(encoding="utf-8")
        (control / "workspace.lock.json").write_text(
            lock_text.replace('"workspace_id": "fixture-ws",',
                              '"workspace_id": "fixture-ws", "workspace_id": "fixture-ws",'),
            encoding="utf-8", newline="\n")
        _git(["add", "-A"], control)
        _git(["commit", "-q", "-m", "dup"], control)
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1 and _error_type(result) == "DuplicateKey", (
            f"B4: {_error_type(result)}"
        )
        _git(["reset", "-q", "--hard", "HEAD~1"], control)

        # B5: authoritative bootstrap without an admitting policy is refused.
        # The refusal comes from the RESOLVER child; since R6a the bootstrap
        # relays the failed child's typed JSON inside the labeled
        # `[resolver-preflight stdout]` block (both streams retained), so
        # the class is extracted from that block.
        result = _run_bootstrap(control, devkit, "--mode", "authoritative")
        assert result.returncode == 1, f"B5: rc={result.returncode} out={result.stdout} err={result.stderr}"
        stdout_block = result.stdout.split("[resolver-preflight stdout]\n", 1)[1] \
                               .split("[resolver-preflight stderr]", 1)[0]
        assert json.loads(stdout_block)["error"]["type"] == "UntrustedControlRevision", (
            f"B5: {stdout_block[:200]}"
        )

        # B6: the checkout-mapping file substitutes for --devkit.
        (control / ".qiven-workspace.local.json").write_text(
            json.dumps({"checkouts": {"qiven-devkit": str(devkit)}}),
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, None)
        assert result.returncode == 0 and json.loads(result.stdout)["released"] is True, "B6: mapping leg"

        # B9 (P0 repair R6a): a failing resolver preflight must surface
        # BOTH captured streams, labeled - never discard stderr because
        # stdout is non-empty; a long stream renders bounded with a
        # truthful omitted-byte marker. The stub replaces the fixture
        # resolver (identity still checks: only the worktree is dirty,
        # which shadow mode labels as a note).
        resolver = devkit / "tools" / "workspace_resolver.py"
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b9-out-marker\\n' + 'o' * 5000 + '\\n')\n"
            "sys.stderr.write('b9-err-marker\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1, f"B9: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "[resolver-preflight stdout]" in result.stdout and "b9-out-marker" in result.stdout, (
            f"B9: stdout stream not surfaced: {result.stdout[:300]}"
        )
        assert "[resolver-preflight stderr]" in result.stdout and "b9-err-marker" in result.stdout, (
            f"B9: stderr stream discarded: {result.stdout[:300]}"
        )
        assert "bytes omitted" in result.stdout, "B9: unbounded or unmarked stream excerpt"
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B10 (R6a whole-file completeness): a ZERO-exit child that emits
        # no parseable receipt is still a failed child interaction; its
        # captured payload is the only evidence of what it emitted and
        # must surface (labeled, bounded) - the decode-failure path may
        # not discard the streams the way the nonzero-exit path once did.
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b10-garbage-payload-not-json\\n')\n"
            "sys.stderr.write('b10-child-stderr-note\\n')\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit)
        assert result.returncode == 1, f"B10: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "emitted no receipt" in result.stderr, "B10: untyped decode failure"
        assert "[resolver-preflight stdout]" in result.stdout \
            and "b10-garbage-payload-not-json" in result.stdout, (
            f"B10: child stdout payload discarded: {result.stdout[:300]}"
        )
        assert "[resolver-preflight stderr]" in result.stdout \
            and "b10-child-stderr-note" in result.stdout, (
            f"B10: child stderr payload discarded: {result.stdout[:300]}"
        )
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B11 (R6a adapter-site completeness): the gate-configure ADAPTER
        # nonzero-exit site carries the same both-streams law as the
        # preflight site - typed banner, labeled streams, bounded excerpt.
        # NOTE: the locators are repeated AFTER the subcommand - the
        # bootstrap's subparsers inherit parents=[common] with plain
        # defaults, so a pre-subcommand --control/--devkit is silently
        # overwritten (adjacent pre-existing defect, reported as finding
        # F-bootstrap-argparse; the subparser values win, which is the
        # working spelling).
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b11-adapter-out-marker\\n' + 'a' * 5000 + '\\n')\n"
            "sys.stderr.write('b11-adapter-err-marker\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit, "gate-configure",
                                "--control", str(control), "--devkit", str(devkit),
                                "--repo", "qiven-devkit", "--repo-root", str(devkit),
                                "--preset", "default", "--cmake", "cmake")
        assert result.returncode == 1, f"B11: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "[FAIL] resolver-adapter failed; both captured streams follow" in result.stdout, (
            f"B11: untyped adapter failure: {result.stdout[:300]}"
        )
        assert "[resolver-adapter stdout]" in result.stdout and "b11-adapter-out-marker" in result.stdout, (
            f"B11: adapter stdout not surfaced: {result.stdout[:300]}"
        )
        assert "[resolver-adapter stderr]" in result.stdout and "b11-adapter-err-marker" in result.stdout, (
            f"B11: adapter stderr discarded: {result.stdout[:300]}"
        )
        assert "bytes omitted" in result.stdout, "B11: unbounded or unmarked adapter stream excerpt"
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B12 (R6a adapter-site completeness): the gate-configure ADAPTER
        # no-receipt decode-failure site relays the unparseable payload
        # (labeled, bounded) instead of discarding it.
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b12-garbage-adapter-not-json\\n')\n"
            "sys.stderr.write('b12-adapter-stderr-note\\n')\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit, "gate-configure",
                                "--control", str(control), "--devkit", str(devkit),
                                "--repo", "qiven-devkit", "--repo-root", str(devkit),
                                "--preset", "default", "--cmake", "cmake")
        assert result.returncode == 1, f"B12: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "emitted no receipt" in result.stderr, "B12: untyped adapter decode failure"
        assert "[resolver-adapter stdout]" in result.stdout \
            and "b12-garbage-adapter-not-json" in result.stdout, (
            f"B12: adapter stdout payload discarded: {result.stdout[:300]}"
        )
        assert "[resolver-adapter stderr]" in result.stdout \
            and "b12-adapter-stderr-note" in result.stdout, (
            f"B12: adapter stderr payload discarded: {result.stdout[:300]}"
        )
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B13 (R6a receipt-content completeness): a receipt that DECODES
        # and matches the generation but names no adapter file is a
        # receipt-CONTENT failure site - its banner must name the actual
        # received vs expected values (same law as the generation-mismatch
        # sites). The stub also emits NOTHING on stderr: an empty captured
        # stream must still render its labeled header with an explicit
        # empty marker - an absent header would be indistinguishable from
        # the discarded-stream defect the repair exists to remove.
        stub_receipt = json.dumps({"workspace_generation": lock["generation"],
                                   "adapter_path": ""})
        resolver.write_text(
            "import sys\n"
            f"sys.stdout.write({stub_receipt!r})\n"
            "sys.exit(0)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit, "gate-configure",
                                "--control", str(control), "--devkit", str(devkit),
                                "--repo", "qiven-devkit", "--repo-root", str(devkit),
                                "--preset", "default", "--cmake", "cmake")
        assert result.returncode == 1, f"B13: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "[FAIL] adapter receipt names no adapter file" in result.stderr, (
            f"B13: untyped receipt-content failure: {result.stderr[:300]}"
        )
        assert "received adapter_path=''" in result.stderr, (
            f"B13: receipt-content banner does not name the received value: {result.stderr[:300]}"
        )
        assert "[resolver-adapter stdout]" in result.stdout and "adapter_path" in result.stdout, (
            f"B13: relayed receipt payload not surfaced: {result.stdout[:300]}"
        )
        assert "[resolver-adapter stderr]" in result.stdout, (
            f"B13: empty stream header missing: {result.stdout[:300]}"
        )
        assert "(nothing captured)" in result.stdout, "B13: empty stream not explicitly marked"
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B14 (P0 A2 defect a, F-bootstrap-argparse): shared flags given
        # BEFORE the subcommand must survive the subparser re-parse. The
        # subparsers inherit parents=[common]; with plain defaults the
        # re-parse OVERWROTE the namespace (--control fell back to the
        # ambient workspace root, --mode silently reset to shadow), so
        # the pre-subcommand spelling targeted the wrong workspace.
        # Leg 1: pre-subcommand locators + explicit `preflight`
        # subcommand release the fixture exactly like the default path.
        result = _run_bootstrap(control, devkit, "preflight")
        assert result.returncode == 0, f"B14: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert json.loads(result.stdout)["released"] is True, (
            "B14: pre-subcommand flags did not reach the resolver"
        )

        # Leg 2: --mode authoritative BEFORE the subcommand must arrive.
        # Before the fix the subparser default reset it to shadow and
        # this spelling SUCCEEDED against the fixture (the discriminator:
        # a dropped mode flag silently downgraded an authoritative gate).
        result = _run_bootstrap(control, devkit, "--mode", "authoritative", "preflight")
        assert result.returncode == 1, f"B14: authoritative mode was dropped: {result.stdout[:300]}"
        stdout_block = result.stdout.split("[resolver-preflight stdout]\n", 1)[1] \
                               .split("[resolver-preflight stderr]", 1)[0]
        assert json.loads(stdout_block)["error"]["type"] == "UntrustedControlRevision", (
            f"B14: {stdout_block[:200]}"
        )

        # Leg 3: the gate-configure subparser shares the same parents
        # mechanism - pre-subcommand locators must reach the ADAPTER site
        # (B11's stub shape, locators now only before the subcommand).
        resolver.write_text(
            "import sys\n"
            "sys.stdout.write('b14-adapter-out-marker\\n')\n"
            "sys.stderr.write('b14-adapter-err-marker\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n")
        result = _run_bootstrap(control, devkit, "gate-configure",
                                "--repo", "qiven-devkit", "--repo-root", str(devkit),
                                "--preset", "default", "--cmake", "cmake")
        assert result.returncode == 1, f"B14: rc={result.returncode} out={result.stdout} err={result.stderr}"
        assert "[resolver-adapter stdout]" in result.stdout and "b14-adapter-out-marker" in result.stdout, (
            f"B14: adapter not reached with pre-subcommand flags: {result.stdout[:300]}"
        )
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B15 (P0 A2 defect b): a hung resolver preflight terminates
        # TYPED (PreflightTimeout envelope, rc 1) with the partial
        # captured streams relayed labeled - never a raw traceback.
        # Behavioral leg without burning the real 120 s budget: the
        # module constant is patched in-process (main() reads it at call
        # time); the stub flushes its markers BEFORE sleeping so the
        # timeout's partial capture carries them.
        resolver.write_text(
            "import sys, time\n"
            "sys.stdout.write('b15-out-marker\\n'); sys.stdout.flush()\n"
            "sys.stderr.write('b15-err-marker\\n'); sys.stderr.flush()\n"
            "time.sleep(30)\n",
            encoding="utf-8", newline="\n")
        spec = importlib.util.spec_from_file_location("qiven_bootstrap_under_test", BOOTSTRAP)
        bootstrap_mod = importlib.util.module_from_spec(spec)
        saved_bytecode_flag = sys.dont_write_bytecode
        sys.dont_write_bytecode = True  # the real workspace stays clean
        try:
            spec.loader.exec_module(bootstrap_mod)
        finally:
            sys.dont_write_bytecode = saved_bytecode_flag
        saved_budget = bootstrap_mod.PREFLIGHT_TIMEOUT
        bootstrap_mod.PREFLIGHT_TIMEOUT = 3
        captured_out, captured_err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                rc = bootstrap_mod.main(["--control", str(control), "--devkit", str(devkit),
                                         "preflight"])
        finally:
            bootstrap_mod.PREFLIGHT_TIMEOUT = saved_budget
        out_text, err_text = captured_out.getvalue(), captured_err.getvalue()
        assert rc == 1, f"B15: rc={rc} (typed timeout must exit 1)"
        envelope_at = out_text.find('{\n  "schema"')
        assert envelope_at >= 0, f"B15: no typed error envelope: {out_text[:300]}"
        envelope = json.loads(out_text[envelope_at:])
        assert envelope["error"]["type"] == "PreflightTimeout", f"B15: {envelope}"
        assert "timed out" in err_text, f"B15: no typed timeout banner: {err_text[:300]}"
        assert "[resolver-preflight stdout]" in out_text and "b15-out-marker" in out_text, (
            f"B15: partial stdout not relayed: {out_text[:300]}"
        )
        assert "[resolver-preflight stderr]" in out_text and "b15-err-marker" in out_text, (
            f"B15: partial stderr not relayed: {out_text[:300]}"
        )
        assert "Traceback" not in err_text, "B15: raw traceback escaped the typed contract"
        _git(["checkout", "--", "tools/workspace_resolver.py"], devkit)

        # B16 (P0 A2 defect c): a failing `git` child's typed message
        # retains BOTH captured streams. The classic unborn-HEAD
        # `git rev-parse HEAD` prints "HEAD" to stdout AND the fatal to
        # stderr; the former stderr-only rendering dropped the stdout
        # half of that evidence.
        unborn = root / "unborn"
        unborn.mkdir()
        _git(["init", "-q", "-b", "main"], unborn)
        try:
            bootstrap_mod._git(["rev-parse", "HEAD"], unborn)
            raise AssertionError("B16: unborn rev-parse did not fail typed")
        except bootstrap_mod.Typed as error:
            message = str(error)
            assert "[stdout]" in message and "HEAD" in message, f"B16: stdout dropped: {message}"
            assert "[stderr]" in message and "fatal" in message, f"B16: stderr missing: {message}"

    print("[ OK ] workspace-bootstrap contract test (B1-B16)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
