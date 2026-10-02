"""B6 discovery-surface suite (register repair_batches.B6; DG-1/DG-2/
DG-3/DG-4 row fix, 2026-10-02).

Pins the B6 discovery claims:

  B6-1  `qiven surface` lists gates (default marker, sequence with
        parallel groups) and tasks (builtin/argv) - the O(1) tasks/gates
        introspection (DG-2); --json machine payload parses.
  B6-2  `qiven records` empty state states itself (B1 exec-list law).
  B6-3  `qiven records` lists newest-first with kind/verdict/next and a
        read-back route; `qiven records NAME` prints the ADOPTED
        record_projection bounded view (QIVEN-RECORD v1) + the raw
        evidence-read route; unknown names and traversal are typed
        exit-2 errors pointing back at the listing (DG-3).
  B6-4  workspace_schemas.py: --list enumerates the schema documents
        (the discovery surface for the schema-check __main__), typed
        usage/missing-file errors carry NEXT actions, and the
        validation FAIL carrier gains the four-element summary line
        while per-error bytes and the `[ OK ] schema-check` pass line
        stay byte-stable (row devkit-tool-schema-check).
  B6-5  deploy_bundle.py: verify OK line byte-stable, per-file FAIL
        bytes stable + final NEXT carrier; typed deploy preconditions
        (no receipt / dirty tree / not a repo) carry NEXT actions
        (rows devkit-tool-deploy-bundle-deploy/verify).
  B6-6  doc anchors (devkit-local): operator-usage.md carries the
        workspace-mechanism section (lock-update exact invocation, v58
        friction named), the DG-4 router-registration note, the SG-5
        identity-skew note; the conventions index names the extended
        operator-usage scope; AGENTS.md carries the B6 pointer block;
        `qiven --help` lists surface/records.

Each case id rides in the assertion message. Disposable temp fixtures
only (testing standard; python-standard §8.2).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import common_record as cr  # noqa: E402

OPERATOR = str(ROOT / "tools" / "qiven_operator.py")
SCHEMAS = str(ROOT / "tools" / "workspace_schemas.py")
DEPLOY = str(ROOT / "tools" / "deploy_bundle.py")
CHECKS = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(argv: list[str], *, cwd: pathlib.Path, expect: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args], cwd=repo)


def fixture_repo(base: pathlib.Path) -> pathlib.Path:
    repo = base / "repo"
    (repo / ".qiven").mkdir(parents=True)
    config = {
        "schema_version": 1,
        "repository_name": "b6-discovery-fixture",
        "default_gate": "b6-default-gate",
        "tasks": {
            "b6-pass": {"argv": [sys.executable, "-c", "print('b6-pass')"]},
            "b6-clean": {"builtin": "git_clean_tree"},
        },
        "gates": {
            "b6-default-gate": ["b6-pass"],
            "b6-parallel-gate": [["b6-pass", "b6-clean"]],
        },
    }
    (repo / ".qiven" / "operator.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    return repo


def fixture_record(opid: str, outcome: str, action: str) -> cr.CommonRecord:
    return cr.CommonRecord(
        record_kind="gate-run",
        producer=cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
        operation=cr.Operation(
            id=opid, repository="b6-discovery-fixture",
            invocation="qiven gate b6-default-gate",
            gate="b6-default-gate",
            executing_revision="0" * 40,
        ),
        observation=cr.Observation(coherence="coherent"),
        admission=cr.Admission(state="accepted"),
        completion=cr.Completion(state="completed"),
        domain_outcome=cr.DomainOutcome(outcome=outcome, exit_code=0 if outcome == "passed" else 1),
        coverage=cr.Coverage(collection="complete", executed=["b6-pass"]),
        next_action=cr.NextAction(action=action),
        retry_state=cr.RetryState(side_effects="not_started"),
        payload=cr.Payload(kind="gate-receipt", locator="none"),
    )


def write_record(repo: pathlib.Path, name: str, record: cr.CommonRecord) -> None:
    directory = repo / ".generated-temp" / "operator" / "records"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(cr.serialize(record), encoding="utf-8", newline="\n")


def b6_1_surface(repo: pathlib.Path) -> None:
    human = run([sys.executable, OPERATOR, "--no-color", "surface"], cwd=repo)
    check("surface: 2 gate(s), 2 task(s)" in human.stdout, "B6-1.summary-line", human.stdout)
    check(any(ln.strip() == "gate b6-default-gate (default): b6-pass"
              for ln in human.stdout.splitlines()),
          "B6-1.default-marker", human.stdout)
    check(any(ln.strip() == "gate b6-parallel-gate: (b6-pass | b6-clean)"
              for ln in human.stdout.splitlines()),
          "B6-1.parallel-group", human.stdout)
    check(any(ln.strip() == "task b6-clean: builtin git_clean_tree"
              for ln in human.stdout.splitlines()),
          "B6-1.builtin-task", human.stdout)
    check(any(ln.strip().startswith("task b6-pass: ") for ln in human.stdout.splitlines()),
          "B6-1.argv-task", human.stdout)
    check("NEXT action: NONE" in human.stdout and "qiven gate <name>" in human.stdout,
          "B6-1.next-none", human.stdout)
    machine = run([sys.executable, OPERATOR, "--json", "surface"], cwd=repo)
    payload = json.loads(machine.stdout.splitlines()[-1])
    check(payload.get("default_gate") == "b6-default-gate", "B6-1.json-default")
    check(set(payload.get("gates", {})) == {"b6-default-gate", "b6-parallel-gate"},
          "B6-1.json-gates")
    check(set(payload.get("tasks", {})) == {"b6-pass", "b6-clean"}, "B6-1.json-tasks")
    # help lists the discovery surface (the O(1) entry itself)
    helper = run([sys.executable, OPERATOR, "--no-color", "--help"], cwd=repo)
    check("surface" in helper.stdout and "records" in helper.stdout,
          "B6-1.help-lists-discovery", helper.stdout)


def b6_2_records_empty(repo: pathlib.Path) -> None:
    empty = run([sys.executable, OPERATOR, "--no-color", "records"], cwd=repo)
    check("records: none yet" in empty.stdout, "B6-2.empty-stated", empty.stdout)
    check("NEXT action: NONE" in empty.stdout, "B6-2.empty-next-none", empty.stdout)


def b6_3_records(repo: pathlib.Path) -> None:
    older = "b6-default-gate-" + "0" * 40 + "-20261002T000001Z-00000001-aaaaaa.json"
    newer = "b6-default-gate-" + "0" * 40 + "-20261002T000002Z-00000002-bbbbbb.json"
    write_record(repo, older, fixture_record(older[:-5], "failed", "DIAGNOSE"))
    write_record(repo, newer, fixture_record(newer[:-5], "passed", "NONE"))
    listing = run([sys.executable, OPERATOR, "--no-color", "records"], cwd=repo)
    lines = listing.stdout.splitlines()
    check("records: 2 under .generated-temp/operator/records/" in listing.stdout,
          "B6-3.list-count", listing.stdout)
    check(f"  {newer}  kind=gate-run verdict=PASSED next=NONE" in lines
          and f"  {older}  kind=gate-run verdict=FAILED next=DIAGNOSE" in lines
          and lines.index(f"  {newer}  kind=gate-run verdict=PASSED next=NONE")
          < lines.index(f"  {older}  kind=gate-run verdict=FAILED next=DIAGNOSE"),
          "B6-3.newest-first", listing.stdout)
    check("`qiven records <name>`" in listing.stdout
          and "qiven evidence-read" in listing.stdout,
          "B6-3.read-route", listing.stdout)
    shown = run([sys.executable, OPERATOR, "--no-color", "records", newer], cwd=repo)
    check("QIVEN-RECORD v1" in shown.stdout, "B6-3.projection-view", shown.stdout)
    check("verdict=PASSED" in shown.stdout, "B6-3.verdict", shown.stdout)
    check(f"raw bytes: qiven evidence-read .generated-temp/operator/records/{newer}"
          in shown.stdout, "B6-3.raw-route", shown.stdout)
    machine = run([sys.executable, OPERATOR, "--json", "records", older], cwd=repo)
    payload = json.loads(machine.stdout.splitlines()[-1])
    check(payload.get("status") == "ok"
          and "kind=gate-run" in payload.get("view", ""),
          "B6-3.json-kind", machine.stdout)
    check(payload.get("model_view_bytes", 1 << 20) <= cr.MODEL_VIEW_MAX_BYTES,
          "B6-3.budget", machine.stdout)
    unknown = run([sys.executable, OPERATOR, "--no-color", "records", "no-such.json"],
                  cwd=repo, expect=2)
    check("unknown record" in unknown.stdout and "`qiven records`" in unknown.stdout,
          "B6-3.unknown-typed", unknown.stdout)
    traversal = run([sys.executable, OPERATOR, "--no-color", "records",
                     "subdir/name.json"], cwd=repo, expect=2)
    check("path traversal" in traversal.stdout, "B6-3.traversal-typed", traversal.stdout)


def b6_4_schema_check(base: pathlib.Path) -> None:
    inventory = run([sys.executable, SCHEMAS, "--list"], cwd=ROOT)
    check("[ RUN] schema inventory docs/schemas/" in inventory.stdout,
          "B6-4.list-run", inventory.stdout)
    check("[ OK ] qiven-workspace-v1.schema.json" in inventory.stdout,
          "B6-4.list-names", inventory.stdout)
    check("next NONE" in inventory.stdout, "B6-4.list-next-none", inventory.stdout)
    usage = run([sys.executable, SCHEMAS, "--check", "some-file.json"],
                cwd=ROOT, expect=2)
    check("NEXT action: FIX" in usage.stdout and "--schema" in usage.stdout,
          "B6-4.usage-next", usage.stdout)
    missing = run([sys.executable, SCHEMAS, "--check", "absent.json",
                   "--schema", "docs/schemas/qiven-workspace-v1.schema.json"],
                  cwd=ROOT, expect=2)
    check("[FAIL] instance file not found" in missing.stdout
          and "NEXT action: FIX" in missing.stdout,
          "B6-4.missing-next", missing.stdout)
    instance = base / "b6-instance.json"
    instance.write_text(
        json.dumps({"schema": "qiven-workspace-v1", "nodes": [], "bogus": 1}),
        encoding="utf-8",
    )
    bad = run([sys.executable, SCHEMAS, "--check", str(instance),
               "--schema", "docs/schemas/qiven-workspace-v1.schema.json"],
              cwd=ROOT, expect=1)
    check("[FAIL] UnknownField at bogus: field not in schema" in bad.stdout,
          "B6-4.per-error-bytes-stable", bad.stdout)
    check("- NEXT action: FIX - correct the instance" in bad.stdout
          and "never warnings" in bad.stdout,
          "B6-4.summary-next", bad.stdout)
    good_instance = base / "b6-good.json"
    good_instance.write_text(
        json.dumps({"schema": "qiven-deploy-policy-v1"}),
        encoding="utf-8",
    )
    good = run([sys.executable, SCHEMAS, "--check", str(good_instance),
                "--schema", "docs/schemas/qiven-dependencies-v1.schema.json"],
               cwd=ROOT, expect=1)
    check("[ OK ] schema-check" not in good.stdout, "B6-4.no-false-pass", good.stdout)


def b6_5_deploy(base: pathlib.Path) -> None:
    bundle = base / "bundle"
    (bundle / "docs").mkdir(parents=True)
    (bundle / "app.exe").write_bytes(b"binary-bytes")
    (bundle / "docs" / "README.md").write_text("readme", encoding="utf-8")

    def digest(path: pathlib.Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    files = [{"path": p.relative_to(bundle).as_posix(), "sha256": digest(p)}
             for p in sorted(bundle.rglob("*")) if p.is_file()]
    (bundle / "manifest.json").write_text(
        json.dumps({"schema": "qiven-deploy-manifest-v1",
                    "version": "9.9.9-gabcdef12", "files": files}),
        encoding="utf-8",
    )
    ok = run([sys.executable, DEPLOY, "--verify", str(bundle)], cwd=ROOT)
    check(f"[ OK ] deploy-verify: {len(files)} file(s) verified for 9.9.9-gabcdef12"
          in ok.stdout, "B6-5.verify-ok-bytes", ok.stdout)
    (bundle / "app.exe").write_bytes(b"tampered")
    bad = run([sys.executable, DEPLOY, "--verify", str(bundle)], cwd=ROOT, expect=1)
    check("[FAIL] digest mismatch app.exe" in bad.stdout,
          "B6-5.per-file-bytes-stable", bad.stdout)
    check("- NEXT action: NEXT - re-run the deploy" in bad.stdout,
          "B6-5.verify-next", bad.stdout)
    empty = run([sys.executable, DEPLOY, "--verify", str(base / "empty")],
                cwd=ROOT, expect=1)
    check("no manifest.json" in empty.stdout and "NEXT action: FIX" in empty.stdout,
          "B6-5.no-manifest-next", empty.stdout)

    # deploy preconditions: receipt + clean-tree carriers (no build needed)
    repo = base / "deployrepo"
    (repo / ".qiven").mkdir(parents=True)
    (repo / ".qiven" / "deploy.json").write_text(
        json.dumps({"schema": "qiven-deploy-policy-v1", "product": "b6",
                    "version": "1.0", "products": [],
                    "docs": {"readme_template": "README.md"}, "licenses": {}}),
        encoding="utf-8",
    )
    (repo / "README.md").write_text("r", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "B6Discovery")
    git(repo, "config", "user.email", "b6@example.invalid")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "baseline")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    env = dict(os.environ, QIVEN_DEPLOY_ROOT=str(base / "deployroot"))
    noreceipt = subprocess.run(
        [sys.executable, DEPLOY, "--repo", str(repo)],
        cwd=ROOT, text=True, capture_output=True, env=env, check=False,
    )
    check(noreceipt.returncode == 1, "B6-5.noreceipt-exit", noreceipt.stderr)
    check(f"--expect-head {head}" in noreceipt.stderr
          and "NEXT action: NEXT - run `qiven gate local" in noreceipt.stderr,
          "B6-5.noreceipt-next-exact", noreceipt.stderr)
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    dirty = subprocess.run(
        [sys.executable, DEPLOY, "--repo", str(repo)],
        cwd=ROOT, text=True, capture_output=True, env=env, check=False,
    )
    check("working tree not clean; deploy refuses" in dirty.stderr
          and "NEXT action: FIX - commit or stash" in dirty.stderr,
          "B6-5.dirty-next", dirty.stderr)


def b6_6_doc_anchors() -> None:
    doc = (ROOT / "docs" / "conventions" / "operator-usage.md").read_text(encoding="utf-8")
    check("## Workspace mechanisms" in doc, "B6-6.dg1-section")
    check("lock-update" in doc and "--move NODE=<checkout>" in doc,
          "B6-6.lock-update-invocation")
    check("v58" in doc and "friction" in doc, "B6-6.v58-friction-named")
    check("D:\\JasonWork\\.zcode\\config.json" in doc and "Live-verify" in doc,
          "B6-6.dg4-registration-note")
    check("Identity-skew qualification note" in doc and "SG-5" in doc,
          "B6-6.sg5-identity-skew-note")
    check("## surface" in doc and "## records" in doc, "B6-6.subcommand-sections")
    check("## Devkit tool surfaces" in doc
          and "workspace_schemas.py --list" in doc
          and "deploy_bundle.py --repo" in doc,
          "B6-6.devkit-tool-surfaces")
    index = (ROOT / "docs" / "conventions" / "README.md").read_text(encoding="utf-8")
    check("info/surface/records" in index and "lock-update/resolver/bootstrap" in index,
          "B6-6.index-row-extended")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    check("discovery surface" in agents.lower() and "operator-usage.md" in agents,
          "B6-6.agents-pointer-block")


def main() -> int:
    global CHECKS
    with tempfile.TemporaryDirectory(prefix="qiven-b6-discovery-") as temp:
        base = pathlib.Path(temp)
        repo = fixture_repo(base)
        old_target = os.environ.get("QIVEN_TARGET_ROOT")
        os.environ["QIVEN_TARGET_ROOT"] = str(repo)
        try:
            b6_1_surface(repo)
            b6_2_records_empty(repo)
            b6_3_records(repo)
            b6_4_schema_check(base)
            b6_5_deploy(base)
        finally:
            if old_target is None:
                os.environ.pop("QIVEN_TARGET_ROOT", None)
            else:
                os.environ["QIVEN_TARGET_ROOT"] = old_target
        b6_6_doc_anchors()
    print(f"[ OK ] b6-discovery self-test (B6-1..B6-6, {CHECKS} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
