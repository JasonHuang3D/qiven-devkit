from __future__ import annotations

"""Operator regression suite: gate/run/ci semantics + exec v2 bounded
process custody (docs/design/exec-custody.md).

Case groups:
  G1  generation + identity (info, receipts, fail-fast, isolation, parallel)
  G2  exec v1 semantics preserved under custody (exit codes, logs, UTF-8,
      big output, stdin EOF, batch chains, .cmd wrapping, still-running
      124, stop, observed-exit)
  G3  custody laws (the 2026-09-23 incident regression classes):
      C1  node-reuse leak   — lingering grandchild dies with the run
      C2  lease enforcement — deadline kills the tree with no caller
      C3  custodian death   — watchdog kill => kernel tree-kill
      C5  stop kills job-orphaned members
      C6  task custody      — gate/run tasks reap their trees
      C7  sweep             — expired runs terminated, stale finalized
      C8  atomic records    — concurrent readers never see torn JSON
      C9  custody identity fields on record/status
      C10 heartbeat freshness observable while running
Each numbered assertion raises AssertionError with the case id in its
message on failure.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
CMAKE = os.environ.get("QIVEN_CMAKE")
if not CMAKE:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from toolchain import resolve
    CMAKE = resolve()["cmake"]

IS_WINDOWS = os.name == "nt"
checks = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    if not condition:
        raise AssertionError(f"[{label}] {detail}" if detail else f"[{label}] assertion failed")


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    expect: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != expect:
        raise AssertionError(
            f"unexpected exit {completed.returncode}, expected {expect}: {argv}\n{completed.stdout}"
        )
    return completed


def generate(repo: Path) -> None:
    run(
        [
            CMAKE,
            f"-DDEVKIT_ROOT={ROOT}",
            f"-DDESTINATION={repo}",
            "-DREPOSITORY_NAME=operator-fixture",
            "-DCMAKE_PROJECT_NAME=operator-fixture",
            "-DCMAKE_TARGET_NAME=operator-fixture",
            "-DCMAKE_ALIAS=qiven::operator_fixture",
            "-DCPP_NAMESPACE=qiven::operator_fixture",
            "-DTEST_OPTION_NAME=QIVEN_OPERATOR_FIXTURE_BUILD_TESTS",
            "-DVS_SOLUTION_NAME=operator-fixture",
            "-P",
            str(ROOT / "cmake" / "QivenRepoNew.cmake"),
        ]
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(repo), *args])


def load_operator(repo: Path):
    module_path = repo / "tools" / "qiven_operator.py"
    spec = importlib.util.spec_from_file_location("qiven_operator_fixture", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load generated qiven_operator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parallel_code(me: Path, other: Path) -> str:
    return (
        "from pathlib import Path\n"
        "import time\n"
        f"me = Path({str(me)!r})\n"
        f"other = Path({str(other)!r})\n"
        "me.write_text('ready', encoding='utf-8')\n"
        "deadline = time.monotonic() + 2.0\n"
        "while time.monotonic() < deadline and not other.exists():\n"
        "    time.sleep(0.01)\n"
        "raise SystemExit(0 if other.exists() else 9)\n"
    )


def assert_no_repo_bytecode(repo: Path) -> None:
    artifacts = sorted(
        str(path.relative_to(repo))
        for path in repo.rglob("*")
        if path.is_file() and (path.suffix == ".pyc" or "__pycache__" in path.parts)
    )
    if artifacts:
        raise AssertionError(f"Operator execution wrote Python bytecode into repository: {artifacts}")


def wait_until(predicate, timeout: float, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main() -> int:
    global checks
    with tempfile.TemporaryDirectory(prefix="qiven-operator-test-") as temp:
        repo = Path(temp) / "repo"
        generate(repo)
        for relative in (
            ".qiven/operator.json",
            "tools/qiven.cmd",
            "tools/qiven.py",
            "tools/qiven_operator.py",
        ):
            if not (repo / relative).is_file():
                raise AssertionError(f"missing generated Operator file: {relative}")

        git(repo, "init", "-b", "main")
        git(repo, "add", "--all")
        run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=QivenFixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "baseline",
            ]
        )
        head = git(repo, "rev-parse", "HEAD").stdout.strip()

        # ---------------- G1: generation, identity, gates -----------------
        info = run([sys.executable, "tools/qiven.py", "--json", "info"], cwd=repo)
        payload = json.loads(info.stdout)
        check(payload["status"] == "ok", "G1.info-status")
        check(payload["repository"] == "operator-fixture", "G1.info-repo")
        check(payload["head"] == head, "G1.info-head")
        check("[ RUN]" not in info.stdout and "[ OK ]" not in info.stdout, "G1.json-purity")
        assert_no_repo_bytecode(repo)

        config_path = repo / ".qiven" / "operator.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        marker_a = repo / "a.marker"
        marker_c = repo / "c.marker"
        parallel_a = repo / "parallel-a.marker"
        parallel_b = repo / "parallel-b.marker"
        child_only = "QIVEN_OPERATOR_CHILD_ONLY_7F31B2"

        if IS_WINDOWS:
            leak_script = repo / "tools" / "fixture-env-leak.cmd"
            leak_script.write_text(
                "@echo off\r\n"
                f"set \"{child_only}=leaked\"\r\n"
                "cd /d \"%TEMP%\"\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )
            isolation_set_argv = ["tools/fixture-env-leak.cmd"]
        else:
            isolation_set_argv = [
                sys.executable,
                "-c",
                f"import os, tempfile; os.environ[{child_only!r}]='leaked'; os.chdir(tempfile.gettempdir())",
            ]

        isolation_check = (
            "import os\n"
            "from pathlib import Path\n"
            f"expected = Path({str(repo)!r}).resolve()\n"
            f"leaked = os.environ.get({child_only!r})\n"
            "raise SystemExit(11 if leaked else (12 if Path.cwd().resolve() != expected else 0))\n"
        )

        config["tasks"].update(
            {
                "fixture-pass": {
                    "argv": [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path(r'{marker_a}').write_text('ok')",
                    ]
                },
                "fixture-fail": {"argv": [sys.executable, "-c", "raise SystemExit(7)"]},
                "fixture-must-not-run": {
                    "argv": [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path(r'{marker_c}').write_text('bad')",
                    ]
                },
                "fixture-isolation-set": {"argv": isolation_set_argv},
                "fixture-isolation-check": {"argv": [sys.executable, "-c", isolation_check]},
                "fixture-slow": {"argv": [sys.executable, "-c", "import time; time.sleep(0.18)"]},
                "fixture-parallel-a": {"argv": [sys.executable, "-c", parallel_code(parallel_a, parallel_b)]},
                "fixture-parallel-b": {"argv": [sys.executable, "-c", parallel_code(parallel_b, parallel_a)]},
            }
        )
        config["gates"]["fixture-fail-fast"] = [
            "fixture-pass",
            "fixture-fail",
            "fixture-must-not-run",
        ]
        config["gates"]["fixture-isolation"] = [
            "fixture-isolation-set",
            "fixture-isolation-check",
        ]
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        failed = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-fail-fast"],
            cwd=repo,
            expect=1,
        )
        failed_payload = json.loads(failed.stdout)
        check(failed_payload["status"] == "fail", "G1.failfast-status")
        check(marker_a.is_file(), "G1.failfast-ran-first")
        check(not marker_c.exists(), "G1.failfast-stopped", "fail-fast gate executed a later stage")
        check("[ RUN]" not in failed.stdout and "[FAIL]" not in failed.stdout, "G1.failfast-json-purity")

        isolation = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-isolation"],
            cwd=repo,
        )
        isolation_payload = json.loads(isolation.stdout)
        check(isolation_payload["status"] == "pass", "G1.isolation-pass", isolation.stdout)
        check(os.environ.get(child_only) is None, "G1.no-env-leak")

        parallel = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "run",
                "--parallel",
                "fixture-parallel-a",
                "fixture-parallel-b",
            ],
            cwd=repo,
        )
        parallel_payload = json.loads(parallel.stdout)
        check(parallel_payload["status"] == "pass", "G1.parallel-pass", parallel.stdout)
        check(
            {item["name"] for item in parallel_payload["results"]}
            == {"fixture-parallel-a", "fixture-parallel-b"},
            "G1.parallel-names",
        )
        assert_no_repo_bytecode(repo)

        operator = load_operator(repo)
        operator.HEARTBEAT_SECONDS = 0.05
        operator.POLL_SECONDS = 0.01
        human_output = io.StringIO()
        with contextlib.redirect_stdout(human_output):
            human_rc = operator.main(["--no-color", "run", "fixture-slow"])
        rendered = human_output.getvalue()
        check(human_rc == 0, "G1.human-rc", rendered)
        check("[ RUN] fixture-slow" in rendered, "G1.human-run-tag")
        check("[WAIT] fixture-slow:" in rendered, "G1.human-wait-tag")
        check("[ OK ] fixture-slow" in rendered, "G1.human-ok-tag")
        check("[ OK ] run: PASS" in rendered, "G1.human-summary")
        check("\x1b[" not in rendered, "G1.no-ansi")

        # -------- G2/G3 fixtures + helpers ---------------------------------
        scratch = repo / ".generated-temp" / "exec-tests"
        scratch.mkdir(parents=True, exist_ok=True)

        def qiven_cli(*args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
            return run([sys.executable, "tools/qiven.py", "--json", *args], cwd=repo, expect=expect)

        def exec_start(*target: str, timeout: str, lifetime: str | None = None,
                       expect: int = 0) -> dict:
            args = [sys.executable, "tools/qiven.py", "--json", "exec", "start",
                    "--timeout", timeout]
            if lifetime is not None:
                args += ["--max-lifetime", lifetime]
            completed = run([*args, "--", *target], cwd=repo, expect=expect)
            return json.loads(completed.stdout)

        def exec_status(run_id: str) -> dict:
            return json.loads(qiven_cli("exec", "status", run_id).stdout)

        def exec_record(run_id: str) -> dict:
            return json.loads(
                (repo / ".generated-temp" / "operator" / "exec" / f"{run_id}.json")
                .read_text(encoding="utf-8")
            )

        def exec_log_text(payload: dict) -> str:
            return Path(str(payload["log"])).read_text(encoding="utf-8", errors="replace")

        def pid_dead(pid: int) -> bool:
            return not operator._process_alive(pid)

        # lingering grandchild fixture: writes its pid, then outlives the
        # primary by a minute (the MSBuild node-reuse shape)
        linger = scratch / "linger.py"
        linger.write_text(
            "import os, time\n"
            f"pidfile = r'{scratch / 'linger.pid'}'\n"
            "with open(pidfile, 'w') as handle:\n"
            "    handle.write(str(os.getpid()))\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        spawn_and_exit = scratch / "spawn_and_exit.py"
        spawn_and_exit.write_text(
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, r'{linger}'])\n"
            "print('primary-done', flush=True)\n",
            encoding="utf-8",
        )
        sleep_holder = scratch / "sleep_holder.py"
        sleep_holder.write_text(
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, r'{linger}'])\n"
            "print('holding', flush=True)\n"
            "time.sleep(45)\n",
            encoding="utf-8",
        )

        def linger_pid() -> int | None:
            pidfile = scratch / "linger.pid"
            if not pidfile.is_file():
                return None
            text = pidfile.read_text(encoding="utf-8").strip()
            return int(text) if text.isdigit() else None

        # -------- G2: exec semantics under custody ------------------------

        # (a) creation-flags law: watchdog detached flags + custodied child
        if IS_WINDOWS:
            import subprocess as _sp

            flags = operator._exec_creationflags(breakaway=True)
            check(bool(flags & _sp.CREATE_NO_WINDOW), "G2a.watchdog-no-window")
            check(not flags & _sp.DETACHED_PROCESS, "G2a.no-detached-process")
            check(bool(flags & _sp.CREATE_NEW_PROCESS_GROUP), "G2a.watchdog-group")
            retry_flags = operator._exec_creationflags(breakaway=False)
            check(bool(retry_flags & _sp.CREATE_NO_WINDOW), "G2a.retry-no-window")
            check(not retry_flags & _sp.CREATE_BREAKAWAY_FROM_JOB, "G2a.retry-no-breakaway")
            child_flags = operator._child_creationflags()
            check(bool(child_flags & _sp.CREATE_NO_WINDOW), "G2a.child-no-window")
            check(
                not child_flags & _sp.CREATE_BREAKAWAY_FROM_JOB,
                "G2a.child-never-breaks-away",
                "a custodied child must stay inside the run job",
            )
        else:
            check(operator._exec_creationflags(breakaway=True) == 0, "G2a.posix-zero")

        # (b) stdout AND stderr land in the log; exit codes propagate
        both = exec_start(
            sys.executable, "-c",
            "import sys; print('exec-stdout-marker'); "
            "sys.stderr.write('exec-stderr-marker\\n'); raise SystemExit(3)",
            timeout="60", expect=3,
        )
        check(both["exit_code"] == 3, "G2b.exit-code")
        log_text = exec_log_text(both)
        check("exec-stdout-marker" in log_text, "G2b.stdout-captured", log_text)
        check("exec-stderr-marker" in log_text, "G2b.stderr-captured", log_text)

        # (c) UTF-8 output survives the log round trip
        utf8 = exec_start(sys.executable, "-X", "utf8", "-c", "print('exec-中文-标记')", timeout="60")
        check("exec-中文-标记" in exec_log_text(utf8), "G2c.utf8")

        # (d) large output is not truncated or lost (~1.2 MB)
        big = exec_start(
            sys.executable, "-c",
            "for i in range(20000): print(f'exec-big-line-{i:06d}-" + "x" * 40 + "')",
            timeout="120",
        )
        check(big["log_bytes"] >= 1_000_000, "G2d.big-output", str(big["log_bytes"]))

        # (e) a child that reads stdin gets immediate EOF (DEVNULL), no hang
        stdin_case = exec_start(
            sys.executable, "-c",
            "import sys; data = sys.stdin.read(); "
            "raise SystemExit(42 if data == '' else 43)",
            timeout="60", expect=42,
        )
        check(stdin_case["exit_code"] == 42, "G2e.stdin-eof")

        if IS_WINDOWS:
            # (f) .cmd through exec: echo + exit code (the class that lost
            # output to popup consoles before the 2026-09-23 fix)
            batch = scratch / "echo-seven.cmd"
            batch.write_bytes(
                b"@echo off\r\n"
                b"echo exec-batch-marker\r\n"
                b"exit /b 7\r\n"
            )
            batch_abs = exec_start(str(batch), timeout="60", expect=7)
            check("exec-batch-marker" in exec_log_text(batch_abs), "G2f.batch-log")

            # (g) relative .cmd path resolves against ROOT (WinError 2 class)
            rel_batch = exec_start(
                ".generated-temp/exec-tests/echo-seven.cmd", timeout="60", expect=7
            )
            check("exec-batch-marker" in exec_log_text(rel_batch), "G2g.relative-batch")

            # (h) batch -> batch (call chain) keeps one log
            inner = scratch / "inner.cmd"
            inner.write_bytes(b"@echo off\r\necho exec-inner-marker\r\nexit /b 0\r\n")
            outer = scratch / "outer.cmd"
            outer.write_bytes(
                b"@echo off\r\n"
                b"echo exec-outer-marker\r\n"
                b'call "' + str(inner).encode() + b'"\r\n'
                b"exit /b 0\r\n"
            )
            chain = exec_start(str(outer), timeout="60")
            chain_text = exec_log_text(chain)
            check("exec-outer-marker" in chain_text and "exec-inner-marker" in chain_text, "G2h.chain")

            # (i) console grandchildren keep writing to the log (the popup
            # regression class: cmd -> python -> python)
            grandchild = scratch / "grandchild.py"
            grandchild.write_text("print('exec-grandchild-marker')\n", encoding="utf-8")
            child_py = scratch / "child.py"
            child_py.write_text(
                "import subprocess, sys\n"
                f"subprocess.run([sys.executable, r'{grandchild}'], check=True)\n"
                "print('exec-child-marker')\n",
                encoding="utf-8",
            )
            console_chain = scratch / "console-chain.cmd"
            console_chain.write_bytes(
                b"@echo off\r\n"
                b'"' + sys.executable.encode() + b'" "' + str(child_py).encode() + b'"\r\n'
            )
            deep = exec_start(str(console_chain), timeout="60")
            deep_text = exec_log_text(deep)
            check("exec-child-marker" in deep_text, "G2i.child-marker", deep_text)
            check("exec-grandchild-marker" in deep_text, "G2i.grandchild-marker", deep_text)

            # (j) qiven.cmd itself through exec — and the spawn record shows
            # the cmd.exe wrap
            info_via_cmd = exec_start("tools/qiven.cmd", "--json", "info", timeout="60")
            check('"status"' in exec_log_text(info_via_cmd), "G2j.cmd-through-exec")
            record = exec_record(info_via_cmd["id"])
            check(record["spawn_argv"][0].lower() == "cmd.exe", "G2j.spawn-argv-cmd", str(record["spawn_argv"]))
            check(record["argv"][0] == "tools/qiven.cmd", "G2j.argv-preserved")

            # (k) batch arguments with spaces survive intact
            args_batch = scratch / "echo-args.cmd"
            args_batch.write_bytes(b"@echo off\r\necho arg1=%~1\r\nexit /b 0\r\n")
            spaced = exec_start(str(args_batch), "text with spaces", timeout="60")
            check("arg1=text with spaces" in exec_log_text(spaced), "G2k.spaced-args")

        # (l) front-end timeout returns still-running (124); the child is
        # NOT killed by the front-end returning
        slow = exec_start(
            sys.executable, "-c",
            "import time\n"
            "start = time.time()\n"
            "while time.time() - start < 12.0:\n"
            "    print('beat', flush=True)\n"
            "    time.sleep(0.2)\n",
            timeout="1", lifetime="40", expect=124,
        )
        check(slow["status"] == "still-running", "G2l.still-running")
        run_id = str(slow["id"])
        time.sleep(0.8)
        snap = exec_status(run_id)
        check(snap["state"] == "running", "G2l.status-running", snap.get("state"))
        check("beat" in snap["tail"], "G2l.tail-live")

        # C10: heartbeat freshness is observable while running
        check(
            snap.get("heartbeat_age_seconds") is not None and snap["heartbeat_age_seconds"] < 30,
            "C10.heartbeat-fresh",
            str(snap.get("heartbeat_age_seconds")),
        )

        # C9: custody identity fields are carried on record + status
        rec = exec_record(run_id)
        for field in ("job_name", "watchdog_pid", "deadline_utc", "max_lifetime_seconds"):
            check(bool(rec.get(field)), f"C9.record-{field}", str(rec.get(field)))
        check(snap.get("deadline_utc") == rec.get("deadline_utc"), "C9.status-deadline")
        check(bool(snap.get("watchdog_pid")), "C9.status-watchdog")

        # C8: record rewrites are atomic — a concurrent reader never sees
        # torn JSON while the watchdog heartbeats
        stop_flag = threading.Event()
        parse_failures: list[str] = []
        reads = [0]

        def record_reader() -> None:
            path = repo / ".generated-temp" / "operator" / "exec" / f"{run_id}.json"
            while not stop_flag.is_set():
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    reads[0] += 1
                except FileNotFoundError:
                    pass
                except PermissionError:
                    # transient Windows rename-collision surface, not
                    # corruption; the retry is part of the read contract
                    pass
                except (json.JSONDecodeError, OSError) as exc:
                    parse_failures.append(str(exc))

        reader = threading.Thread(target=record_reader, daemon=True)
        reader.start()

        listing = json.loads(qiven_cli("exec", "list").stdout)
        check(any(item["id"] == run_id for item in listing["runs"]), "G2l.list-visible")

        stop_payload = json.loads(qiven_cli("exec", "stop", run_id).stdout)
        check(stop_payload["status"] == "stopped", "G2l.stopped", stop_payload.get("stop_note"))
        stop_flag.set()
        reader.join(timeout=5)
        check(reads[0] > 0, "C8.reader-progress", str(reads[0]))
        check(not parse_failures, "C8.atomic-records", "; ".join(parse_failures[:3]))

        final = exec_status(run_id)
        check(final["state"] == "stopped", "G2l.final-stopped")
        check(pid_dead(int(slow["pid"])), "G2l.pid-dead-after-stop")

        # (m) an exit the living custodian observes is reported exactly —
        # the custodian outlives the front-end budget and writes the code
        observed = exec_start(
            sys.executable, "-c", "import time; time.sleep(2.5); raise SystemExit(0)",
            timeout="1", lifetime="40", expect=124,
        )
        observed_id = str(observed["id"])
        got_done = wait_until(lambda: exec_status(observed_id)["state"] == "done", timeout=15)
        check(got_done, "G2m.eventual-done")
        observed_snap = exec_status(observed_id)
        check(observed_snap["exit_code"] == 0, "G2m.observed-code", str(observed_snap["exit_code"]))

        # -------- G3: custody laws (the incident regression classes) ------

        # C1 node-reuse leak: primary exits, lingering grandchild must die
        # with the run (kernel job containment + completion reap)
        (scratch / "linger.pid").unlink(missing_ok=True)
        leak = exec_start(sys.executable, str(spawn_and_exit), timeout="60", lifetime="40")
        check(leak["status"] == "done", "C1.primary-done")
        got_pid = wait_until(lambda: linger_pid() is not None, timeout=10)
        check(got_pid, "C1.grandchild-spawned")
        grand_pid = linger_pid()
        reaped = wait_until(lambda: grand_pid is not None and pid_dead(grand_pid), timeout=15)
        check(reaped, "C1.grandchild-reaped", f"grandchild pid {grand_pid} still alive after run done")

        # C5 stop kills job-orphaned members: primary still running, its
        # grandchild lingers inside the same job — stop must reap BOTH
        (scratch / "linger.pid").unlink(missing_ok=True)
        holder = exec_start(sys.executable, str(sleep_holder), timeout="2", lifetime="60", expect=124)
        got_pid = wait_until(lambda: linger_pid() is not None, timeout=10)
        check(got_pid, "C5.grandchild-spawned")
        grand_pid = linger_pid()
        check(not pid_dead(grand_pid), "C5.grandchild-alive-pre-stop")
        stop_two = json.loads(qiven_cli("exec", "stop", str(holder["id"])).stdout)
        check(stop_two["status"] == "stopped", "C5.stop-ack")
        both_dead = wait_until(
            lambda: pid_dead(int(holder["pid"])) and pid_dead(grand_pid), timeout=10
        )
        check(both_dead, "C5.stop-kills-tree", "stop left primary or job member alive")

        # C2 lease enforcement: nobody polls, nobody stops — the deadline
        # still kills the tree (the "dozens of msbuild" class)
        (scratch / "linger.pid").unlink(missing_ok=True)
        leased = exec_start(
            sys.executable, str(sleep_holder), timeout="2", lifetime="11", expect=124
        )
        leased_id = str(leased["id"])
        expired = wait_until(lambda: exec_status(leased_id)["state"] == "expired", timeout=30)
        check(expired, "C2.lease-fires", f"state={exec_status(leased_id)['state']}")
        check(pid_dead(int(leased["pid"])), "C2.primary-dead")
        grand_pid = linger_pid()
        check(grand_pid is None or pid_dead(grand_pid), "C2.tree-dead")

        # C3 custodian death => kernel tree-kill (kill-on-close): simulate
        # the session dying while a run is active
        holder2 = exec_start(sys.executable, str(sleep_holder), timeout="2", lifetime="60", expect=124)
        holder2_id = str(holder2["id"])
        watchdog_pid = int(exec_record(holder2_id)["watchdog_pid"])
        check(operator._process_alive(watchdog_pid), "C3.watchdog-alive")
        if IS_WINDOWS:
            run(["taskkill", "/F", "/PID", str(watchdog_pid)])
        else:
            import signal

            os.kill(watchdog_pid, signal.SIGKILL)
        tree_dead = wait_until(
            lambda: pid_dead(int(holder2["pid"])) and (linger_pid() is None or pid_dead(linger_pid())),
            timeout=15,
        )
        check(tree_dead, "C3.kernel-tree-kill", "tree survived custodian death")
        got_indeterminate = wait_until(
            lambda: exec_status(holder2_id)["state"] == "indeterminate", timeout=10
        )
        check(got_indeterminate, "C3.indeterminate-honest",
              f"state={exec_status(holder2_id)['state']}")

        # C6 task custody: a gate/run task's tree cannot outlive the task
        (scratch / "linger.pid").unlink(missing_ok=True)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["tasks"]["fixture-tree-leak"] = {"argv": [sys.executable, str(spawn_and_exit)]}
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        task_run = run([sys.executable, "tools/qiven.py", "--json", "run", "fixture-tree-leak"], cwd=repo)
        task_payload = json.loads(task_run.stdout)
        check(task_payload["status"] == "pass", "C6.task-pass", task_run.stdout)
        got_pid = wait_until(lambda: linger_pid() is not None, timeout=10)
        check(got_pid, "C6.grandchild-spawned")
        grand_pid = linger_pid()
        task_reaped = wait_until(lambda: pid_dead(grand_pid), timeout=15)
        check(task_reaped, "C6.task-tree-reaped", "task grandchild survived the task")

        # C7 sweep: stale fabricated records are finalized; expired live
        # runs are terminated by the piggyback sweep
        exec_dir = repo / ".generated-temp" / "operator" / "exec"
        stale_id = "20260101T000000Z-00000001-deadbe"
        (exec_dir / f"{stale_id}.json").write_text(
            json.dumps({
                "schema": 2, "id": stale_id, "argv": ["gone"], "pid": 4194303,
                "watchdog_pid": 4194302, "job_name": f"qiven-exec-{stale_id}",
                "log": str(exec_dir / f"{stale_id}.log"),
                "started_utc": "2026-01-01T00:00:00Z",
                "deadline_utc": "2026-01-01T00:10:00Z",
                "max_lifetime_seconds": 600.0, "status": "running",
            }),
            encoding="utf-8",
        )
        # the piggyback sweep rides any invocation (info is cheapest)
        run([sys.executable, "tools/qiven.py", "--json", "info"], cwd=repo)
        stale_after = json.loads(
            (exec_dir / f"{stale_id}.json").read_text(encoding="utf-8")
        )
        check(stale_after.get("status") in ("expired", "indeterminate"), "C7.stale-finalized",
              str(stale_after.get("status")))
        # a healthy run is never touched by an explicit sweep
        healthy = exec_start(sys.executable, str(sleep_holder), timeout="2", lifetime="60", expect=124)
        sweep_payload = json.loads(qiven_cli("exec", "sweep").stdout)
        check(sweep_payload["status"] == "ok", "C7.sweep-ok")
        check(
            not [a for a in sweep_payload["actions"] if a.get("id") == healthy["id"]],
            "C7.no-false-positive",
            "sweep acted on a healthy run: " + str(sweep_payload["actions"]),
        )
        check(exec_status(str(healthy["id"]))["state"] == "running", "C7.healthy-untouched")
        json.loads(qiven_cli("exec", "stop", str(healthy["id"])).stdout)

        # G1 tail: exact-head + clean-tree gates (unchanged v1 laws)
        wrong_head = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "gate",
                "--name",
                "fixture-head",
                "--expect-head",
                "0" * 40,
            ],
            cwd=repo,
            expect=2,
        )
        check(json.loads(wrong_head.stdout)["status"] == "error", "G1.unknown-gate-error")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["gates"]["fixture-head"] = []
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        exact_fail = run(
            [
                sys.executable,
                "tools/qiven.py",
                "--json",
                "gate",
                "--name",
                "fixture-head",
                "--expect-head",
                "0" * 40,
            ],
            cwd=repo,
            expect=1,
        )
        check(json.loads(exact_fail.stdout)["status"] == "fail", "G1.exact-head-fail")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["gates"]["fixture-clean"] = ["clean-tree"]
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        dirty = run(
            [sys.executable, "tools/qiven.py", "--json", "gate", "--name", "fixture-clean"],
            cwd=repo,
            expect=1,
        )
        dirty_payload = json.loads(dirty.stdout)
        check(dirty_payload["status"] == "fail", "G1.clean-tree-fail")
        check("working tree is not clean" in dirty_payload["results"][0]["detail"], "G1.clean-tree-detail")

        # CI dispatch contract (unchanged v1 laws, monkeypatched)
        ci_config = {
            "ci": {
                "full": {
                    "workflow": "ci.yml",
                    "inputs": {"jobs": "full"},
                }
            }
        }
        ci_console = operator.Console(json_mode=True, no_color=True)
        local_head = "a" * 40
        remote_mismatch = "b" * 40
        dispatch_calls: list[list[str]] = []

        operator.shutil.which = lambda name: "gh" if name == "gh" else None
        operator._current_branch = lambda: "fixture-branch"
        operator._head = lambda: local_head
        operator._remote_repo = lambda: "example/operator-fixture"
        operator._remote_branch_head = lambda branch: remote_mismatch

        def fake_run_capture(argv: list[str], *, cwd: Path = operator.ROOT) -> subprocess.CompletedProcess[str]:
            dispatch_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "")

        operator._run_capture = fake_run_capture
        try:
            operator._ci_start(ci_config, "full", ci_console)
        except operator.OperatorError as exc:
            check("match local HEAD" in str(exc), "G1.ci-stale-rejected")
        else:
            raise AssertionError("CI dispatch accepted a stale remote branch")
        check(not dispatch_calls, "G1.ci-no-dispatch-before-verify")

        operator._remote_branch_head = lambda branch: local_head
        ci_payload = operator._ci_start(ci_config, "full", ci_console)
        check(len(dispatch_calls) == 1, "G1.ci-single-dispatch")
        check(ci_payload["status"] == "dispatched", "G1.ci-dispatched")
        check(ci_payload["head"] == local_head, "G1.ci-head")
        check(ci_payload["remote_head"] == local_head, "G1.ci-remote-head")
        check(ci_payload["branch"] == "fixture-branch", "G1.ci-branch")

        # ---------------- G4: ci watch (observation-only runner) ----------
        # Pure helpers first.
        runs = [
            {"databaseId": 11, "headSha": "c" * 40, "status": "completed", "conclusion": "success"},
            {"databaseId": 10, "headSha": local_head, "status": "in_progress", "conclusion": None},
            {"databaseId": 9, "headSha": local_head, "status": "completed", "conclusion": "failure"},
        ]
        check(operator._ci_watch_match_run(runs, local_head)["databaseId"] == 10,
              "G4.match-live-run-beats-older-terminal")
        check(operator._ci_watch_match_run(runs, "d" * 40) is None, "G4.match-miss-is-none")
        terminal_only = [
            {"databaseId": 11, "headSha": "c" * 40, "status": "completed", "conclusion": "success"},
            {"databaseId": 9, "headSha": local_head, "status": "completed", "conclusion": "failure"},
        ]
        check(operator._ci_watch_match_run(terminal_only, local_head)["databaseId"] == 9,
              "G4.match-terminal-fallback-newest")
        check(operator._ci_watch_verdict("in_progress", None) == "pending", "G4.verdict-pending")
        check(operator._ci_watch_verdict("completed", "success") == "success", "G4.verdict-success")
        check(operator._ci_watch_verdict("completed", "failure") == "failure", "G4.verdict-failure")
        check(operator._ci_watch_verdict("completed", "cancelled") == "cancelled", "G4.verdict-cancelled")
        check(operator._ci_watch_verdict("completed", "startup_failure") == "failure",
              "G4.verdict-unknown-conclusion-fails-closed")
        check(operator._ci_watch_verdict("queued", None) == "pending", "G4.verdict-queued-pending")

        # Timeout budget validation: NaN/inf/non-positive must be rejected so
        # the inherently-terminating guarantee cannot be defeated by flags.
        for bad_timeout in (float("nan"), float("inf"), 0.0, -5.0):
            try:
                operator._ci_watch(ci_config, "full", ci_console, bad_timeout, False)
            except operator.OperatorError:
                check(True, "G4.timeout-validated-rejected")
            else:
                raise AssertionError(f"ci watch accepted non-terminating --timeout {bad_timeout!r}")

        # Watch loop against scripted gh replies (dispatch never invoked).
        real_sleep = operator.time.sleep
        watch_calls: list[list[str]] = []
        script = {
            "list": [
                json.dumps([{"databaseId": 10, "headSha": "c" * 40, "status": "completed", "conclusion": "success"}]),
                json.dumps([{"databaseId": 12, "headSha": local_head, "status": "in_progress",
                             "conclusion": None, "url": "https://example/runs/12"}]),
            ],
            "view": [
                json.dumps({"status": "in_progress", "conclusion": None, "url": "https://example/runs/12"}),
                json.dumps({"status": "completed", "conclusion": "success", "url": "https://example/runs/12"}),
            ],
        }
        receipts: list[str] = []
        operator._print_json = lambda payload: receipts.append(json.dumps(payload))
        fast_sleeps: list[float] = []

        def watch_capture(argv: list[str]) -> subprocess.CompletedProcess[str]:
            watch_calls.append(list(argv))
            joined = " ".join(argv)
            if "run list" in joined:
                return subprocess.CompletedProcess(argv, 0, script["list"].pop(0))
            if "run view" in joined:
                return subprocess.CompletedProcess(argv, 0, script["view"].pop(0))
            raise AssertionError(f"unexpected gh call: {argv}")

        operator._gh_capture = watch_capture
        operator.time.sleep = fast_sleeps.append
        watch_console = operator.Console(json_mode=True, no_color=True)
        payload = operator._ci_watch(ci_config, "full", watch_console, 60.0, True)
        check(payload["_exit"] == 0, "G4.watch-success-exit0")
        check(payload["run_id"] == 12, "G4.watch-identity-bound-run")
        check(payload["conclusion"] == "success", "G4.watch-success-conclusion")
        check(payload["url"] == "https://example/runs/12", "G4.watch-url")
        check(receipts and json.loads(receipts[-1])["conclusion"] == "success", "G4.watch-receipt-json")
        check("_exit" not in json.loads(receipts[-1]), "G4.watch-receipt-clean")
        check(all("workflow run" not in " ".join(c) for c in watch_calls), "G4.watch-never-dispatches")
        check(any("run list" in " ".join(c) for c in watch_calls), "G4.watch-discovery-used-list")
        check(len(fast_sleeps) >= 3, "G4.watch-poll-interval-sleeps")

        # Failure conclusion maps to exit 1.
        script["view"] = [json.dumps({"status": "completed", "conclusion": "failure",
                                      "url": "https://example/runs/12"})]
        script["list"] = [json.dumps([{"databaseId": 12, "headSha": local_head, "status": "in_progress",
                                       "conclusion": None, "url": "https://example/runs/12"}])]
        payload = operator._ci_watch(ci_config, "full", watch_console, 60.0, False)
        check(payload["_exit"] == 1, "G4.watch-failure-exit1")

        # Stale same-head terminal decoy: two terminal-only polls, then the
        # live queued run appears - the decoy's verdict must never surface.
        script["list"] = [
            json.dumps([{"databaseId": 9, "headSha": local_head, "status": "completed", "conclusion": "failure"}]),
            json.dumps([{"databaseId": 9, "headSha": local_head, "status": "completed", "conclusion": "failure"}]),
            json.dumps([
                {"databaseId": 9, "headSha": local_head, "status": "completed", "conclusion": "failure"},
                {"databaseId": 12, "headSha": local_head, "status": "queued", "conclusion": None,
                 "url": "https://example/runs/12"},
            ]),
        ]
        script["view"] = [json.dumps({"status": "completed", "conclusion": "success",
                                      "url": "https://example/runs/12"})]
        payload = operator._ci_watch(ci_config, "full", watch_console, 60.0, False)
        check(payload["run_id"] == 12, "G4.watch-stale-terminal-decoy-ignored")
        check(payload["_exit"] == 0, "G4.watch-decoy-run-verdict-not-reported")

        # Terminal-only evidence is accepted after the stabilization window.
        stale_terminal = json.dumps([{"databaseId": 9, "headSha": local_head, "status": "completed",
                                      "conclusion": "failure", "url": "https://example/runs/9"}])
        script["list"] = [stale_terminal] * 4
        payload = operator._ci_watch(ci_config, "full", watch_console, 60.0, False)
        check(payload["run_id"] == 9, "G4.watch-terminal-stabilized-accept")
        check(payload["_exit"] == 1, "G4.watch-terminal-stabilized-verdict")

        # Three consecutive gh failures abort with a typed error.
        def failing_capture(argv: list[str]) -> subprocess.CompletedProcess[str]:
            watch_calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 1, "", "gh unavailable")

        operator._gh_capture = failing_capture
        operator.time.sleep = lambda seconds: None
        try:
            operator._ci_watch(ci_config, "full", watch_console, 5.0, False)
        except operator.OperatorError as exc:
            check("3 times" in str(exc), "G4.watch-gh-three-strikes-typed")
        else:
            raise AssertionError("ci watch did not abort after three gh failures")

        # Poll-phase timeout: run stays pending past the deadline -> verdict
        # timeout with exit 1 (never an infinite wait).
        clock = {"now": 0.0}
        real_monotonic = operator.time.monotonic
        pending_list = json.dumps([{"databaseId": 12, "headSha": local_head, "status": "in_progress",
                                    "conclusion": None, "url": "https://example/runs/12"}])
        pending_view = json.dumps({"status": "in_progress", "conclusion": None,
                                   "url": "https://example/runs/12"})

        def pending_capture(argv: list[str]) -> subprocess.CompletedProcess[str]:
            watch_calls.append(list(argv))
            if "run list" in " ".join(argv):
                return subprocess.CompletedProcess(argv, 0, pending_list)
            return subprocess.CompletedProcess(argv, 0, pending_view)

        def advancing_sleep(seconds: float) -> None:
            clock["now"] += 60.0
            fast_sleeps.append(seconds)

        operator._gh_capture = pending_capture
        operator.time.monotonic = lambda: clock["now"]
        operator.time.sleep = advancing_sleep
        payload = operator._ci_watch(ci_config, "full", watch_console, 1.0, False)
        check(payload["conclusion"] == "timeout", "G4.watch-poll-timeout-verdict")
        check(payload["_exit"] == 1, "G4.watch-poll-timeout-exit1")

        # Discovery timeout is inherently terminating: no run ever appears.
        empty_list = json.dumps([])
        operator._gh_capture = lambda argv: (
            watch_calls.append(list(argv)) or subprocess.CompletedProcess(argv, 0, empty_list)
        )
        try:
            operator._ci_watch(ci_config, "full", watch_console, 1.0, False)
        except operator.OperatorError as exc:
            check("no run found" in str(exc), "G4.watch-discovery-timeout-typed")
        else:
            raise AssertionError("ci watch discovery loop did not terminate on timeout")

        # Restore process-global patches: the fixture module shares the real
        # time module, so later additions to this suite must not inherit fakes.
        operator.time.monotonic = real_monotonic
        operator.time.sleep = real_sleep

    print(f"[ OK ] Qiven Operator tests passed ({checks} named checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
