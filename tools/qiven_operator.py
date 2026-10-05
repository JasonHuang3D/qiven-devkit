from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import uuid

# Common Record v1 siblings (frozen envelope + B+D projection; ADR-0060
# D3). They live in the SAME devkit tools directory as this operator, so
# every consumer path (script invocation, WR-6 importlib load, operator
# tests) resolves them at the executing devkit revision. The fallback
# path insert is pure path resolution for spec-loaded module use.
try:
    import common_record as _cr
except ImportError:  # pragma: no cover - spec-load without tools on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import common_record as _cr

# B1 (ADR-0060 D3; register row devkit-record-projection-py): the bounded
# model view stops being test-only - the FAIL carriers of gate/run adopt
# it as the additive record view after the selector-law summary line.
try:
    import record_projection as _rp
except ImportError:  # pragma: no cover - spec-load without tools on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import record_projection as _rp


# WR-6 consumption model (2026-09-28; supersedes the ADR-0046 Decision-3
# shim+pin wording, which is historical record): consumer repositories
# launch through the workspace bootstrap identity-check, set
# QIVEN_TARGET_ROOT to their own repository root, and import THIS
# operator from the locked devkit node; unset means this checkout is the
# target itself. No consumer-local devkit pin exists.
ROOT = Path(os.environ.get("QIVEN_TARGET_ROOT", Path(__file__).resolve().parents[1])).resolve()
CONFIG_PATH = ROOT / ".qiven" / "operator.json"
HEARTBEAT_SECONDS = 5.0
POLL_SECONDS = 0.05
ANSI_GREEN = "\x1b[32m"
ANSI_RED = "\x1b[31m"
ANSI_YELLOW = "\x1b[33m"
ANSI_CYAN = "\x1b[36m"
ANSI_RESET = "\x1b[0m"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _color_enabled() -> bool:
    if _flag("QIVEN_OPERATOR_NO_COLOR") or os.environ.get("NO_COLOR") is not None or not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


@dataclass
class Result:
    name: str
    status: str
    # None is the not_run sentinel (P0 repair R3): an unexecuted stage's
    # exit was never observed, and standard §4.3 forbids guessing it to 0.
    # All failure accounting keys on truthiness (`if result.returncode`),
    # so None correctly counts as neither pass nor fail.
    returncode: int | None
    duration_seconds: float = 0.0
    detail: str = ""
    output: str = ""
    # P0 repair R2 evidence retention: set only when the task's raw
    # captured-output bytes were retained as a durable artifact (task
    # failure OR over RAW_LOG_RETAIN_THRESHOLD_BYTES). None means "no
    # artifact retained" - absent, never guessed.
    evidence_path: str | None = None
    evidence_sha256: str | None = None
    evidence_bytes: int | None = None


class Console:
    def __init__(self, *, json_mode: bool = False, verbose: bool = False, no_color: bool = False) -> None:
        self.json_mode = json_mode
        self.verbose = verbose
        self.color = _color_enabled() and not json_mode and not no_color
        self._lock = threading.Lock()

    def _paint(self, text: str, color: str) -> str:
        return f"{color}{text}{ANSI_RESET}" if self.color else text

    def tag(self, kind: str) -> str:
        mapping = {
            "run": ("[ RUN]", ANSI_CYAN),
            "wait": ("[WAIT]", ANSI_YELLOW),
            "ok": ("[ OK ]", ANSI_GREEN),
            "fail": ("[FAIL]", ANSI_RED),
        }
        text, color = mapping[kind]
        return self._paint(text, color)

    def emit(self, kind: str, message: str) -> None:
        if self.json_mode:
            return
        with self._lock:
            print(f"{self.tag(kind)} {message}", flush=True)

    def block(self, text: str) -> None:
        if self.json_mode or not text:
            return
        with self._lock:
            print(text, end="" if text.endswith("\n") else "\n", flush=True)


class OperatorError(RuntimeError):
    """A typed operator failure.

    ``next_action`` is the single canonical recovery channel for
    invocation-precondition refusals (ADR-0062 d5: the one failure class
    where the mechanism mechanically knows the correction): a Common
    Record NextAction token (FIX + supported_by) carried BESIDE the
    frozen error text - JSON payload field and human NEXT line share it,
    no second advisory channel. Other failure classes leave it unset and
    their published shape is unchanged (classification stays the
    consumer's step; a guessed correction would violate the class law).
    """

    def __init__(self, message: str, *,
                 next_action: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.next_action = next_action


# ===========================================================================
# Failure guidance (owner direction 2026-10-01: GLM-first-consumer output)
#
# A FAIL line pulls the consuming agent's attention into the failure
# detail and away from the governing contracts (the aggressive-bugfix
# bias: seeing FAIL, agents skip contracts and start "fixing"). The
# FIRST lines a consumer sees on a failure surface are therefore
# GUIDANCE, not the failure text: the known wrong-response pattern for
# the class, the lawful procedure, and the exact pointer. The failure
# detail itself always follows UNMODIFIED (evidence law - failure text
# is never rewritten to soothe). Denial-shaped surfaces (the hook
# router) stay instruction-first by design: their denial IS the
# guidance. Emitted once per surface kind per invocation.
# ============================================================================

_FAILURE_GUIDANCE = {
    "task": (
        "[qiven] Stay calm: classify this failure first; do not edit or detour.\n"
        "[qiven] Do NOT: weaken the gate, comment out a test, lower warnings, or re-run\n"
        "[qiven]       blind (testing-standard section 11 - the gate is the acceptance proof).\n"
        "[qiven] FIRST: read the failing task's output BELOW and NAME the failure class;\n"
        "[qiven]       a timeout is a classification event, never a verdict.\n"
        "[qiven] Procedure + profiles: docs/engineering/execution-protocol.md."
    ),
    "exact-head": (
        "[qiven] Stay calm: exact-head is a string comparison, not fuzzy matching.\n"
        "[qiven] The gate pins the EXACT head: pass the FULL 40-char sha (an abbreviated\n"
        "[qiven]       sha fails the compare even when it names the same commit).\n"
        "[qiven] If HEAD moved since the invocation: commit/stash first, then re-run at\n"
        "[qiven]       the new full sha. Do NOT bypass or re-point the check."
    ),
    "exec": (
        "[qiven] Stay calm: exec failures and exit codes have defined handling; do not detour.\n"
        "[qiven] Exit codes: child code observed / 124 still-running OR indeterminate\n"
        "[qiven]       (key on the payload status field, not the code alone) /\n"
        "[qiven]       1 expired (business code unknown, never guessed) / 2 operator error.\n"
        "[qiven] Procedure: docs/conventions/operator-usage.md (exec section)."
    ),
}


def _emit_failure_guidance(console: "Console", kind: str) -> None:
    text = _FAILURE_GUIDANCE.get(kind)
    if not text:
        return
    emitted = getattr(console, "_guidance_emitted", None)
    if emitted is None:
        emitted = set()
        console._guidance_emitted = emitted
    if kind in emitted:
        return
    emitted.add(kind)
    console.block(text)


def _load_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OperatorError(f"missing Operator config: {CONFIG_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise OperatorError(f"invalid Operator config JSON: {exc}") from exc
    if data.get("schema_version") != 1:
        raise OperatorError("unsupported Operator config schema")
    return data


def _run_capture(argv: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return _run_capture(["git", *args])


# ===========================================================================
# Windows process/job custody layer (exec v2, 2026-09-23 incident redesign)
#
# Production invariants enforced here (docs/design/exec-custody.md):
#   I1 bounded lifetime  - every tree dies by its deadline, kernel-enforced
#   I2 custody on death  - the custodian's death kills its tree instantly
#   I4 tree completeness - the whole tree is one Job Object, no breakaway
#
# The layer is standard-library-only (ctypes). Every helper fails closed:
# a custody primitive that cannot be created means the child is NOT
# spawned (never uncustodied children).
# ===========================================================================

WIN_CREATE_SUSPENDED = 0x00000004
WIN_CREATE_NEW_PROCESS_GROUP = 0x00000200
WIN_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
WIN_CREATE_NO_WINDOW = 0x08000000
WIN_WAIT_OBJECT_0 = 0x00000000
WIN_WAIT_TIMEOUT = 0x00000102
WIN_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
WIN_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
WIN_JOB_OBJECT_EXTENDED_LIMIT = 9  # JobObjectExtendedLimitInformation class
WIN_JOB_OBJECT_TERMINATE = 0x0008  # access right for OpenJobObject
WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WIN_SYNCHRONIZE = 0x00100000
# defense-in-depth cap for runaway recursive fan-out inside one run/task
CUSTODY_ACTIVE_PROCESS_CAP = 512
# grace between primary exit and job termination: bounded window for late
# output flush from straggler writers (stderr shares the stdout handle,
# so no offset interleaving hazard exists)
CUSTODY_REAP_GRACE_SECONDS = 1.5


def _load_kernel32():
    import ctypes
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.BYTE),
            ("SchedulingClass", wintypes.BYTE),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    return kernel32, JOBOBJECT_EXTENDED_LIMIT_INFORMATION


_KERNEL32_CACHE: Any = None


def _win_kernel32():
    global _KERNEL32_CACHE
    if _KERNEL32_CACHE is None:
        _KERNEL32_CACHE = _load_kernel32()
    return _KERNEL32_CACHE


def _win_last_error() -> str:
    import ctypes

    code = ctypes.get_last_error()
    return f"WinError {code}"


def _job_create(name: str | None = None) -> int:
    """Create a custody Job Object: KILL_ON_JOB_CLOSE + process cap.
    Raises OperatorError on failure (fail-closed: no job, no child)."""
    kernel32, info_class = _win_kernel32()
    handle = kernel32.CreateJobObjectW(None, name)
    if not handle:
        raise OperatorError(f"CreateJobObjectW failed: {_win_last_error()}")
    info = info_class()
    info.BasicLimitInformation.LimitFlags = (
        WIN_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | WIN_JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    )
    info.BasicLimitInformation.ActiveProcessLimit = CUSTODY_ACTIVE_PROCESS_CAP
    if not kernel32.SetInformationJobObject(
        handle, WIN_JOB_OBJECT_EXTENDED_LIMIT, ctypes.byref(info), ctypes.sizeof(info)
    ):
        kernel32.CloseHandle(handle)
        raise OperatorError(f"SetInformationJobObject failed: {_win_last_error()}")
    return handle


def _job_terminate(handle: int, exit_code: int) -> bool:
    kernel32, _ = _win_kernel32()
    return bool(kernel32.TerminateJobObject(handle, exit_code))


def _job_open_terminate_by_name(name: str, exit_code: int) -> tuple[bool, str]:
    """Terminate a named job from another process. Returns (terminated, note).
    An unopenable job means no handle exists anywhere, which under
    KILL_ON_JOB_CLOSE means the tree is already dead — reported as success
    with that reason, never as a hang."""
    kernel32, _ = _win_kernel32()
    handle = kernel32.OpenJobObjectW(WIN_JOB_OBJECT_TERMINATE, False, name)
    if not handle:
        return True, f"job object {name} not openable (tree already dead): {_win_last_error()}"
    try:
        if not kernel32.TerminateJobObject(handle, exit_code):
            return False, f"TerminateJobObject failed: {_win_last_error()}"
        return True, "job terminated"
    finally:
        kernel32.CloseHandle(handle)


def _win_spawn(argv: list[str], cwd: Path, env: dict[str, str], stdout_fd: int,
               stdin_fd: int, creationflags: int) -> tuple[int, int, int]:
    """Spawn a custodied child through _winapi.CreateProcess — the same
    battle-tested path subprocess itself uses. Returns (process_handle,
    thread_handle, pid); caller resumes+closes the thread and closes the
    process handle when done. The std fds MUST already be inheritable
    (PEP 446: os.open fds are non-inheritable by default); this function
    asserts that contract rather than silently spawning blind children.
    Raises OSError on failure."""
    import _winapi
    import msvcrt

    os.set_inheritable(stdin_fd, True)
    os.set_inheritable(stdout_fd, True)
    # bInheritHandles=TRUE hands the child EVERY inheritable handle of
    # this process, not just the std trio — including OUR OWN stdout/stdin
    # when the caller supervises us through a pipe. Descendants then keep
    # that pipe open and the caller blocks until the whole run tree exits
    # (observed live: a 1-second supervision budget took 13.8 s to return).
    # De-inherit our stdio first so only the intended handles propagate.
    for std_fd in (0, 1, 2):
        try:
            if os.get_inheritable(std_fd):
                os.set_inheritable(std_fd, False)
        except (OSError, ValueError):
            pass
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= _winapi.STARTF_USESTDHANDLES
    # hStd* fields carry HANDLES; an fd number there is silently invalid
    # (the child loses its redirected output — the empty-log defect class)
    startup.hStdInput = msvcrt.get_osfhandle(stdin_fd)
    startup.hStdOutput = msvcrt.get_osfhandle(stdout_fd)
    startup.hStdError = msvcrt.get_osfhandle(stdout_fd)
    handle, thread, pid, _tid = _winapi.CreateProcess(
        None,
        subprocess.list2cmdline(argv),
        None,
        None,
        True,
        creationflags,
        env,
        str(cwd) if cwd else None,
        startup,
    )
    return handle, thread, pid


def _wait_handle(handle: int, milliseconds: int) -> str:
    """'signaled' | 'timeout' | 'failed' — wait-object liveness without the
    STILL_ACTIVE(259) exit-code ambiguity."""
    kernel32, _ = _win_kernel32()
    result = kernel32.WaitForSingleObject(handle, milliseconds)
    if result == WIN_WAIT_OBJECT_0:
        return "signaled"
    if result == WIN_WAIT_TIMEOUT:
        return "timeout"
    return "failed"


def _exit_code_of_handle(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32, _ = _win_kernel32()
    code = wintypes.DWORD()
    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
        raise OperatorError(f"GetExitCodeProcess failed: {_win_last_error()}")
    return int(code.value)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32, _ = _win_kernel32()
        handle = kernel32.OpenProcess(WIN_PROCESS_QUERY_LIMITED_INFORMATION | WIN_SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            # wait-based check: a process that exited with code 259 is DEAD
            # (the old GetExitCodeProcess==STILL_ACTIVE check misread it)
            return _wait_handle(handle, 0) == "timeout"
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_timestamp_seconds(stamp: object) -> float | None:
    """Parse an RFC3339-UTC second stamp; None when absent or malformed."""
    if not isinstance(stamp, str) or not stamp:
        return None
    import calendar

    try:
        parsed = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return float(calendar.timegm(parsed))


def _utc_now_seconds() -> float:
    import calendar

    return float(calendar.timegm(time.gmtime()))


def _heartbeat_age_seconds(record: dict[str, Any]) -> float | None:
    seconds = _utc_timestamp_seconds(record.get("heartbeat_utc") or record.get("started_utc"))
    if seconds is None:
        return None
    return max(0.0, _utc_now_seconds() - seconds)


# ===========================================================================
# exec v2: supervised detached execution under bounded process custody.
#
# Front-end (qiven exec start): builds the run record, spawns the WATCHDOG
# detached, monitors with heartbeats until its own --timeout budget
# (exit 124 = still running), and returns. The watchdog is the custodian:
# it creates the run's Job Object (KILL_ON_JOB_CLOSE), joins the job
# itself (so its death kills the tree by kernel action), spawns the child
# born into the job, enforces the deadline lease, reaps tree leftovers
# after the primary exits (the MSBuild node-reuse leak class), and
# terminates the job — itself included — with the child's exit code.
#
# Window discipline (2026-09-23 law, unchanged): children and watchdog use
# CREATE_NO_WINDOW, never DETACHED_PROCESS; .cmd/.bat targets run through
# an explicit `cmd.exe /d /c call <abs path>`; path-like argv[0] resolves
# against ROOT before spawning (MEM-20260923T212000Z-D4E5F6).
# ===========================================================================
EXEC_DEFAULT_TIMEOUT_SECONDS = 120.0
EXEC_DEFAULT_MAX_LIFETIME_SECONDS = 3600.0
EXEC_MAX_LIFETIME_CEILING_SECONDS = 86400.0
EXEC_MAX_LIFETIME_FLOOR_SECONDS = 10.0
EXEC_EXIT_STILL_RUNNING = 124
EXEC_WATCHDOG_STARTUP_BUDGET_SECONDS = 15.0
EXEC_HEARTBEAT_STALE_SECONDS = 45.0
_BATCH_SUFFIXES = (".cmd", ".bat")
_REDACTED_ENV_KEYS = ()


def _exec_creationflags(breakaway: bool = True) -> int:
    """Windows creation flags for the detached WATCHDOG spawn. breakaway is
    best-effort survival across a caller's job death; custody never depends
    on it (the lease does)."""
    if os.name != "nt":
        return 0
    flags = WIN_CREATE_NO_WINDOW | WIN_CREATE_NEW_PROCESS_GROUP
    if breakaway:
        flags |= WIN_CREATE_BREAKAWAY_FROM_JOB
    return flags


def _child_creationflags() -> int:
    """Creation flags for a CUSTODIED child: hidden console + own group; NO
    breakaway (the child must stay inside the run's job — tree
    completeness, invariant I4)."""
    if os.name != "nt":
        return 0
    return WIN_CREATE_NO_WINDOW | WIN_CREATE_NEW_PROCESS_GROUP


def _exec_prepare_argv(argv: list[str]) -> list[str]:
    """Harden the exec target before spawning.

    1. A path-like argv[0] (absolute, or containing a separator) that
       exists relative to the operator ROOT is resolved to its absolute
       path — the child's CreateProcess resolves the APPLICATION against
       the CALLER's directories, not the child's cwd, so a relative path
       that looks valid can still WinError 2.
    2. .cmd/.bat targets run through an explicit `cmd.exe /d /c call ...`
       (/d skips AutoRun registry scripts; the explicit form replaces
       CreateProcess's implicit — and undocumented — batch dispatch, and
       makes the console-handling path deterministic).
    """
    if not argv:
        return argv
    head = argv[0]
    rest = argv[1:]
    resolved = head
    if os.path.isabs(head) or ("/" in head) or ("\\" in head):
        candidate = Path(head)
        if not candidate.is_absolute():
            candidate = ROOT / head
        if candidate.is_file():
            resolved = candidate.resolve()
    if str(resolved).lower().endswith(_BATCH_SUFFIXES):
        return ["cmd.exe", "/d", "/c", "call", str(resolved), *rest]
    return [str(resolved), *rest]


def _exec_dir() -> Path:
    return ROOT / ".generated-temp" / "operator" / "exec"


def _new_exec_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{os.getpid():08d}-{os.urandom(3).hex()}"


def _exec_record_path(exec_id: str) -> Path:
    return _exec_dir() / f"{exec_id}.json"


def _exec_log_path(exec_id: str) -> Path:
    return _exec_dir() / f"{exec_id}.log"


RECORD_WRITE_ATTEMPTS = 10
RECORD_WRITE_RETRY_SECONDS = 0.02


def _write_exec_record(record: dict[str, Any]) -> None:
    """Atomic record rewrite (tmp + os.replace) with reader-collision
    retry. On Windows the replace fails with Access Denied while another
    process (the supervising front-end polls every 50 ms) briefly holds
    the file open — Python readers cannot request FILE_SHARE_DELETE, so
    the WRITER must retry. A write that still fails after the retries
    degrades to a truncating direct write (torn-read risk beats losing
    the custodian: record writes must never crash a live watchdog)."""
    path = _exec_record_path(str(record.get("id")))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    for attempt in range(RECORD_WRITE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt + 1 == RECORD_WRITE_ATTEMPTS:
                path.write_text(
                    json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1),
                    encoding="utf-8",
                )
                try:
                    tmp.unlink()
                except OSError:
                    pass
                return
            time.sleep(RECORD_WRITE_RETRY_SECONDS)


def _read_exec_record(exec_id: str) -> dict[str, Any]:
    path = _exec_record_path(exec_id)
    if not path.is_file():
        raise OperatorError(
            f"unknown exec id: {exec_id} (no record at {path})"
            " - NEXT action: FIX - run 'qiven exec list' to enumerate known"
            " run ids (an id typo or a swept/expired run is the usual cause)"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperatorError(f"corrupt exec record: {path}") from exc


def _read_exec_record_path(path: Path) -> dict[str, Any] | None:
    """Best-effort record read for observers (sweeps, lists, monitors).
    A momentary PermissionError is the Windows rename-collision surface,
    not corruption — retry briefly before concluding the record unreadable."""
    last_error: OSError | None = None
    for attempt in range(5):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.01)
            continue
        except (json.JSONDecodeError, OSError):
            return None
        return record if isinstance(record, dict) else None
    del last_error
    return None


_TERMINAL_STATES = frozenset({"done", "stopped", "expired", "error", "indeterminate"})


def _exec_state(record: dict[str, Any]) -> str:
    """Terminal states come from the record; live states are computed from
    custody evidence (watchdog/pid liveness + heartbeat freshness). Never
    guesses an exit code for an unobserved exit. Schema-v1 records (no
    status field) are honored: an observed exit_code means done."""
    if record.get("exit_code") is not None:
        return "done"
    status = str(record.get("status") or "")
    if status in _TERMINAL_STATES:
        return status
    if status == "starting":
        return "starting"
    pid = int(record.get("pid") or 0)
    watchdog_pid = int(record.get("watchdog_pid") or 0)
    watchdog_alive = _process_alive(watchdog_pid)
    primary_alive = _process_alive(pid)
    if watchdog_alive:
        return "running" if primary_alive else "reaping"
    if primary_alive:
        # custody anomaly: kill-on-close should have reaped the tree when
        # the watchdog died; sweep will taskkill it as defense in depth
        return "orphaned"
    return "indeterminate"


def _exec_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    pid = int(record.get("pid") or 0)
    log_path = Path(str(record.get("log") or ""))
    log_size = log_path.stat().st_size if log_path.is_file() else 0
    state = _exec_state(record)
    heartbeat_age = _heartbeat_age_seconds(record)
    return {
        "id": record.get("id"),
        "pid": pid,
        "watchdog_pid": int(record.get("watchdog_pid") or 0),
        "job_name": record.get("job_name"),
        "state": state,
        "exit_code": record.get("exit_code"),
        "argv": record.get("argv"),
        "log": str(log_path),
        "log_bytes": log_size,
        "started_utc": record.get("started_utc"),
        "finished_utc": record.get("finished_utc"),
        "deadline_utc": record.get("deadline_utc"),
        "heartbeat_age_seconds": None if heartbeat_age is None else round(heartbeat_age, 1),
    }


def _tail_text(path: Path, limit_bytes: int) -> str:
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit_bytes:
            handle.seek(-limit_bytes, os.SEEK_END)
        data = handle.read(limit_bytes)
    return data.decode("utf-8", errors="replace")


def _child_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # node-reuse is the observed leak amplifier (v19 incident): even where
    # custody is somehow unavailable, our children never leave MSBuild
    # worker nodes behind
    env["MSBUILDDISABLENODEREUSE"] = "1"
    return env


def _clamp_lifetime(value: float) -> float:
    return min(EXEC_MAX_LIFETIME_CEILING_SECONDS, max(EXEC_MAX_LIFETIME_FLOOR_SECONDS, value))


# --- watchdog (the custodian) ---------------------------------------------


def _watchdog_run(record_path: str) -> int:
    """`python qiven_operator.py --exec-watchdog <record>`: supervise one
    exec run under kernel custody. Owns the run record while running.
    Exit code mirrors the child's; 2 for operator errors before spawn."""
    record = _read_exec_record_path(Path(record_path))
    if record is None:
        sys.stderr.write(f"[watchdog] unreadable record: {record_path}\n")
        return 2
    log_path = Path(str(record.get("log")))
    job_name = str(record.get("job_name"))
    try:
        max_lifetime = float(record.get("max_lifetime_seconds") or 0.0)
    except (TypeError, ValueError):
        max_lifetime = 0.0
    if max_lifetime <= 0.0:
        record["status"] = "error"
        record["error"] = "watchdog record lacks max_lifetime_seconds"
        _write_exec_record(record)
        return 2

    if os.name == "nt":
        try:
            job = _job_create(job_name)
            kernel32, _ = _win_kernel32()
            # join our own job: every descendant is born inside it, and our
            # death (any cause) closes the last handle -> kernel tree-kill
            if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
                raise OperatorError(
                    f"AssignProcessToJobObject(self) failed: {_win_last_error()}"
                )
        except OperatorError as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            _write_exec_record(record)
            sys.stderr.write(f"[watchdog] {exc}\n")
            return 2

    spawn_argv = _exec_prepare_argv(list(record.get("argv") or []))
    if not spawn_argv:
        record["status"] = "error"
        record["error"] = "exec requires a command after --"
        _write_exec_record(record)
        return 2

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process_handle = None
    try:
        if os.name == "nt":
            log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            nul_fd = os.open("NUL", os.O_RDWR)
            try:
                process_handle, thread_handle, pid = _win_spawn(
                    spawn_argv, ROOT, _child_environment(), log_fd, nul_fd,
                    _child_creationflags(),
                )
            finally:
                os.close(log_fd)
                os.close(nul_fd)
            kernel32, _ = _win_kernel32()
            kernel32.ResumeThread(thread_handle)
            kernel32.CloseHandle(thread_handle)
        else:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    spawn_argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, env=_child_environment(),
                    start_new_session=True,
                )
            pid = process.pid
    except OSError as exc:
        record["status"] = "error"
        record["error"] = f"could not start exec process: {exc}"
        record["spawn_argv"] = spawn_argv
        _write_exec_record(record)
        return 2

    record["pid"] = pid
    record["spawn_argv"] = spawn_argv
    record["status"] = "running"
    record["started_utc"] = _utc_now()
    record["watchdog_pid"] = os.getpid()
    record["heartbeat_utc"] = _utc_now()
    _write_exec_record(record)

    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    deadline_monotonic = time.monotonic() + max_lifetime
    while True:
        if os.name == "nt":
            state = _wait_handle(process_handle, 100)
            finished = state == "signaled"
            if state == "failed":
                record["status"] = "error"
                record["error"] = "WaitForSingleObject failed on child handle"
                _write_exec_record(record)
                return 2
        else:
            finished = process.poll() is not None
            time.sleep(0.1)
        now = time.monotonic()
        if finished:
            break
        if now >= deadline_monotonic:
            # lease enforcement: terminal record FIRST (durable before we
            # terminate ourselves inside the job), then kernel kill
            record["status"] = "expired"
            record["finished_utc"] = _utc_now()
            record["heartbeat_utc"] = _utc_now()
            _write_exec_record(record)
            if os.name == "nt":
                _job_terminate(job, EXEC_EXIT_STILL_RUNNING)
                return EXEC_EXIT_STILL_RUNNING  # if the job-kill self did not land
            import signal

            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
            return EXEC_EXIT_STILL_RUNNING
        if now >= next_heartbeat:
            record["heartbeat_utc"] = _utc_now()
            _write_exec_record(record)
            next_heartbeat = now + HEARTBEAT_SECONDS

    if os.name == "nt":
        exit_code = _exit_code_of_handle(process_handle)
    else:
        exit_code = int(process.returncode)
    duration = time.monotonic() - started
    # terminal record BEFORE terminating the job (the termination also
    # ends this watchdog — the record must already be durable)
    record["status"] = "done"
    record["exit_code"] = exit_code
    record["finished_utc"] = _utc_now()
    record["duration_seconds"] = round(duration, 3)
    record["heartbeat_utc"] = _utc_now()
    _write_exec_record(record)
    # completion reaps: bounded grace for straggler writers (MSBuild node
    # reuse class), then the whole tree — leftovers and this watchdog —
    # exits with the child's code
    time.sleep(CUSTODY_REAP_GRACE_SECONDS)
    if os.name == "nt":
        _job_terminate(job, exit_code)
        kernel32, _ = _win_kernel32()
        kernel32.CloseHandle(process_handle)
        return exit_code
    import signal

    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    return exit_code


# --- exec front-end --------------------------------------------------------


def _spawn_watchdog(record_path: Path, diag_path: Path) -> int:
    """Spawn the watchdog detached; returns its pid. Diagnostics land in a
    durable side log for postmortems (empty logs are a defect class)."""
    argv = [sys.executable, str(Path(__file__).resolve()), "--exec-watchdog", str(record_path)]
    if os.name == "nt":
        diag_fd = os.open(str(diag_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        nul_fd = os.open("NUL", os.O_RDWR)
        try:
            flags = _exec_creationflags(breakaway=True)
            try:
                handle, thread, pid = _win_spawn(argv, ROOT, _child_environment(), diag_fd, nul_fd, flags)
            except OSError:
                # restrictive ancestor job forbids breakaway: retry without
                # it — custody never depended on breakaway anyway
                handle, thread, pid = _win_spawn(
                    argv, ROOT, _child_environment(), diag_fd, nul_fd,
                    _exec_creationflags(breakaway=False),
                )
        finally:
            os.close(diag_fd)
            os.close(nul_fd)
        kernel32, _ = _win_kernel32()
        kernel32.ResumeThread(thread)
        kernel32.CloseHandle(thread)
        kernel32.CloseHandle(handle)
        return pid
    with diag_path.open("wb") as diag:
        process = subprocess.Popen(
            argv, cwd=ROOT, stdout=diag, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=_child_environment(), start_new_session=True,
        )
    return process.pid


def _exec_terminal_response(exec_id: str, current: dict[str, Any], console: Console) -> tuple[dict[str, Any], int]:
    """Map a terminal run state to its front-end payload and exit code."""
    state = _exec_state(current)
    # additive Common Record (ADR-0060 D3): terminal front-end outcome
    snapshot = _exec_snapshot(current)
    _emit_exec_record(f"start-{state}", current, state)
    if state == "done":
        code = int(current.get("exit_code") or 0)
        console.emit("ok" if code == 0 else "fail",
                     f"exec {exec_id}: exit {code} ({current.get('duration_seconds', 0)}s)")
        return dict(snapshot, status="done"), code
    if state == "expired":
        _emit_failure_guidance(console, "exec")
        console.emit("fail", f"exec {exec_id}: lease expired at {current.get('deadline_utc')} (tree killed, code unknown)")
        return dict(snapshot, status="expired"), 1
    if state == "error":
        detail = str(current.get("error") or "watchdog error")
        _emit_failure_guidance(console, "exec")
        console.emit("fail", f"exec {exec_id}: {detail}")
        return dict(snapshot, status="error"), 2
    if state == "stopped":
        console.emit("ok", f"exec {exec_id}: stopped")
        return dict(snapshot, status="stopped"), 0
    _emit_failure_guidance(console, "exec")
    console.emit("wait", f"exec {exec_id}: indeterminate exit (no living supervisor observed it)")
    return dict(snapshot, status="indeterminate"), EXEC_EXIT_STILL_RUNNING


def _exec_start_frontend(argv: list[str], timeout_seconds: float, max_lifetime: float,
                         console: Console) -> tuple[dict[str, Any], int]:
    if not argv:
        # ADR-0062 d5 channel law mirrored from main()'s exec-start check:
        # unreachable via the CLI today (main rejects the empty command
        # first), but a direct caller of the frontend must not bypass the
        # canonical FIX recovery channel.
        raise OperatorError(
            "exec requires a command after --",
            next_action=asdict(_cr.next_action_for(
                "invocation-rejected",
                "supply the command to run after the '--' separator"
                " (qiven exec start -- <command> [args...]) and"
                " re-invoke",
            )),
        )
    max_lifetime = _clamp_lifetime(max_lifetime)
    timeout_seconds = max(1.0, min(timeout_seconds, max_lifetime))
    exec_id = _new_exec_id()
    log_path = _exec_log_path(exec_id)
    record_path = _exec_record_path(exec_id)
    diag_path = _exec_dir() / f"{exec_id}.watchdog.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    deadline_utc = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(_utc_now_seconds() + max_lifetime)
    )
    record: dict[str, Any] = {
        "schema": 2,
        "id": exec_id,
        "argv": list(argv),
        "log": str(log_path),
        "job_name": f"qiven-exec-{exec_id}",
        "started_utc": _utc_now(),
        "timeout_seconds": timeout_seconds,
        "max_lifetime_seconds": max_lifetime,
        "deadline_utc": deadline_utc,
        "status": "starting",
    }
    _write_exec_record(record)

    try:
        watchdog_pid = _spawn_watchdog(record_path, diag_path)
    except OSError as exc:
        record["status"] = "error"
        record["error"] = f"could not spawn watchdog: {exc}"
        _write_exec_record(record)
        detail = f"exec start failed (watchdog spawn): {exc}"
        _emit_failure_guidance(console, "exec")
        console.emit("fail", detail)
        return {"status": "error", "error": detail, "argv": argv}, 2
    # from here the WATCHDOG owns the record: its first write carries pid,
    # watchdog_pid and state=running. A front-end rewrite here would race
    # that write and could regress the record to "starting".
    console.emit("run", f"exec {exec_id}: watchdog pid {watchdog_pid}, lease {max_lifetime:.0f}s, log {log_path}")

    started = time.monotonic()

    # phase 1: wait for the watchdog to signal (record gains pid + state)
    while True:
        current = _read_exec_record_path(record_path) or record
        state = _exec_state(current)
        if state != "starting":
            record = current
            break
        if time.monotonic() - started >= EXEC_WATCHDOG_STARTUP_BUDGET_SECONDS:
            detail = (f"watchdog {watchdog_pid} did not signal within "
                      f"{EXEC_WATCHDOG_STARTUP_BUDGET_SECONDS:.0f}s "
                      f"(diagnostics: {diag_path})")
            console.emit("fail", f"exec {exec_id}: {detail}")
            current = _read_exec_record_path(record_path) or record
            current["status"] = "error"
            current["error"] = detail
            _write_exec_record(current)
            _emit_exec_record("start-error", current, "error")
            _kill_tree_hard(watchdog_pid)
            return {"status": "error", "error": detail, "id": exec_id, "argv": argv}, 2
        time.sleep(POLL_SECONDS)

    # phase 2: supervise until a terminal state or the front-end budget.
    # The run itself is bounded by the LEASE, never by this loop: when the
    # budget elapses the watchdog keeps custody and enforces the deadline.
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    while True:
        current = _read_exec_record_path(record_path) or record
        record = current
        state = _exec_state(current)
        if state in _TERMINAL_STATES:
            return _exec_terminal_response(exec_id, current, console)
        now = time.monotonic()
        if now - started >= timeout_seconds:
            snapshot = _exec_snapshot(current)
            # additive Common Record: the still-running 124 return (a
            # live run under custody; never conflated with indeterminate)
            _emit_exec_record("start-still-running", current, "running")
            console.emit(
                "wait",
                f"exec {exec_id}: still running after {timeout_seconds:.0f}s "
                f"(log {snapshot['log_bytes']} bytes); operator returns; lease {deadline_utc}",
            )
            # B5 (four-element law): the 124 surface teaches WHY (the
            # operator's own supervision budget elapsed - the run is NOT
            # failed, it continues under watchdog custody until the lease)
            # and the re-attach route; the WAIT line above stays
            # byte-stable and 124 is never a verdict
            console.block(
                f"  why: exit 124 is the operator supervision budget, not a failure\n"
                f"  verdict - the run continues under watchdog custody until lease\n"
                f"  {deadline_utc}; the business outcome is not yet observed\n"
                f"  NEXT action: re-attach with `qiven exec status {exec_id}` between\n"
                f"  other work (never a tight poll); read the log at\n"
                f"  done/expired/indeterminate; key on the payload status field,\n"
                f"  not the exit code"
            )
            return dict(snapshot, status="still-running"), EXEC_EXIT_STILL_RUNNING
        if now >= next_heartbeat:
            log_bytes = log_path.stat().st_size if log_path.is_file() else 0
            age = _heartbeat_age_seconds(current)
            console.emit(
                "wait",
                f"exec {exec_id}: running for {now - started:.0f}s, log {log_bytes} bytes"
                + (f", custodian beat {age:.0f}s ago" if age is not None else ""),
            )
            next_heartbeat = now + HEARTBEAT_SECONDS
        time.sleep(POLL_SECONDS)


def _kill_tree_hard(pid: int) -> None:
    """Last-resort tree kill (sweep defense in depth; not the primary
    custody path)."""
    if pid <= 0:
        return
    if os.name == "nt":
        _run_capture(["taskkill", "/T", "/F", "/PID", str(pid)])
    else:
        import signal

        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _exec_stop(record: dict[str, Any], console: Console) -> tuple[dict[str, Any], int]:
    exec_id = str(record.get("id"))
    state = _exec_state(record)
    if state in _TERMINAL_STATES:
        snapshot = _exec_snapshot(record)
        snapshot["status"] = "not-running" if state == "indeterminate" else state
        console.emit("ok", f"exec stop {exec_id}: already {state}")
        return snapshot, 0
    job_name = str(record.get("job_name") or "")
    # durable terminal record FIRST, then the kernel action
    record["status"] = "stopped"
    record["finished_utc"] = _utc_now()
    _write_exec_record(record)
    note = "no job name on record"
    if os.name == "nt" and job_name:
        terminated, note = _job_open_terminate_by_name(job_name, 130)
    else:
        _kill_tree_hard(int(record.get("pid") or 0))
        terminated, note = True, "tree killed"
    snapshot = _exec_snapshot(record)
    snapshot["stop_note"] = note
    snapshot["status"] = "stopped"
    if terminated:
        console.emit("ok", f"exec stop {exec_id}: stopped ({note})")
    else:
        # B1 (D3): a failed termination teaches its own next step instead
        # of a bare FAIL; the record keeps pid + job_name for the manual
        # route.
        console.emit(
            "fail",
            f"exec stop {exec_id}: stopped ({note})"
            " - NEXT action: DIAGNOSE - the job-object terminate failed;"
            " verify the process state before retrying (taskkill /PID"
            f" {record.get('pid')} /T; the run record keeps pid + job_name)",
        )
    return snapshot, 0 if terminated else 1


def _sweep_exec_records(console: Console | None = None, *, quiet: bool = True) -> list[dict[str, Any]]:
    """Dead-man insurance, piggybacked on every operator invocation:
    terminate runs past their lease, hard-kill custody anomalies, finalize
    stale records. Never raises; never touches healthy runs."""
    actions: list[dict[str, Any]] = []
    directory = _exec_dir()
    if not directory.is_dir():
        return actions
    now_seconds = _utc_now_seconds()
    for record_path in sorted(directory.glob("*.json")):
        record = _read_exec_record_path(record_path)
        if record is None:
            continue
        status = str(record.get("status") or "")
        if status in _TERMINAL_STATES:
            continue
        state = _exec_state(record)
        if state == "orphaned":
            _kill_tree_hard(int(record.get("pid") or 0))
            record["status"] = "stopped"
            record["finished_utc"] = _utc_now()
            record["stop_note"] = "sweep: custody anomaly hard-killed"
            _write_exec_record(record)
            actions.append({"id": record.get("id"), "action": "hard-killed"})
        elif state == "indeterminate":
            record["status"] = "indeterminate"
            record["finished_utc"] = _utc_now()
            _write_exec_record(record)
            actions.append({"id": record.get("id"), "action": "finalized-indeterminate"})
        else:
            deadline = _utc_timestamp_seconds(str(record.get("deadline_utc") or ""))
            if deadline is not None and now_seconds > deadline:
                job_name = str(record.get("job_name") or "")
                if os.name == "nt" and job_name:
                    _job_open_terminate_by_name(job_name, EXEC_EXIT_STILL_RUNNING)
                else:
                    _kill_tree_hard(int(record.get("pid") or 0))
                record["status"] = "expired"
                record["finished_utc"] = _utc_now()
                _write_exec_record(record)
                actions.append({"id": record.get("id"), "action": "expired"})
    if actions and console is not None and not quiet:
        for action in actions:
            console.emit("wait", f"exec sweep: {action['action']} {action['id']}")
    return actions


def _locked_toolchain_commit() -> str:
    """WR-5: the locked qiven-toolchain-win node commit (typed fail)."""
    control = Path(os.environ.get("QIVEN_WORKSPACE_CONTROL",
                                  ROOT.parent / "qiven-workspace")).resolve()
    lock_path = control / "workspace.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"workspace lock unreadable at {lock_path}: {exc}") from exc
    node = lock.get("nodes", {}).get("qiven-toolchain-win")
    commit = node.get("commit") if isinstance(node, dict) else None
    if not isinstance(commit, str) or len(commit) != 40:
        raise OperatorError("workspace lock has no qiven-toolchain-win node commit")
    return commit


def _toolchain() -> dict[str, str]:
    root = Path(os.environ.get("QIVEN_TOOLCHAIN_ROOT", ROOT.parent / "qiven-toolchain-win")).resolve()
    locked = _locked_toolchain_commit()
    head = _run_capture(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=root)
    head_sha = head.stdout.strip() if head.returncode == 0 else ""
    if head_sha != locked:
        raise OperatorError(f"toolchain checkout at {head_sha[:12] or '<unreadable>'} != "
                            f"locked node {locked[:12]}; advance the workspace lock deliberately")
    manifest = root / "toolchain.json"
    if not manifest.is_file():
        raise OperatorError(f"toolchain manifest not found: {manifest}")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperatorError(f"invalid toolchain manifest: {exc}") from exc
    tools = data.get("tools", {})
    resolved: dict[str, str] = {"toolchain_root": str(root)}
    for logical, key in (("cmake", "cmake"), ("clang_format", "clang-format")):
        entry = tools.get(key)
        if not isinstance(entry, dict) or not entry.get("path"):
            raise OperatorError(f"toolchain manifest lacks {key}")
        path = (root / entry["path"]).resolve()
        if not path.is_file():
            raise OperatorError(f"tool not found: {path}")
        resolved[logical] = str(path)
    ctest = Path(resolved["cmake"]).with_name("ctest.exe" if os.name == "nt" else "ctest")
    if not ctest.is_file():
        raise OperatorError(f"ctest not found beside CMake: {ctest}")
    resolved["ctest"] = str(ctest)
    return resolved


def _expand(value: str, tools: dict[str, str] | None) -> str:
    if "{" not in value:
        return value
    mapping = {"root": str(ROOT), "python": sys.executable}
    if tools:
        mapping.update(tools)
    try:
        return value.format_map(mapping)
    except KeyError as exc:
        raise OperatorError(f"unknown command placeholder: {exc.args[0]}") from exc


def _argv_for_task(spec: dict[str, Any]) -> list[str]:
    raw = spec.get("argv")
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) and item for item in raw):
        raise OperatorError("command task requires non-empty string argv")
    needs_tools = any("{cmake}" in item or "{ctest}" in item or "{clang_format}" in item or "{toolchain_root}" in item for item in raw)
    tools = _toolchain() if needs_tools else None
    argv = [_expand(item, tools) for item in raw]
    candidate = Path(argv[0])
    if not candidate.is_absolute():
        local = ROOT / candidate
        if local.exists():
            argv[0] = str(local)
    if argv[0].lower().endswith((".cmd", ".bat")):
        if os.name != "nt":
            raise OperatorError("Windows batch task requested on non-Windows host")
        command_line = subprocess.list2cmdline(argv)
        return ["cmd.exe", "/d", "/s", "/c", f"call {command_line}"]
    return argv


# ===========================================================================
# Bounded inline excerpts + raw evidence retention (P0 producer repairs
# R1/R2, 2026-10-01). Budgets are serialized UTF-8 BYTES, never character
# counts; head/tail slices land on character boundaries (byte-slice then
# lossy-decode drops at most the one partial codepoint at the boundary,
# so localized diagnostics stay byte-faithful); control lines (markers)
# are ASCII-safe. Shared by _spill_large_logs (R1) and _run_process (R2).
# ===========================================================================

RESULT_EXCERPT_HEAD_BYTES = 1024
RESULT_EXCERPT_TAIL_BYTES = 1024
# a task's raw captured output is retained as durable evidence when the
# task FAILED or the captured bytes exceed this threshold (declared
# decision, not happenstance)
RAW_LOG_RETAIN_THRESHOLD_BYTES = 65536
# B7a (four-element law): builtin FAIL listings (diff-check findings,
# clean-tree dirty paths) are bounded to the D3 inline-finding budget of
# 8 with an explicit omission count; the full listing command is named
BUILTIN_FINDINGS_SHOWN = 8


def _utf8_prefix(text: str, budget: int) -> str:
    """Longest character-boundary prefix of `text` whose UTF-8 encoding
    fits in `budget` bytes."""
    if budget <= 0 or not text:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    return encoded[:budget].decode("utf-8", errors="ignore")


def _utf8_suffix(text: str, budget: int) -> str:
    """Character-boundary suffix of `text` of at most `budget` UTF-8 bytes."""
    if budget <= 0 or not text:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    return encoded[-budget:].decode("utf-8", errors="ignore")


def _excerpt_with_marker(text: str, full_where: str) -> tuple[str, int]:
    """(bounded excerpt, omitted byte count) for one captured text; when
    bytes are omitted, an ASCII marker names where the full output lives.
    head + tail + omitted == total UTF-8 bytes always holds."""
    total = len(text.encode("utf-8"))
    head = _utf8_prefix(text, RESULT_EXCERPT_HEAD_BYTES)
    tail = _utf8_suffix(text, RESULT_EXCERPT_TAIL_BYTES)
    omitted = total - len(head.encode("utf-8")) - len(tail.encode("utf-8"))
    if omitted <= 0:
        return text, 0
    marker = f"[... {omitted} bytes omitted; {full_where} ...]"
    return f"{head}\n{marker}\n{tail}", omitted


def _retain_raw_log(name: str, raw: bytes) -> tuple[str, str, int] | None:
    """Copy a task's raw captured bytes to the operator evidence area
    (the same tempfile/qiven-operator directory _spill_large_logs uses)
    under a collision-resistant name. Returns (path, sha256, byte count)
    or None when the copy fails - retention is evidence, never a gate: a
    failed copy must not change the task verdict."""
    try:
        directory = Path(tempfile.gettempdir()) / "qiven-operator"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
        evidence = directory / f"qiven-task-{safe_name}-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}.log"
        evidence.write_bytes(raw)
        return str(evidence), hashlib.sha256(raw).hexdigest(), len(raw)
    except OSError:
        return None


def _run_process(name: str, spec: dict[str, Any], console: Console) -> Result:
    """Run ONE declared task child under per-task process custody: a Job
    Object (KILL_ON_JOB_CLOSE + process cap) held by this operator. The
    tree cannot outlive the task: on primary exit, leftovers (the MSBuild
    node-reuse class) are terminated after the output grace; if THIS
    operator dies mid-task, the kernel kills the tree via handle close."""
    started = time.monotonic()
    console.emit("run", name)
    try:
        argv = _argv_for_task(spec)
    except OperatorError as exc:
        console.emit("fail", f"{name}: {exc}")
        return Result(name, "fail", 2, detail=str(exc))

    env = _child_environment()
    log_fd = None
    job = None
    process_handle = None
    process = None
    returncode: int | None = None
    with tempfile.NamedTemporaryFile(prefix="qiven-operator-", suffix=".log", delete=False) as handle:
        log_path = Path(handle.name)
    try:
        if os.name == "nt":
            job = _job_create()
            log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            nul_fd = os.open("NUL", os.O_RDWR)
            try:
                # CREATE_SUSPENDED -> assign -> resume: zero-race custody
                # (no grandchild can be born before the primary is in the
                # job, unlike the Popen-then-assign pattern)
                process_handle, thread_handle, _pid = _win_spawn(
                    argv, ROOT, env, log_fd, nul_fd,
                    _child_creationflags() | WIN_CREATE_SUSPENDED,
                )
            finally:
                os.close(log_fd)
                os.close(nul_fd)
            kernel32, _ = _win_kernel32()
            kernel32.AssignProcessToJobObject(job, process_handle)
            kernel32.ResumeThread(thread_handle)
            kernel32.CloseHandle(thread_handle)
        else:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    argv, cwd=ROOT, env=env, stdout=log,
                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        while True:
            if os.name == "nt":
                if _wait_handle(process_handle, 100) == "signaled":
                    returncode = _exit_code_of_handle(process_handle)
                    break
            else:
                returncode = process.poll()
                if returncode is not None:
                    break
                time.sleep(0.1)
            now = time.monotonic()
            if now >= next_heartbeat:
                console.emit("wait", f"{name}: running for {now - started:.0f}s")
                next_heartbeat = now + HEARTBEAT_SECONDS
        duration = time.monotonic() - started
        # completion reaps the task tree (bounded grace for late flush)
        time.sleep(CUSTODY_REAP_GRACE_SECONDS)
        # raw bytes FIRST (P0 repair R2): the decode-with-replacement view
        # below is for rendering only and must never overwrite or stand in
        # for the captured bytes; the retained artifact (if any) carries
        # the original bytes exactly.
        raw_output = log_path.read_bytes()
        output = raw_output.decode("utf-8", errors="replace")
        if os.name == "nt":
            _job_terminate(job, int(returncode))
        else:
            import signal

            try:
                os.killpg(int(process.pid), signal.SIGKILL)
            except OSError:
                pass
        assert returncode is not None
        # retention is a declared-threshold decision: task failure OR
        # captured bytes over RAW_LOG_RETAIN_THRESHOLD_BYTES (never
        # happenstance, and never a gate - a failed copy degrades to no
        # artifact, reported truthfully below)
        evidence: tuple[str, str, int] | None = None
        if returncode != 0 or len(raw_output) > RAW_LOG_RETAIN_THRESHOLD_BYTES:
            evidence = _retain_raw_log(name, raw_output)
        if returncode == 0:
            console.emit("ok", f"{name} ({duration:.2f}s)")
            if console.verbose:
                console.block(output)
            return Result(name, "pass", 0, duration, output=output,
                          evidence_path=evidence[0] if evidence else None,
                          evidence_sha256=evidence[1] if evidence else None,
                          evidence_bytes=evidence[2] if evidence else None)
        _emit_failure_guidance(console, "task")
        console.emit("fail", f"{name}: exit {returncode} ({duration:.2f}s)")
        # bounded failure rendering (P0 repair R2): head/tail excerpt plus
        # one line naming the retained evidence (or the honest byte count
        # when retention failed) - the unbounded body never hits the agent
        # console even though it survives in the artifact/Result
        excerpt, _ = _excerpt_with_marker(
            output,
            "full output in retained evidence" if evidence else "full output captured but not retained",
        )
        if evidence:
            evidence_note = (f"full output retained at: {evidence[0]} "
                             f"({evidence[2]} bytes, sha256 {evidence[1]})")
        else:
            evidence_note = (f"captured output: {len(raw_output)} bytes "
                             "(not retained: evidence copy failed)")
        console.block(f"{excerpt}\n{evidence_note}")
        # B5 (four-element law): the task FAIL carrier names WHY (typed
        # rule: a declared task must exit 0) and the mechanical NEXT route -
        # DIAGNOSE (D3: unexpected task failures; the mechanism does not
        # mechanically know the correction) - with the evidence read-back
        # handle and the exact re-run command. The WHAT line and the
        # excerpt/evidence note above stay byte-stable.
        read_route = (f"`qiven evidence-read {evidence[0]}` for the full bytes"
                      if evidence else "re-run with --verbose for the full output")
        console.block(
            f"  rule: operator/task-failed (a declared task must exit 0; {name} exited\n"
            f"  {returncode} - unexpected-failure class, correction not mechanically known)\n"
            f"  NEXT: DIAGNOSE - classify the failure from the excerpt/evidence above,\n"
            f"  {read_route}, fix at the\n"
            f"  cause, then re-run `qiven run {name}`; do NOT weaken the gate or re-run blind"
        )
        return Result(name, "fail", int(returncode), duration, output=output,
                      evidence_path=evidence[0] if evidence else None,
                      evidence_sha256=evidence[1] if evidence else None,
                      evidence_bytes=evidence[2] if evidence else None)
    except OSError as exc:
        detail = f"could not start process: {exc}"
        console.emit("fail", f"{name}: {detail}")
        return Result(name, "fail", 2, time.monotonic() - started, detail=detail)
    finally:
        if os.name == "nt":
            kernel32, _ = _win_kernel32()
            if process_handle:
                kernel32.CloseHandle(process_handle)
            if job:
                kernel32.CloseHandle(job)
        try:
            log_path.unlink()
        except OSError:
            pass


def _builtin(name: str, spec: dict[str, Any], console: Console, expect_head: str | None) -> Result:
    started = time.monotonic()
    console.emit("run", name)
    kind = spec.get("builtin")
    if kind == "exact_head":
        expected = expect_head or spec.get("expected")
        if not expected:
            console.emit("ok", f"{name}: no expected SHA supplied")
            return Result(name, "pass", 0, time.monotonic() - started)
        completed = _git("rev-parse", "HEAD")
        actual = completed.stdout.strip()
        if completed.returncode or actual != expected:
            detail = f"expected {expected}, got {actual or '<unresolved>'}"
            _emit_failure_guidance(console, "exact-head")
            console.emit("fail", f"{name}: {detail}")
            # B5 (four-element law): the mismatch FAIL names the rule, the
            # compared values and the FIX route; the pinned detail line
            # above stays byte-stable
            console.block(
                f"  rule: operator/exact-head-mismatch (string-exact compare of the FULL\n"
                f"  40-char sha - never name resolution or prefix matching)\n"
                f"  evidence: expected {expected}\n"
                f"            got {actual or '<unresolved>'}  (git rev-parse HEAD)\n"
                f"  NEXT: FIX - verify the intended full sha, commit or stash new work,\n"
                f"  then re-run with the exact 40-char sha; do NOT bypass or re-point\n"
                f"  the check"
            )
            return Result(name, "fail", 1, time.monotonic() - started, detail=detail, output=completed.stdout)
    elif kind == "gate_proof":
        # pit P-53: merge-class publication requires a recorded full-gate
        # PASS for the EXACT head being published; a missing or stale receipt
        # fails closed (the A3 masking class: scoped gates are not the gate)
        gate_name = str(spec.get("gate") or "")
        head = _git("rev-parse", "HEAD").stdout.strip()
        receipt_file = _receipt_path(gate_name, head)
        if not gate_name:
            detail = "gate_proof builtin requires a 'gate' name"
            console.emit("fail", f"{name}: {detail}")
            return Result(name, "fail", 1, time.monotonic() - started, detail=detail)
        if not receipt_file.is_file():
            # B7a (four-element law): the FAIL carrier names the P-53 law,
            # the receipt locator and the exact re-run (prefix bytes pinned
            # by p0_closeout_test EC6: "no <gate> PASS receipt ...")
            detail = f"no {gate_name} PASS receipt for exact head {head[:12]}"
            console.emit("fail", f"{name}: {detail}")
            console.block(
                f"  rule: operator/gate-proof-missing-receipt (pit P-53: merge-class\n"
                f"  publication requires a recorded full-gate PASS for the EXACT head;\n"
                f"  a scoped or stale gate is not the gate)\n"
                f"  evidence: expected receipt at: {receipt_file} (absent)\n"
                f"  NEXT: FIX - run `qiven gate --name {gate_name}` at this head and\n"
                f"  let it write the PASS receipt, then re-run this proof"
            )
            return Result(name, "fail", 1, time.monotonic() - started, detail=detail)
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        if receipt.get("status") != "pass" or receipt.get("head") != head:
            detail = f"receipt for {head[:12]} is not a matching PASS"
            console.emit("fail", f"{name}: {detail}")
            console.block(
                f"  rule: operator/gate-proof-stale-receipt (pit P-53: the proof is a\n"
                f"  full-gate PASS recorded for the EXACT 40-char head)\n"
                f"  evidence: receipt at {receipt_file} has status="
                f"{receipt.get('status')!r}, head={str(receipt.get('head'))[:12]}\n"
                f"  NEXT: FIX - run `qiven gate --name {gate_name}` at the current\n"
                f"  head {head[:12]}, then re-run this proof"
            )
            return Result(name, "fail", 1, time.monotonic() - started, detail=detail)
        console.emit("ok", f"{name}: {gate_name} PASS @ {head[:12]} "
                           f"({receipt.get('timestamp')})")
        return Result(name, "pass", 0, time.monotonic() - started)
    elif kind == "git_diff_check":
        base = str(spec.get("base", "origin/main"))
        completed = _git("diff", "--check", f"{base}...HEAD")
        if completed.returncode:
            # B7a (four-element law): typed rule + BOUNDED listing (the raw
            # git block was unbounded) + the exact FIX route
            lines = [ln for ln in completed.stdout.splitlines() if ln.strip()]
            shown, omitted = lines[:BUILTIN_FINDINGS_SHOWN], len(lines) - min(
                len(lines), BUILTIN_FINDINGS_SHOWN)
            block = "\n".join(shown)
            if omitted > 0:
                block += (f"\n  [evidence: first {len(shown)} of {len(lines)} "
                          f"finding(s); full listing: git diff --check {base}...HEAD]")
            console.emit("fail", f"{name}: git diff --check failed vs {base}...HEAD "
                                 "(rule: operator/diff-check - whitespace errors and "
                                 "conflict markers block publication)")
            console.block(block)
            console.emit("fail", f"{name}: NEXT: FIX - fix the whitespace/conflict "
                                 f"markers at the paths above, then re-run; full "
                                 f"listing: git diff --check {base}...HEAD")
            return Result(name, "fail", completed.returncode, time.monotonic() - started, output=completed.stdout)
    elif kind == "git_clean_tree":
        completed = _git("status", "--porcelain=v1", "--untracked-files=all")
        dirty = completed.stdout.strip()
        if completed.returncode or dirty:
            detail = "working tree is not clean" if dirty else "git status failed"
            # B7a (four-element law): typed rule + BOUNDED dirty listing
            # (was unbounded) + the commit/stash FIX route; the detail
            # string stays pinned by operator-test G1.clean-tree-detail
            lines = [ln for ln in completed.stdout.splitlines() if ln.strip()]
            shown, omitted = lines[:BUILTIN_FINDINGS_SHOWN], len(lines) - min(
                len(lines), BUILTIN_FINDINGS_SHOWN)
            block = "\n".join(shown)
            if omitted > 0:
                block += (f"\n  [evidence: first {len(shown)} of {len(lines)} "
                          f"dirty path(s); full listing: git status --porcelain=v1 "
                          f"--untracked-files=all]")
            console.emit("fail", f"{name}: {detail} (rule: operator/clean-tree - "
                                 "gates publish from a clean tree)")
            console.block(block)
            if dirty:
                console.emit("fail", f"{name}: NEXT: FIX - commit or stash the paths "
                                     "above, then re-run; never force the check green")
            else:
                # git itself failed (rc != 0, no listing): the clean-tree
                # law still fails closed; DIAGNOSE names the real defect
                console.emit("fail", f"{name}: NEXT: DIAGNOSE - git status itself "
                                     "failed; run `git status --porcelain=v1 "
                                     "--untracked-files=all` directly to see the git "
                                     "error, fix that first, then re-run")
            return Result(name, "fail", 1, time.monotonic() - started, detail=detail, output=completed.stdout)
    else:
        detail = f"unknown builtin: {kind}"
        console.emit("fail", f"{name}: {detail}")
        return Result(name, "fail", 2, time.monotonic() - started, detail=detail)
    duration = time.monotonic() - started
    console.emit("ok", f"{name} ({duration:.2f}s)")
    return Result(name, "pass", 0, duration)


def _record_duration(result: Result, kind: str) -> None:
    """Append one task-duration event to the durable durations log (the
    evidence base for long-class routing decisions; owner 2026-09-23).
    Never raises: logging must not gate."""
    try:
        path = ROOT / ".generated-temp" / "operator" / "task-durations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "at": _utc_now(),
            "kind": kind,
            "task": result.name,
            "status": result.status,
            "duration_seconds": round(result.duration_seconds, 3),
            "head": _git_head_or_empty(),
        }
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _git_head_or_empty() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return completed.stdout.strip()[:12] if completed.returncode == 0 else ""
    except Exception:
        return ""


def _run_task(name: str, tasks: dict[str, Any], console: Console, expect_head: str | None) -> Result:
    spec = tasks.get(name)
    if not isinstance(spec, dict):
        detail = _unknown_task_error(name, tasks)
        console.emit("fail", detail)
        return Result(name, "fail", 2, detail=detail)
    if "builtin" in spec:
        result = _builtin(name, spec, console, expect_head)
    else:
        result = _run_process(name, spec, console)
    _record_duration(result, kind="task")
    return result


def _unknown_task_error(name: str, tasks: dict[str, Any]) -> str:
    available = ", ".join(sorted(tasks)) if tasks else "none"
    return f"unknown task: {name} (available: {available})"


def _receipt_path(gate: str, head: str) -> Path:
    # receipts are proof-of-PASS for an exact head, not evidence archives;
    # they live in the repo-local git-ignored temp area per the
    # generated-temp convention (tool subtree: operator/receipts)
    return ROOT / ".generated-temp" / "operator" / "receipts" / f"{gate}-{head}.json"


def _write_gate_receipt(payload: dict[str, Any]) -> None:
    if payload.get("status") != "pass":
        return
    try:
        path = _receipt_path(str(payload.get("gate")), str(payload.get("head")))
        path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            "gate": payload.get("gate"),
            "head": payload.get("head"),
            "status": payload.get("status"),
            "timestamp": _utc_now(),
            "tasks": [
                {"name": r.get("name"), "status": r.get("status"),
                 "duration_seconds": r.get("duration_seconds")}
                for r in payload.get("results", [])
            ],
        }
        path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )
    except OSError:
        # a receipt that cannot be written degrades to no-proof-at-merge-time
        # (merge-proof then fails), which is the fail-closed direction
        pass


# ===========================================================================
# Common Record v1 emission (ADR-0060 D3; the B+D semantics + projection
# batch, 2026-10-02). Records are ADDITIVE artifacts: the existing human
# CLI output, exit codes and receipt JSON stay byte-compatible; the
# record is one additional file (plus one additive FAIL summary line in
# human gate mode). Emission is evidence, never a gate: a record that
# cannot be written degrades to no record (fail-closed for proof, the
# same law as _write_gate_receipt), which is why every emitter swallows
# OSError/ValueError - record construction must never break an operation
# whose result is already decided.
# ===========================================================================

def _new_operation_id() -> str:
    """Collision-resistant operation id (ADR-0060 D6: stamp + pid + rand)."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{os.getpid():08d}-{os.urandom(3).hex()}"


def _records_dir() -> Path:
    # records sit beside the receipts subtree (same repo-local generated
    # temp area, git-ignored, per the generated-temp convention)
    return ROOT / ".generated-temp" / "operator" / "records"


def _write_common_record(record: "_cr.CommonRecord", filename: str) -> str | None:
    try:
        path = _records_dir() / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_cr.serialize(record), encoding="utf-8", newline="\n")
        return str(path)
    except (OSError, ValueError):
        return None


def _emit_gate_record(payload: dict[str, Any], results: list[Result],
                      expect_head: str | None, repository: str | None) -> dict[str, Any] | None:
    """One Common Record per gate invocation (PASS and FAIL) at
    .generated-temp/operator/records/<gate>-<head>-<operation-id>.json.
    Returns the record's next_action section (for the additive human FAIL
    summary line) or None when emission was skipped."""
    try:
        gate_name = str(payload.get("gate"))
        head = str(payload.get("head"))
        opid = _new_operation_id()
        executed = [r.name for r in results if r.status != "not_run"]
        not_executed = [
            _cr.CoverageItem(name=r.name, reason=r.detail or "not started")
            for r in results
            if r.status == "not_run"
        ]
        failed = [r for r in results if r.returncode]
        exact_head_failed = [
            r for r in failed if r.name == "exact-head" and expect_head
        ]

        findings: list[_cr.Finding] = []
        for result in failed:
            if result.name == "exact-head":
                findings.append(_cr.Finding(
                    rule_id="operator/exact-head-mismatch",
                    location=_cr.FindingLocation(path="git HEAD"),
                    actual=result.detail or "HEAD does not match --expect-head",
                    expected=f"HEAD == {expect_head}",
                    contract_revision="unavailable",
                ))
            else:
                findings.append(_cr.Finding(
                    rule_id="operator/stage-failed",
                    location=_cr.FindingLocation(path=result.name),
                    actual=result.detail or f"exit {result.returncode}",
                    expected="exit 0",
                    contract_revision="unavailable",
                ))
        findings.sort(key=lambda f: (f.rule_id, f.location.path))

        if not failed:
            next_action = _cr.next_action_for("pass")
        elif exact_head_failed:
            next_action = _cr.next_action_for(
                "invocation-rejected",
                "exact-head is a string compare on the FULL 40-char sha: pass the "
                "complete sha to --expect-head (commit/stash first if HEAD moved, "
                "then re-run at the new head)",
            )
        else:
            next_action = _cr.next_action_for(
                "unexpected-task-failure",
                "classify the failing task's failure class before any repair; do "
                "not weaken the gate (docs/engineering/execution-protocol.md)",
            )

        evidence: list[_cr.Evidence] = []
        for result in results:
            if result.evidence_path:
                digest = result.evidence_sha256 or ""
                if digest and not digest.startswith("sha256:"):
                    digest = f"sha256:{digest}"
                evidence.append(_cr.Evidence(
                    locator=result.evidence_path,
                    digest=digest or None,
                    byte_count=result.evidence_bytes,
                    layout="stdout+stderr-merged",
                    completeness="complete",
                ))
        receipt_path = _receipt_path(gate_name, head)
        if not failed and receipt_path.is_file():
            try:
                receipt_bytes = receipt_path.read_bytes()
                evidence.append(_cr.Evidence(
                    locator=str(receipt_path),
                    digest=f"sha256:{hashlib.sha256(receipt_bytes).hexdigest()}",
                    byte_count=len(receipt_bytes),
                    layout="json",
                    completeness="complete",
                ))
            except OSError:
                pass  # receipt evidence degrades to absent, never gates

        if not failed:
            payload_ref = _cr.Payload(kind="gate-receipt", locator=str(receipt_path))
            reference = str(receipt_path) if receipt_path.is_file() else (
                f"none (receipt write degraded at {receipt_path})")
        else:
            first_artifact = next(
                (r.evidence_path for r in failed if r.evidence_path), None
            )
            payload_ref = _cr.Payload(
                kind="gate-machine-json",
                locator=first_artifact or "unavailable",
            )
            reference = first_artifact or "none retained"

        devkit_node = payload.get("devkit_node")
        record = _cr.CommonRecord(
            record_kind="gate-run",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=opid,
                repository=repository or ROOT.name,
                cwd=str(ROOT),
                invocation="qiven gate " + gate_name + (
                    f" --expect-head {expect_head}" if expect_head else ""),
                gate=gate_name,
                selected_revision=(
                    devkit_node
                    if isinstance(devkit_node, str) and len(devkit_node) == 40
                    else None
                ),
                executing_revision=head if len(head) == 40 else None,
                workspace_generation=(
                    payload.get("workspace_generation")
                    if isinstance(payload.get("workspace_generation"), str)
                    and payload["workspace_generation"].startswith("sha256:")
                    else None
                ),
            ),
            observation=_cr.Observation(coherence="coherent"),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state="completed"),
            domain_outcome=_cr.DomainOutcome(
                outcome="passed" if not failed else "failed",
                exit_code=0 if not failed else 1,
            ),
            coverage=_cr.Coverage(
                collection="complete" if not not_executed else "partial",
                executed=executed,
                not_executed=not_executed,
            ),
            next_action=next_action,
            retry_state=_cr.RetryState(side_effects="not_started"),
            payload=payload_ref,
            findings=findings,
            evidence=evidence,
        )
        _write_common_record(record, f"{gate_name}-{head}-{opid}.json")
        summary = asdict(next_action)
        summary["reference"] = reference
        try:
            # B1: the bounded model view of the SAME record rides the
            # FAIL carrier (additive block after the selector-law line).
            summary["projection"] = _rp.project(record)
        except Exception:
            summary["projection"] = None
        return summary
    except (OSError, ValueError, KeyError):
        # never-must-gate boundary: record construction failure must not
        # alter a gate result that already ran (standard §4.2)
        return None


def _emit_run_record(payload: dict[str, Any], results: list[Result],
                     repository: str | None) -> dict[str, Any] | None:
    """One Common Record per `qiven run` invocation (PASS and FAIL) at
    .generated-temp/operator/records/run-<head>-<operation-id>.json
    (B1; mirrors _emit_gate_record without the gate/receipt legs)."""
    try:
        head = str(payload.get("head") or "")
        opid = _new_operation_id()
        executed = [r.name for r in results if r.status != "not_run"]
        not_executed = [
            _cr.CoverageItem(name=r.name, reason=r.detail or "not started")
            for r in results
            if r.status == "not_run"
        ]
        failed = [r for r in results if r.returncode]

        findings = [
            _cr.Finding(
                rule_id="operator/stage-failed",
                location=_cr.FindingLocation(path=r.name),
                actual=r.detail or f"exit {r.returncode}",
                expected="exit 0",
                contract_revision="unavailable",
            )
            for r in failed
        ]
        findings.sort(key=lambda f: (f.rule_id, f.location.path))

        if not failed:
            next_action = _cr.next_action_for("pass")
        else:
            next_action = _cr.next_action_for(
                "unexpected-task-failure",
                "classify the failing task's failure class before any repair; "
                "the task contract lives in .qiven/operator.json (declare the "
                "same task in a gate for receipt+coverage, or re-run single "
                "tasks while diagnosing)",
            )

        evidence = [
            _cr.Evidence(
                locator=r.evidence_path,
                digest=(f"sha256:{r.evidence_sha256}" if r.evidence_sha256 else None),
                byte_count=r.evidence_bytes,
                layout="stdout+stderr-merged",
                completeness="complete",
            )
            for r in results
            if r.evidence_path
        ]
        first_artifact = next(
            (r.evidence_path for r in failed if r.evidence_path), None
        )
        payload_ref = _cr.Payload(
            kind="run-machine-json", locator=first_artifact or "unavailable"
        )
        devkit_node = payload.get("devkit_node")
        record = _cr.CommonRecord(
            record_kind="task-run",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=opid,
                repository=repository or ROOT.name,
                cwd=str(ROOT),
                invocation="qiven run " + " ".join(str(r.name) for r in results),
                selected_revision=(
                    devkit_node
                    if isinstance(devkit_node, str) and len(devkit_node) == 40
                    else None
                ),
                executing_revision=head if len(head) == 40 else None,
                workspace_generation=(
                    payload.get("workspace_generation")
                    if isinstance(payload.get("workspace_generation"), str)
                    and payload["workspace_generation"].startswith("sha256:")
                    else None
                ),
            ),
            observation=_cr.Observation(coherence="coherent"),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state="completed"),
            domain_outcome=_cr.DomainOutcome(
                outcome="passed" if not failed else "failed",
                exit_code=0 if not failed else 1,
            ),
            coverage=_cr.Coverage(
                collection="complete" if not not_executed else "partial",
                executed=executed,
                not_executed=not_executed,
            ),
            next_action=next_action,
            retry_state=_cr.RetryState(side_effects="not_started"),
            payload=payload_ref,
            findings=findings,
            evidence=evidence,
        )
        _write_common_record(record, f"run-{head}-{opid}.json")
        summary = asdict(next_action)
        summary["reference"] = first_artifact or "none retained"
        try:
            summary["projection"] = _rp.project(record)
        except Exception:
            summary["projection"] = None
        return summary
    except (OSError, ValueError, KeyError):
        return None


def _emit_ci_dispatch_record(payload: dict[str, Any],
                             repository: str | None) -> None:
    """One Common Record per successful `qiven ci start` dispatch
    (B1): the carrier's NEXT line names the watch handle, and the record
    carries the same next-action mechanically."""
    try:
        head = str(payload.get("head") or "")
        opid = _new_operation_id()
        profile = str(payload.get("profile") or "")
        # candidate law (2026-10-03): the record carries the SELECTED
        # candidate (selected_revision — same field the run record uses for
        # the chosen node) and the invocation materializes the flags so the
        # last-run-as-record semantics show the explicit selection even in
        # the default-HEAD case; workspace_ref rides the same invocation.
        candidate = str(payload.get("candidate") or "")
        workspace_ref = payload.get("workspace_ref")
        invocation = f"qiven ci start {profile} --candidate {candidate}".rstrip()
        if workspace_ref:
            invocation += f" --workspace-ref {workspace_ref}"
        watch_handle = f"qiven ci watch {profile} (run_in_background)"
        record = _cr.CommonRecord(
            record_kind="ci-dispatch",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=opid,
                repository=repository or ROOT.name,
                cwd=str(ROOT),
                invocation=invocation,
                selected_revision=(
                    candidate
                    if len(candidate) == 40 and set(candidate) <= _CI_CANDIDATE_HEX
                    else None
                ),
                executing_revision=head if len(head) == 40 else None,
            ),
            observation=_cr.Observation(coherence="coherent"),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state="completed"),
            domain_outcome=_cr.DomainOutcome(outcome="passed", exit_code=0),
            coverage=_cr.Coverage(collection="complete", executed=["ci-dispatch"],
                                  not_executed=[]),
            next_action=_cr.next_action_for("operation-running", watch_handle),
            retry_state=_cr.RetryState(side_effects="in_progress"),
            payload=_cr.Payload(kind="ci-dispatch-payload",
                                locator=str(payload.get("url") or "unavailable")),
        )
        _write_common_record(record, f"ci-dispatch-{head}-{opid}.json")
    except (OSError, ValueError, KeyError):
        return None


def _emit_ci_watch_record(payload: dict[str, Any],
                          repository: str | None) -> str | None:
    """One Common Record per `qiven ci watch` terminal observation
    (B1). Returns the additive NEXT-action suffix for the FAIL carrier
    line (None on success or construction failure)."""
    try:
        verdict = str(payload.get("conclusion") or "unknown")
        head = str(payload.get("head") or "")
        opid = _new_operation_id()
        profile = str(payload.get("profile") or "")
        run_id = str(payload.get("run_id") or "")
        repo = str(payload.get("repository") or "")
        if verdict == "success":
            next_action = _cr.next_action_for("pass")
            findings = []
        else:
            gh_handle = (
                f"read the failing job log: gh run view {run_id} --repo {repo} "
                f"--log-failed (classify the failure class before any repair; "
                f"do not re-dispatch blind)"
            )
            next_action = _cr.next_action_for("unexpected-task-failure", gh_handle)
            findings = [
                _cr.Finding(
                    rule_id=f"ci/conclusion-{verdict}",
                    location=_cr.FindingLocation(path=f"gh run {run_id}"),
                    actual=f"workflow conclusion={verdict}",
                    expected="conclusion=success",
                    contract_revision="unavailable",
                )
            ]
        record = _cr.CommonRecord(
            record_kind="ci-watch",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=opid,
                repository=repository or ROOT.name,
                cwd=str(ROOT),
                invocation=f"qiven ci watch {profile}".strip(),
                executing_revision=head if len(head) == 40 else None,
            ),
            observation=_cr.Observation(coherence="coherent"),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state="completed"),
            domain_outcome=_cr.DomainOutcome(
                outcome="passed" if verdict == "success" else "failed",
                exit_code=0 if verdict == "success" else 1,
            ),
            coverage=_cr.Coverage(collection="complete", executed=["ci-watch"],
                                  not_executed=[]),
            next_action=next_action,
            retry_state=_cr.RetryState(side_effects="unknown"),
            payload=_cr.Payload(kind="ci-watch-payload",
                                locator=str(payload.get("url") or "unavailable")),
            findings=findings,
        )
        _write_common_record(record, f"ci-watch-{head}-{opid}.json")
        if verdict == "success":
            return None
        summary = asdict(next_action)
        return str(summary.get("supported_by") or "")
    except (OSError, ValueError, KeyError):
        return None


_EXEC_RECORD_MAP: dict[str, dict[str, Any]] = {
    # state -> completion/outcome/event-token; the 124 law: still-running
    # (a live run under custody) and indeterminate (no living supervisor
    # observed the exit) stay DISTINCT; deadline_reached only because the
    # WATCHDOG wrote status=expired after terminating the job (custody/
    # termination observation, never a guess from silence).
    "running":      {"completion": "running", "token": "operation-running"},
    "starting":     {"completion": "running", "token": "operation-running"},
    "reaping":      {"completion": "running", "token": "operation-running"},
    "done":         {"completion": "completed", "token": None},
    "expired":      {"completion": "deadline_reached", "token": "lease-expired"},
    "indeterminate": {"completion": "unknown", "token": "exit-unknown"},
    "orphaned":     {"completion": "unknown", "token": "unknown-side-effects"},
    "stopped":      {"completion": "cancelled", "token": "unknown-side-effects"},
    "error":        {"completion": "unknown", "token": "operator-error"},
}


def _emit_exec_record(event: str, run: dict[str, Any], state: str) -> None:
    """One Common Record for an exec lifecycle observation (start
    front-end outcomes + status observations), written to the records
    area as exec-<run-id>-<event>-<opid>.json. Existing exec output
    contracts are unchanged; the record is an additive artifact."""
    try:
        exec_id = str(run.get("id") or "unknown")
        mapping = _EXEC_RECORD_MAP.get(state)
        if mapping is None:
            return
        log_path = Path(str(run.get("log") or ""))
        log_size: int | None = None
        try:
            if log_path.is_file():
                log_size = log_path.stat().st_size
        except OSError:
            log_size = None

        exit_code = run.get("exit_code")
        if state == "done":
            token = "pass" if exit_code == 0 else "unexpected-task-failure"
        else:
            token = mapping["token"]
        deadline = str(run.get("deadline_utc") or "")
        status_handle = f"qiven exec status {exec_id}" + (
            f" (lease {deadline})" if deadline else ""
        )
        if token in ("operation-running",):
            next_action = _cr.next_action_for(token, status_handle)
        elif token in ("lease-expired", "exit-unknown", "unknown-side-effects"):
            next_action = _cr.next_action_for(
                token,
                f"{status_handle}; inspect the log {log_path if str(log_path) else '(unknown)'}; "
                "side effects unknown - never automatic mutation replay",
            )
        elif token == "operator-error":
            next_action = _cr.next_action_for(
                token, str(run.get("error") or "operator error - read the exec record")
            )
        else:
            next_action = _cr.next_action_for(token)

        side_effects = (
            "in_progress" if mapping["completion"] == "running"
            else "completed" if state == "done"
            else "unknown"
        )
        reconciliation = None
        if next_action.action == "RECONCILE":
            reconciliation = status_handle + "; qiven exec list"

        record = _cr.CommonRecord(
            record_kind="exec-run",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=_new_operation_id(),
                repository=ROOT.name,
                cwd=str(ROOT),
                invocation=" ".join(str(a) for a in (run.get("argv") or [])) or "qiven exec",
                executing_revision=(run.get("head") if isinstance(run.get("head"), str)
                                    and len(str(run.get("head"))) == 40 else None),
            ),
            observation=_cr.Observation(
                coherence="coherent" if state not in ("indeterminate", "orphaned") else "uncertain"
            ),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state=mapping["completion"]),
            domain_outcome=_cr.DomainOutcome(
                outcome=("passed" if exit_code == 0 else "failed") if state == "done"
                else "unknown",
                exit_code=exit_code if state == "done" and isinstance(exit_code, int)
                else "unavailable",
            ),
            coverage=_cr.Coverage(collection="complete", executed=["custody-observe"]),
            next_action=next_action,
            retry_state=_cr.RetryState(
                side_effects=side_effects, reconciliation=reconciliation
            ),
            payload=_cr.Payload(
                kind="exec-run-record",
                locator=str(_exec_record_path(exec_id)),
            ),
            evidence=[_cr.Evidence(
                locator=str(log_path) if str(log_path) else "unavailable",
                layout="stdout+stderr-merged",
                completeness="unknown",
                byte_count=log_size,
            )],
        )
        _write_common_record(record, f"exec-{exec_id}-{event}-{_new_operation_id()}.json")
    except (OSError, ValueError, KeyError):
        # never-must-gate boundary (standard §4.2): exec custody/output
        # contracts must never be altered by record emission
        return None


def _emit_exec_unknown_record(run_id: str) -> None:
    """One Common Record for an exec status query naming a run id that has
    no record (ADR-0060 D15 'unknown running operations'): completion
    unknown, observation unavailable (nothing about the queried run could
    be observed), next FIX naming the mechanically-known enumeration
    handle. The existing typed CLI answer (`unknown exec id`, exit 2) is
    unchanged; the record is the additive artifact."""
    try:
        record_path = _exec_record_path(run_id)
        record = _cr.CommonRecord(
            record_kind="exec-status",
            producer=_cr.Producer(id="devkit-qiven-operator", version="operator-gate-v2"),
            operation=_cr.Operation(
                id=_new_operation_id(),
                repository=ROOT.name,
                cwd=str(ROOT),
                invocation=f"qiven exec status {run_id}",
            ),
            observation=_cr.Observation(coherence="unavailable"),
            admission=_cr.Admission(state="accepted"),
            completion=_cr.Completion(state="unknown"),
            domain_outcome=_cr.DomainOutcome(outcome="unknown", exit_code="unavailable"),
            coverage=_cr.Coverage(collection="complete", executed=["record-lookup"]),
            findings=[_cr.Finding(
                rule_id="operator/unknown-exec-id",
                location=_cr.FindingLocation(path=str(record_path)),
                actual=f"no exec record exists for run id {run_id!r}",
                expected="an existing exec run record (qiven exec list enumerates them)",
                contract_revision="unavailable",
            )],
            next_action=_cr.next_action_for(
                "invocation-rejected",
                "run `qiven exec list` to enumerate known run ids; an id "
                "without a record never gains a guessed state",
            ),
            retry_state=_cr.RetryState(side_effects="unknown"),
            payload=_cr.Payload(kind="exec-status-query",
                                locator=f"qiven exec status {run_id}"),
        )
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_id)[:80]
        _write_common_record(
            record, f"exec-status-unknown-{safe or 'id'}-{_new_operation_id()}.json"
        )
    except (OSError, ValueError, KeyError):
        return


def _not_run_results(stages: list[Any], failed_stage: str) -> list[Result]:
    """Coverage reporting for stages after a fail-fast stop (P0 repair
    R3). These stages did NOT execute: status "not_run", returncode None
    (an unobserved exit is never guessed to 0 - standard §4.3). They are
    additive reporting only: the gate already fails via the failed stage,
    and `if result.returncode` counts None as neither pass nor fail, so
    the PASS/FAIL decision logic is unchanged."""
    detail = f"not started: gate stopped after failed stage {failed_stage}"
    results: list[Result] = []
    for stage in stages:
        if isinstance(stage, str):
            results.append(Result(stage, "not_run", None, detail=detail))
        elif isinstance(stage, list):
            results.extend(Result(str(item), "not_run", None, detail=detail) for item in stage)
    return results


def _run_sequence(sequence: list[Any], tasks: dict[str, Any], console: Console, expect_head: str | None) -> list[Result]:
    results: list[Result] = []
    for index, stage in enumerate(sequence):
        if isinstance(stage, str):
            result = _run_task(stage, tasks, console, expect_head)
            results.append(result)
            if result.returncode:
                # fail-fast execution is unchanged (later stages never
                # run); they are REPORTED as not_run so a consumer can
                # distinguish "gate finished" from "gate stopped here"
                results.extend(_not_run_results(sequence[index + 1:], stage))
                break
            continue
        if isinstance(stage, list) and stage and all(isinstance(item, str) for item in stage):
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(stage), thread_name_prefix="qiven") as pool:
                futures = {name: pool.submit(_run_task, name, tasks, console, expect_head) for name in stage}
                stage_results = [futures[name].result() for name in stage]
            results.extend(stage_results)
            failed_names = ",".join(result.name for result in stage_results if result.returncode)
            if failed_names:
                results.extend(_not_run_results(sequence[index + 1:], failed_names))
                break
            continue
        raise OperatorError(f"invalid gate stage: {stage!r}")
    return results


def _remote_repo() -> str:
    completed = _git("remote", "get-url", "origin")
    if completed.returncode:
        raise OperatorError("cannot resolve git remote 'origin'")
    value = completed.stdout.strip()
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    elif "github.com/" in value:
        value = value.split("github.com/", 1)[1]
    else:
        raise OperatorError(f"origin is not a github.com repository: {value}")
    if value.endswith(".git"):
        value = value[:-4]
    if value.count("/") != 1:
        raise OperatorError(f"cannot parse GitHub repository from origin: {value}")
    return value


def _current_branch() -> str:
    completed = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    branch = completed.stdout.strip()
    if completed.returncode or not branch:
        raise OperatorError("CI dispatch requires a named local branch")
    return branch


def _head() -> str:
    completed = _git("rev-parse", "HEAD")
    if completed.returncode:
        raise OperatorError("cannot resolve HEAD")
    return completed.stdout.strip()


def _workspace_identity() -> dict[str, str | None | bool]:
    """WR-6 (ADR-0052 doc 02): every Operator invocation reports the
    WorkspaceGeneration, the exact Devkit node selected by the lock AND
    the Devkit HEAD actually executing (with an explicit drift marker
    when they differ - the field must be true evidence in exactly the
    drift case it exists to expose). The control locator is
    QIVEN_WORKSPACE_CONTROL or the workspace sibling; outside a
    workspace the fields report None with a standalone note (visible,
    never guessed). Reporting is evidence - revision ENFORCEMENT stays
    in the launcher's bootstrap identity-check."""
    operator_checkout = Path(__file__).resolve().parents[1]
    head_probe = _run_capture(["git", "rev-parse", "HEAD"], cwd=operator_checkout)
    executing_head = head_probe.stdout.strip() if head_probe.returncode == 0 else "<unreadable>"
    control = Path(os.environ.get("QIVEN_WORKSPACE_CONTROL",
                                  ROOT.parent / "qiven-workspace")).resolve()
    lock_path = control / "workspace.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"workspace_generation": None, "devkit_node": None,
                "devkit_head": executing_head, "devkit_drift": False,
                "workspace_mode": "standalone (no workspace lock at the control locator)"}
    node = lock.get("nodes", {}).get("qiven-devkit")
    commit = node.get("commit") if isinstance(node, dict) else None
    if not isinstance(commit, str) or len(commit) != 40:
        return {"workspace_generation": None, "devkit_node": None,
                "devkit_head": executing_head, "devkit_drift": False,
                "workspace_mode": "standalone (lock has no qiven-devkit node)"}
    return {"workspace_generation": str(lock.get("generation")),
            "devkit_node": commit,
            "devkit_head": executing_head,
            "devkit_drift": executing_head != commit,
            "workspace_mode": "workspace"}


def _workspace_identity_fields(payload: dict[str, Any]) -> None:
    identity = _workspace_identity()
    payload.update(identity)


def _remote_branch_head(branch: str) -> str:
    ref = f"refs/heads/{branch}"
    completed = _git("ls-remote", "--heads", "origin", ref)
    if completed.returncode:
        raise OperatorError(f"cannot resolve remote branch origin/{branch}")
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        if not lines:
            raise OperatorError(f"remote branch origin/{branch} does not exist")
        raise OperatorError(f"remote branch origin/{branch} resolved ambiguously")
    parts = lines[0].split()
    if len(parts) != 2 or parts[1] != ref:
        raise OperatorError(f"unexpected ls-remote result for origin/{branch}")
    return parts[0]


# CI candidate law (2026-10-03 workflow redesign): the redesigned
# workflow_dispatch gates on input candidate = full 40-hex SHA of the repo
# commit under test (typed failure by design without it). This dispatcher
# tool carries the WHAT+WHY+evidence+NEXT for its own candidate selection:
# the input is ALWAYS selected explicitly here (exact-head law — default
# HEAD resolved by this tool, never a workflow-side fallback) and never
# dispatched empty or malformed.
_CI_CANDIDATE_HEX = set("0123456789abcdef")


def _require_ci_candidate(profile: str, value: str, source: str) -> str:
    """Validate one candidate selection: exactly 40 hex chars, normalized
    lowercase. Typed four-element refusal otherwise (never dispatched)."""
    candidate = value.strip().lower()
    if len(candidate) == 40 and set(candidate) <= _CI_CANDIDATE_HEX:
        return candidate
    raise OperatorError(
        f"ci:{profile}: dispatch refused - candidate is not a full 40-hex SHA"
        f" (got {len(candidate)} chars: '{value}')"
        " - WHY: the redesigned workflow_dispatch REQUIRES input candidate ="
        " the full 40-hex commit SHA under test (typed failure by design),"
        " selected explicitly by this dispatcher - never a workflow-side fallback"
        f" - evidence: {source}='{value}'"
        " - NEXT action: FIX - pass --candidate <full-40-hex-sha> (an"
        " abbreviated sha fails even when it names the same commit), or omit"
        " the flag to dispatch the repository's current HEAD"
    )


def _ci_start(config: dict[str, Any], profile: str, console: Console,
              candidate: str | None = None,
              workspace_ref: str | None = None) -> dict[str, Any]:
    ci = config.get("ci", {})
    spec = ci.get(profile) if isinstance(ci, dict) else None
    if not isinstance(spec, dict):
        raise OperatorError(f"unknown CI profile: {profile}")
    inputs = spec.get("inputs", {})
    if not isinstance(inputs, dict):
        raise OperatorError("CI profile inputs must be an object")
    # CANDIDATE selection (before any dispatch surface is touched): default
    # is the invoking repository's current HEAD — a DELIBERATE explicit
    # selection resolved and recorded by this tool, not a workflow-side
    # fallback; --candidate overrides it. Both paths validate 40-hex and
    # fail typed with nothing dispatched.
    if candidate is None:
        try:
            head_probe = _head()
        except OperatorError as exc:
            raise OperatorError(
                f"ci:{profile}: dispatch refused - the default candidate"
                " (current HEAD) could not be resolved"
                " - WHY: the redesigned workflow_dispatch REQUIRES input"
                " candidate = the full 40-hex commit SHA under test, and this"
                " dispatcher selects it explicitly - a detached or invalid"
                " HEAD leaves nothing lawful to send"
                f" - evidence: git rev-parse HEAD failed in {ROOT}: {exc}"
                " - NEXT action: FIX - repair the checkout (attach/commit the"
                " detached HEAD), or pass --candidate <full-40-hex-sha>"
                " explicitly",
                # forward the structured recovery channel when the wrapped
                # failure carried one (a re-raise must not drop it)
                next_action=exc.next_action,
            ) from exc
        selected_candidate = _require_ci_candidate(profile, head_probe, "HEAD")
        candidate_origin = "head"
    else:
        selected_candidate = _require_ci_candidate(profile, candidate, "--candidate")
        candidate_origin = "flag"
    if workspace_ref is not None and not workspace_ref.strip():
        raise OperatorError(
            f"ci:{profile}: dispatch refused - --workspace-ref is empty"
            " - WHY: an empty workflow input would be dispatched as an empty"
            " string; the input is omitted entirely only when the flag is absent"
            f" - evidence: --workspace-ref='{workspace_ref}'"
            " - NEXT action: FIX - pass a real ref, or omit --workspace-ref"
            " (the workflow then uses the workspace default branch head)"
        )
    selected_workspace_ref = workspace_ref.strip() if workspace_ref is not None else None
    workflow, branch, head, repo = _ci_resolve_guard(config, profile, "ci:" + profile)
    console.emit("ok", f"ci:{profile}: origin/{branch} matches {head}")
    argv = ["gh", "workflow", "run", workflow, "--repo", repo, "--ref", branch]
    # candidate (and workspace_ref when used) ride the SAME -f list as the
    # profile inputs — set as dict keys so a config-declared duplicate is
    # overridden by this tool's explicit selection, never sent twice.
    dispatch_inputs = dict(inputs)
    dispatch_inputs["candidate"] = selected_candidate
    if selected_workspace_ref is not None:
        dispatch_inputs["workspace_ref"] = selected_workspace_ref
    for key, value in dispatch_inputs.items():
        argv.extend(["-f", f"{key}={value}"])
    console.emit("run", f"ci:{profile}: dispatch {workflow} on {branch}"
                        f" (candidate {selected_candidate} via {candidate_origin}"
                        + (f", workspace_ref {selected_workspace_ref})"
                           if selected_workspace_ref is not None else ")"))
    completed = _run_capture(argv)
    if completed.returncode:
        console.block(completed.stdout)
        raise OperatorError(f"ci:{profile}: dispatch failed")
    console.emit("ok", f"ci:{profile}: dispatch accepted; remote job continues asynchronously")
    return {
        "profile": profile,
        "workflow": workflow,
        "repository": repo,
        "branch": branch,
        "head": head,
        "remote_head": head,
        "candidate": selected_candidate,
        "candidate_origin": candidate_origin,
        "workspace_ref": selected_workspace_ref,
        "status": "dispatched",
    }


def _ci_resolve_guard(config: dict[str, Any], profile: str, action: str) -> tuple[str, str, str, str]:
    # Shared dispatch/watch precondition: profile resolution plus the
    # local-HEAD == origin/<branch> guard (the invariant that must not
    # drift between `ci start` and `ci watch` - review finding F5).
    ci = config.get("ci", {})
    spec = ci.get(profile) if isinstance(ci, dict) else None
    if not isinstance(spec, dict):
        raise OperatorError(f"unknown CI profile: {profile}")
    workflow = spec.get("workflow")
    if not isinstance(workflow, str) or not workflow:
        raise OperatorError("CI profile requires workflow")
    if shutil.which("gh") is None:
        raise OperatorError("GitHub CLI 'gh' was not found on PATH")
    branch = _current_branch()
    head = _head()
    repo = _remote_repo()
    remote_head = _remote_branch_head(branch)
    if remote_head != head:
        raise OperatorError(
            f"{action} requires origin/{branch} to match local HEAD: local={head} remote={remote_head}"
        )
    return workflow, branch, head, repo


def _ci_watch_match_run(runs: list[dict[str, Any]], head: str) -> dict[str, Any] | None:
    # gh run list is newest-first; the watch target is identity-bound to the
    # exact head SHA (never "latest" - the operating contract's racy-latest
    # prohibition). Preference order among same-head matches (review finding
    # F1): a NON-TERMINAL run wins immediately (a just-dispatched run exists
    # as queued/in_progress from creation, so the canonical start->watch
    # flow never locks onto a stale terminal run); terminal matches need the
    # stabilization counter in _ci_watch before they may be accepted.
    # Known trade-off (deliberate): if an OLD run is stuck non-terminal and
    # a NEWER same-head run already completed, the newest non-terminal still
    # wins - the F1 listing-lag window is common, stuck runs are rare, and
    # preferring the newer terminal here would reintroduce F1.
    terminal: dict[str, Any] | None = None
    for run in runs:
        if run.get("headSha") != head:
            continue
        if run.get("status") != "completed":
            return run
        if terminal is None:
            terminal = run
    return terminal


def _ci_watch_verdict(status: str | None, conclusion: str | None) -> str:
    # pending while not completed; terminal mapping otherwise. Unknown
    # conclusions are failures, never successes (fail closed).
    if status != "completed":
        return "pending"
    if conclusion == "success":
        return "success"
    if conclusion == "cancelled":
        return "cancelled"
    return "failure"


CI_WATCH_STABLE_POLLS = 3
CI_WATCH_POLL_SECONDS = 10.0
CI_WATCH_GH_STRIKES = 3


def _gh_capture(argv: list[str]) -> subprocess.CompletedProcess[str]:
    # gh JSON must be parsed from stdout ONLY: merging stderr (the
    # _run_capture default) lets any benign gh notice corrupt the parse
    # across a 60-minute poll cadence (review finding F4).
    return subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)


def _ci_watch(config: dict[str, Any], profile: str | None, console: Console,
              timeout_minutes: float, json_receipt: bool,
              identity: dict[str, str] | None = None) -> dict[str, Any]:
    # OBSERVATION ONLY (OBL-F1A2B3 owner design 2026-09-25): watches a
    # DISPATCHED run to its terminal state. Never dispatches anything;
    # the dispatch-only trigger law (MEM-20260921T095600Z-C5E1A8) stands.
    # Designed to run under the harness's run_in_background: inherently
    # terminating (internal timeout), clean output (markers + errors
    # only, no per-poll chatter), one JSON receipt line at the end.
    # Two identity modes: PROFILE (config + local git: HEAD must equal
    # origin/<branch>) or EXPLICIT (--repo/--workflow/--branch/--head,
    # checkout-independent - the caller holds the dispatch identity, so
    # the watch does not depend on live git state for cross-repo use).
    if not (math.isfinite(timeout_minutes) and timeout_minutes > 0):
        raise OperatorError(f"ci:watch --timeout must be a positive finite number of minutes, got {timeout_minutes!r}")
    if identity is not None:
        repo = identity["repo"]
        workflow = identity["workflow"]
        branch = identity["branch"]
        head = identity["head"]
        profile = profile or "explicit"
    else:
        if not profile:
            raise OperatorError("ci watch requires PROFILE, or the explicit --repo/--workflow/--branch/--head identity")
        workflow, branch, head, repo = _ci_resolve_guard(config, profile, "ci:watch")
    deadline = time.monotonic() + timeout_minutes * 60.0
    console.emit("run", f"ci:watch:{profile}: resolving run for {head} on {branch} (workflow {workflow})")
    run: dict[str, Any] | None = None
    stable_polls = 0
    stable_run_id: Any = None
    gh_failures = 0
    while run is None:
        if time.monotonic() >= deadline:
            raise OperatorError(
                f"ci:watch:{profile}: no run found for {head} on {branch} within the timeout "
                "(dispatch happens separately via `qiven ci start`)"
            )
        completed = _gh_capture([
            "gh", "run", "list", "--repo", repo, "--workflow", workflow,
            "--branch", branch, "--limit", "20",
            "--json", "databaseId,headSha,status,conclusion,url",
        ])
        if completed.returncode:
            gh_failures += 1
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            console.emit("fail", f"ci:watch:{profile}: gh run list failed ({gh_failures}/{CI_WATCH_GH_STRIKES}): {detail}")
            if gh_failures >= CI_WATCH_GH_STRIKES:
                raise OperatorError(f"ci:watch:{profile}: gh run list failed {CI_WATCH_GH_STRIKES} times")
            stable_polls = 0
            time.sleep(CI_WATCH_POLL_SECONDS)
            continue
        gh_failures = 0
        try:
            runs = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise OperatorError(f"ci:watch:{profile}: unparseable gh run list output: {exc}") from exc
        candidate = _ci_watch_match_run(runs, head)
        if candidate is None:
            stable_polls = 0
            time.sleep(CI_WATCH_POLL_SECONDS)
            continue
        if candidate.get("status") == "completed":
            # Only-terminal evidence: the just-dispatched run may not be
            # listed yet. Accept only after the SAME terminal run stays the
            # newest match across consecutive polls (identity-checked; a
            # failed poll breaks the streak - finding F1).
            if candidate.get("databaseId") != stable_run_id:
                stable_run_id = candidate.get("databaseId")
                stable_polls = 0
            stable_polls += 1
            if stable_polls < CI_WATCH_STABLE_POLLS:
                time.sleep(CI_WATCH_POLL_SECONDS)
                continue
        run = candidate
    run_id = run.get("databaseId")
    url = run.get("url") or ""
    console.emit("wait", f"ci:watch:{profile}: observing run {run_id} (errors only until terminal)")
    verdict = _ci_watch_verdict(run.get("status"), run.get("conclusion"))
    started = time.monotonic()
    while verdict == "pending":
        if time.monotonic() >= deadline:
            verdict = "timeout"
            break
        time_left = deadline - time.monotonic()
        time.sleep(min(CI_WATCH_POLL_SECONDS, max(0.0, time_left)))
        completed = _gh_capture([
            "gh", "run", "view", str(run_id), "--repo", repo,
            "--json", "status,conclusion,url",
        ])
        if completed.returncode:
            gh_failures += 1
            detail = (completed.stderr or completed.stdout or "").strip()[:200]
            console.emit("fail", f"ci:watch:{profile}: gh run view failed ({gh_failures}/{CI_WATCH_GH_STRIKES}): {detail}")
            if gh_failures >= CI_WATCH_GH_STRIKES:
                raise OperatorError(f"ci:watch:{profile}: gh run view failed {CI_WATCH_GH_STRIKES} times")
            continue
        gh_failures = 0
        try:
            state = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise OperatorError(f"ci:watch:{profile}: unparseable gh run view output: {exc}") from exc
        url = state.get("url") or url
        verdict = _ci_watch_verdict(state.get("status"), state.get("conclusion"))
    payload = {
        "profile": profile,
        "workflow": workflow,
        "repository": repo,
        "branch": branch,
        "head": head,
        "run_id": run_id,
        "url": url,
        "conclusion": verdict,
        "duration_seconds": round(time.monotonic() - started, 1),
    }
    exit_code = 0 if verdict == "success" else 1
    # B1 (D3): a non-success terminal verdict teaches its own next step
    # (DIAGNOSE + the exact gh log command) and leaves a ci-watch record.
    watch_next = _emit_ci_watch_record(payload, config.get("repository_name"))
    if json_receipt:
        _print_json(payload)
    else:
        line = f"ci:watch:{profile}: run {run_id} conclusion={verdict} {url}"
        if verdict != "success" and watch_next:
            line += f" - NEXT action: DIAGNOSE - {watch_next}"
        console.emit("ok" if verdict == "success" else "fail", line)
    payload["_exit"] = exit_code
    return payload


def _common_flags() -> argparse.ArgumentParser:
    # fresh instance per parser: global flags are accepted both before and
    # after the subcommand (a repeated odyssey failure was `gate X --json`).
    # SUPPRESS defaults are the load-bearing part: a subparser parsing the
    # same flag with default=None OVERWRITES a value the top-level parser
    # already set (`--json info` silently lost the flag); with SUPPRESS an
    # absent flag sets nothing and the earlier value survives. main() reads
    # the flags with getattr fallbacks for the absent case.
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="emit machine-readable JSON")
    flags.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="show logs for successful tasks")
    flags.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="disable ANSI terminal color")
    return flags


def _print_json(payload: dict[str, Any]) -> None:
    # Machine-readable stdout must survive Windows consoles/code pages; JSON
    # escapes preserve the Unicode value while keeping the transport ASCII.
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


LOG_SPILL_THRESHOLD = 4096


def _spilled_result(result: dict[str, Any]) -> dict[str, Any]:
    """One spilled result (P0 repair R1): instead of a useless
    `<N chars>` placeholder, keep a bounded head/tail inline excerpt with
    a marker naming the omitted byte count, plus machine-checkable
    completeness counters (head + tail + omitted == output_bytes_total,
    all measured on the UTF-8 serialization). Non-output keys are never
    summarized."""
    spilled = dict(result)
    text = str(spilled.get("output") or "")
    excerpt, omitted = _excerpt_with_marker(text, "full output in log_file")
    spilled["output"] = excerpt
    spilled["output_bytes_total"] = len(text.encode("utf-8"))
    spilled["output_bytes_omitted"] = omitted
    return spilled


def _spill_large_logs(payload: dict[str, Any]) -> dict[str, Any]:
    # machine JSON used to be one unbounded line: buffered suite logs were
    # unrecoverable the moment it passed through a terminal filter. Beyond the
    # threshold, the full payload goes to a durable file and stdout stays a
    # compact summary carrying the log path. The total is budgeted on
    # serialized UTF-8 bytes (not character counts), and each spilled result
    # keeps a bounded head/tail excerpt (not a placeholder) plus truthful
    # omitted-byte counters - the consumer keeps usable inline diagnostics
    # AND the full captured evidence stays recoverable in the log file.
    total = sum(len(str(result.get("output") or "").encode("utf-8")) for result in payload.get("results", []))
    if total <= LOG_SPILL_THRESHOLD:
        return payload
    directory = Path(tempfile.gettempdir()) / "qiven-operator"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = str(payload.get("gate") or "run")
    safe_gate = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    log_file = directory / f"qiven-{safe_gate}-{stamp}-{os.getpid()}.json"
    log_file.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    compact = dict(payload)
    compact["log_file"] = str(log_file)
    compact["results"] = [_spilled_result(result) for result in payload["results"]]
    return compact


# ===========================================================================
# Bounded evidence read route (ADR-0060 D6; B+D batch). A consumer
# utility, NOT a gate task: reads a retained evidence/log artifact one
# BYTE range at a time (documented: --offset/--count are bytes, the only
# addressing an arbitrary captured artifact supports), output byte-capped
# at BOUNDED_READ_MAX_BYTES with an explicit EOF marker and a continue
# cursor. Path boundary: a RELATIVE path addresses the repository's
# .generated-temp/ evidence roots (leading ".generated-temp/" optional);
# an ABSOLUTE path is allowed when it resolves under the repository root
# OR under one of the operator's retained-evidence roots outside it (the
# qiven-owned spill/retention area under the OS temp dir - retained task
# evidence stays recoverable through this route, E-batch closeout law).
# Reads outside both boundaries are typed errors, never silent
# redirects. Decoding is a view (utf-8 errors=replace); invalid captured
# bytes stay recoverable in the artifact (D6). Expiry: when the artifact
# is gone but a `<artifact>.expired` sibling marker exists, the read is a
# typed `expired` error naming the ORIGINAL locator (and the marker's
# bounded note) - an expired pointer stays visible and never justifies
# dropping the diagnostic (D6). When both artifact and marker exist the
# BYTES win (readable evidence is served; the marker alone never hides
# surviving diagnostics).
# ===========================================================================

def _operator_evidence_roots() -> list[Path]:
    """Qiven-owned retained-evidence roots OUTSIDE the repository (the
    spill/retention area under the OS temp dir; ADR-0060 D6 - retained
    task evidence stays recoverable through evidence-read)."""
    try:
        return [(Path(tempfile.gettempdir()) / "qiven-operator").resolve()]
    except OSError:
        return []


def _evidence_target(path_text: str) -> Path:
    """Resolve one evidence-read locator inside the documented boundary."""
    raw = Path(path_text)
    if ".." in raw.parts:
        raise OperatorError(
            f"evidence-read rejects path traversal: {path_text!r}"
        )
    repo_root = ROOT.resolve()
    if raw.is_absolute():
        target = raw.resolve()
        allowed = target == repo_root or repo_root in target.parents or any(
            root == target or root in target.parents
            for root in _operator_evidence_roots()
        )
        if not allowed:
            raise OperatorError(
                f"evidence-read absolute paths must stay under the repository root "
                f"{repo_root} or the operator evidence roots "
                f"{[str(r) for r in _operator_evidence_roots()]}; got {target}"
            )
        return target
    generated = repo_root / ".generated-temp"
    parts = raw.parts
    if parts and parts[0] == ".generated-temp":
        target = (repo_root / Path(*parts)).resolve()
    else:
        target = (generated / Path(*parts)).resolve()
    if generated not in target.parents:
        raise OperatorError(
            f"relative evidence paths must stay under .generated-temp/ (use an "
            f"absolute path under the repository root for other retained "
            f"artifacts); got {path_text!r}"
        )
    return target


def _evidence_read(path_text: str, offset: int, count: int,
                   json_mode: bool, console: Console) -> int:
    if offset < 0:
        raise OperatorError(f"evidence-read --offset must be >= 0, got {offset}")
    if count < 1:
        # a count below 1 is a usage error, never silently enlarged (the
        # documented law: counts are clamped DOWN only, never enlarged)
        raise OperatorError(f"evidence-read --count must be >= 1, got {count}")
    count = min(count, _cr.BOUNDED_READ_MAX_BYTES)
    target = _evidence_target(path_text)
    try:
        size = target.stat().st_size
    except FileNotFoundError as exc:
        # expiry marker (E-batch closeout, D6 "expiration/unavailable
        # artifacts stay visible"): the retention contract removed the
        # artifact but left `<artifact>.expired` - answer with the typed
        # `expired` error naming the ORIGINAL locator plus the marker's
        # bounded note, never a bare not-found that hides the expiry fact
        marker = target.with_name(target.name + ".expired")
        if marker.is_file():
            try:
                note = marker.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                note = ""
            note_text = f"; marker note: {_utf8_prefix(note, 200)}" if note else ""
            raise OperatorError(
                f"evidence expired: {path_text} (original locator {target}; "
                f"retention removed the artifact and left the expiry marker "
                f"{marker}{note_text}) - the expired pointer stays visible, it "
                "never justifies dropping the diagnostic (D6)"
            ) from exc
        raise OperatorError(
            f"evidence not found: {path_text} ({target}); an expired or "
            "never-retained pointer stays visible as this typed error"
        ) from exc
    except OSError as exc:
        raise OperatorError(f"evidence unreadable: {target}: {exc}") from exc
    if target.is_dir():
        raise OperatorError(f"evidence path is a directory: {target}")
    try:
        with target.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(count)
    except OSError as exc:
        raise OperatorError(f"evidence unreadable: {target}: {exc}") from exc
    text = data.decode("utf-8", errors="replace")
    end = offset + len(data)
    eof = end >= size
    try:
        display = str(target.relative_to(ROOT))
    except ValueError:
        display = str(target)
    if json_mode:
        _print_json({
            "status": "ok",
            "path": str(display),
            "offset": offset,
            "bytes_returned": len(data),
            "total_bytes": size,
            "eof": eof,
            "next_offset": None if eof else end,
            "content": text,
        })
        return 0
    console.emit("run", f"evidence-read {display} (bytes {offset}..{end}/{size})")
    console.block(text)
    if eof:
        console.emit("ok", f"evidence-read EOF at byte {end}/{size}")
    else:
        console.emit(
            "wait",
            f"more evidence bytes remain; continue: qiven evidence-read {display} --offset {end}",
        )
    return 0


# ===========================================================================
# Discovery surface (B6, register DG-2/DG-3). `surface` is the O(1)
# tasks/gates/ci introspection (names discoverable without opening
# .qiven/operator.json per repo; ci profiles carry the `ci start`
# entry points); `records` is the read-back route for
# the Common Records the gate/run/ci/exec carriers WRITE - until B6 they
# were write-only (no stdout carrier named them). The bounded view is
# the ADOPTED record_projection (never a second renderer).
# ============================================================================

_RECORDS_LIST_CAP = 40


def _surface(config: dict[str, Any], console: Console, json_mode: bool) -> int:
    """One call lists every declared gate, task, and CI profile (DG-2)."""
    gates_raw = config.get("gates")
    gates = gates_raw if isinstance(gates_raw, dict) else {}
    tasks_raw = config.get("tasks")
    tasks = tasks_raw if isinstance(tasks_raw, dict) else {}
    # CI profiles (the `qiven ci start <profile>` entry points) ride the
    # same O(1) discovery surface: a missing/empty `ci` section is zero
    # profiles, never an error, and a malformed profile entry lists with
    # a null workflow rather than failing the whole surface.
    ci_raw = config.get("ci")
    ci_table = ci_raw if isinstance(ci_raw, dict) else {}
    default = config.get("default_gate")
    task_summary: dict[str, dict[str, Any]] = {}
    for name, spec in sorted(tasks.items()):
        if isinstance(spec, dict) and spec.get("builtin"):
            task_summary[name] = {"kind": "builtin", "builtin": spec["builtin"]}
        elif isinstance(spec, dict) and spec.get("argv"):
            task_summary[name] = {"kind": "argv", "argv": [str(a) for a in spec["argv"]]}
        else:
            task_summary[name] = {"kind": "unrecognized"}

    def _sequence(spec: Any) -> str:
        parts: list[str] = []
        for item in spec if isinstance(spec, list) else [spec]:
            if isinstance(item, list):  # parallel group (gate sequence law)
                parts.append("(" + " | ".join(str(x) for x in item) + ")")
            else:
                parts.append(str(item))
        return " -> ".join(parts)

    ci_profiles: list[dict[str, Any]] = []
    for name, spec in sorted(ci_table.items()):
        workflow = spec.get("workflow") if isinstance(spec, dict) else None
        ci_profiles.append({
            "name": str(name),
            "workflow": workflow if isinstance(workflow, str) and workflow else None,
        })

    if json_mode:
        payload: dict[str, Any] = {
            "status": "ok",
            "repository": config.get("repository_name"),
            "default_gate": default,
            "gates": {str(name): _sequence(spec) for name, spec in sorted(gates.items())},
            "tasks": task_summary,
            "ci_profiles": ci_profiles,
        }
        _workspace_identity_fields(payload)
        _print_json(payload)
        return 0
    console.emit(
        "ok",
        f"surface: {len(gates)} gate(s), {len(tasks)} task(s),"
        f" {len(ci_profiles)} ci profile(s) -"
        " config: .qiven/operator.json",
    )
    for name, spec in sorted(gates.items()):
        mark = " (default)" if name == default else ""
        console.block(f"  gate {name}{mark}: {_sequence(spec)}")
    for name, spec in task_summary.items():
        if spec["kind"] == "builtin":
            console.block(f"  task {name}: builtin {spec['builtin']}")
        elif spec["kind"] == "argv":
            console.block(f"  task {name}: {' '.join(spec['argv'])}")
        else:
            console.block(f"  task {name}: (unrecognized task spec)")
    for entry in ci_profiles:
        workflow = entry["workflow"]
        console.block(
            f"  ci {entry['name']}: {workflow if workflow else '(no workflow declared)'}"
        )
    next_lines = "  NEXT action: NONE - run `qiven gate <name>` or `qiven run <task>`;\n"
    if ci_profiles:
        next_lines += "  ci dispatch: `qiven ci start <profile>`;\n"
    next_lines += "  record read-back: `qiven records`"
    console.block(next_lines)
    return 0


def _record_headline(doc: dict[str, Any]) -> dict[str, str]:
    outcome = (doc.get("domain_outcome") or {}).get("outcome") or "-"
    action = (doc.get("next_action") or {}).get("action") or "-"
    return {
        "record_kind": str(doc.get("record_kind") or "-"),
        "verdict": str(outcome).upper(),
        "next": str(action),
    }


def _records_list(console: Console, json_mode: bool) -> int:
    """Newest-first listing of the retained Common Records (names embed
    the operation-id timestamp, so a reverse-name sort is the
    deterministic newest-first order - no filesystem mtime dependency)."""
    directory = _records_dir()
    names = (
        sorted((p.name for p in directory.glob("*.json")), reverse=True)
        if directory.is_dir() else []
    )
    shown = names[:_RECORDS_LIST_CAP]
    entries: list[dict[str, Any]] = []
    for name in shown:
        entry: dict[str, Any] = {"name": name}
        try:
            doc = json.loads((directory / name).read_text(encoding="utf-8"))
            entry.update(_record_headline(doc) if isinstance(doc, dict) else
                         {"record_kind": "unreadable", "verdict": "-", "next": "-"})
        except (OSError, json.JSONDecodeError):
            entry.update({"record_kind": "unreadable", "verdict": "-", "next": "-"})
        entries.append(entry)
    if json_mode:
        _print_json({
            "status": "ok",
            "count": len(names),
            "returned": len(entries),
            "omitted": len(names) - len(entries),
            "records": entries,
        })
        return 0
    if not entries:
        # B1 exec-list law: an empty state states itself, never silence
        console.emit(
            "ok",
            f"records: none yet under .generated-temp/operator/records/ -"
            " NEXT action: NONE (a gate/run/ci/exec invocation writes one)",
        )
        return 0
    console.emit(
        "ok",
        f"records: {len(names)} under .generated-temp/operator/records/"
        f" (newest first, {len(entries)} shown, {len(names) - len(entries)} omitted)",
    )
    for entry in entries:
        console.block(
            f"  {entry['name']}  kind={entry['record_kind']}"
            f" verdict={entry['verdict']} next={entry['next']}"
        )
    console.block(
        "  NEXT action: NONE - bounded view: `qiven records <name>`;"
        " raw bytes: `qiven evidence-read"
        " .generated-temp/operator/records/<name>`"
    )
    return 0


def _record_show(name: str, console: Console, json_mode: bool) -> int:
    """Print one record's bounded model view (the ADOPTED
    record_projection; raw JSON stays reachable via evidence-read)."""
    if Path(name).name != name:
        raise OperatorError(
            f"records rejects path traversal: {name!r} (a record NAME from"
            " `qiven records`, never a path)"
        )
    target = _records_dir() / name
    if not target.is_file():
        raise OperatorError(
            f"unknown record: {name} (use `qiven records` to list; records"
            " live under .generated-temp/operator/records/)"
        )
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"record unreadable: {target}: {exc}") from exc
    if not isinstance(doc, dict):
        raise OperatorError(f"record is not a common record object: {target}")
    locator = f".generated-temp/operator/records/{name}"
    if json_mode:
        payload = _rp.project_json(doc)
        payload["status"] = "ok"
        payload["record"] = locator
        payload["raw_read"] = f"qiven evidence-read {locator}"
        _print_json(payload)
        return 0
    console.emit("run", f"records {name} (bounded model view)")
    console.block(_rp.project(doc))
    console.block(f"  raw bytes: qiven evidence-read {locator}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qiven", description="Qiven local engineering operator", parents=[_common_flags()]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show repository/operator metadata", parents=[_common_flags()])
    surface = sub.add_parser(
        "surface",
        help="O(1) introspection: list this repository's declared gates, tasks, and ci profiles",
        parents=[_common_flags()],
    )
    records = sub.add_parser(
        "records",
        help="read back the operator's Common Records (list, or NAME for the bounded model view)",
        parents=[_common_flags()],
    )
    records.add_argument(
        "name", nargs="?", default=None,
        help="record file name under .generated-temp/operator/records/ (omit to list)",
    )
    gate = sub.add_parser("gate", help="run the configured local validation gate", parents=[_common_flags()])
    gate.add_argument("gate", nargs="?", default=None, help="gate name; defaults to config default_gate")
    gate.add_argument("--name", dest="gate_flag", default=None, help="gate name (alternative to the positional)")
    gate.add_argument("--expect-head", default=None, help="require exact Git HEAD")
    run = sub.add_parser("run", help="run declared task(s)", parents=[_common_flags()])
    run.add_argument("tasks", nargs="+", help="task names")
    run.add_argument("--parallel", action="store_true", help="run requested tasks in parallel")
    ci = sub.add_parser("ci", help="asynchronous CI operations", parents=[_common_flags()])
    ci_sub = ci.add_subparsers(dest="ci_command", required=True)
    ci_start = ci_sub.add_parser("start", help="dispatch CI and return immediately", parents=[_common_flags()])
    ci_start.add_argument("profile", help="declared CI profile")
    ci_start.add_argument("--candidate", default=None,
                          help="candidate commit SHA sent as workflow input 'candidate' (exactly 40 hex chars; DEFAULT: the repository's current HEAD, resolved and recorded explicitly by this tool)")
    ci_start.add_argument("--workspace-ref", dest="workspace_ref", default=None,
                          help="optional workspace_ref workflow input passthrough (omitted from the dispatch entirely when absent)")
    ci_watch = ci_sub.add_parser(
        "watch", help="observe an already-dispatched CI run to terminal state (observation only; run under run_in_background)",
        parents=[_common_flags()],
    )
    ci_watch.add_argument("profile", nargs="?", default=None,
                          help="declared CI profile (in-repo mode); omitted when the explicit identity flags are used")
    ci_watch.add_argument("--timeout", type=float, default=60.0,
                          help="overall watch budget in minutes (inherently terminating; default 60)")
    ci_watch.add_argument("--receipt", action="store_true",
                          help="print one JSON receipt line at the end (always printed in --json mode)")
    ci_watch.add_argument("--repo", default=None,
                          help="explicit identity mode: OWNER/NAME of the target repository (requires --workflow/--branch/--head)")
    ci_watch.add_argument("--workflow", default=None, help="explicit identity mode: workflow name")
    ci_watch.add_argument("--branch", default=None, help="explicit identity mode: branch name")
    ci_watch.add_argument("--head", default=None, help="explicit identity mode: exact head SHA the run must match")
    exec_parser = sub.add_parser(
        "exec", help="supervised detached command execution under bounded process custody", parents=[_common_flags()]
    )
    exec_sub = exec_parser.add_subparsers(dest="exec_command", required=True)
    exec_start = exec_sub.add_parser("start", help="run a command under watchdog custody with heartbeat", parents=[_common_flags()])
    exec_start.add_argument("--timeout", type=float, default=EXEC_DEFAULT_TIMEOUT_SECONDS,
                            help="front-end supervision budget in seconds (exit 124 when it elapses; the run continues under its lease)")
    exec_start.add_argument("--max-lifetime", type=float, default=EXEC_DEFAULT_MAX_LIFETIME_SECONDS,
                            help=f"hard lease on the run's process tree in seconds (default {EXEC_DEFAULT_MAX_LIFETIME_SECONDS:.0f}, clamped to [{EXEC_MAX_LIFETIME_FLOOR_SECONDS:.0f}, {EXEC_MAX_LIFETIME_CEILING_SECONDS:.0f}])")
    exec_start.add_argument("command_args", nargs=argparse.REMAINDER, help="command after '--' to execute")
    exec_status = exec_sub.add_parser("status", help="snapshot one run: state, custody, log tail", parents=[_common_flags()])
    exec_status.add_argument("run_id", help="exec run id")
    exec_status.add_argument("--tail", type=int, default=2000, help="log tail bytes to include")
    exec_stop = exec_sub.add_parser("stop", help="terminate a run's process tree", parents=[_common_flags()])
    exec_stop.add_argument("run_id", help="exec run id")
    exec_list = exec_sub.add_parser("list", help="list known runs with state and lease", parents=[_common_flags()])
    exec_sweep = exec_sub.add_parser("sweep", help="terminate expired runs, finalize stale records", parents=[_common_flags()])
    evidence = sub.add_parser(
        "evidence-read",
        help="bounded BYTE-range read of a retained evidence/log artifact (EOF marker + continue cursor; capped at 16384 bytes)",
        parents=[_common_flags()],
    )
    evidence.add_argument("path", help="relative stays under .generated-temp/ (leading '.generated-temp/' optional); absolute must be under the repository root")
    evidence.add_argument("--offset", type=int, default=0, help="byte offset to start reading at (default 0)")
    evidence.add_argument("--count", type=int, default=16384,
                          help=f"max bytes to return (capped at {_cr.BOUNDED_READ_MAX_BYTES})")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    if raw and raw[0] == "--exec-watchdog":
        if len(raw) != 2:
            sys.stderr.write("usage: qiven_operator.py --exec-watchdog RECORD\n")
            return 2
        return _watchdog_run(raw[1])
    args = _parser().parse_args(raw)
    json_mode = bool(getattr(args, "json", False))
    verbose_mode = bool(getattr(args, "verbose", False))
    no_color_mode = bool(getattr(args, "no_color", False))
    args.json = json_mode
    args.verbose = verbose_mode
    args.no_color = no_color_mode
    console = Console(json_mode=json_mode, verbose=verbose_mode, no_color=no_color_mode)
    try:
        # dead-man insurance rides every invocation (never blocks, never
        # raises into the caller's command) - except the explicit `exec
        # sweep`, which IS the sweep: piggybacking first would reconcile
        # everything and leave the explicit pass nothing to report
        try:
            if not (args.command == "exec"
                    and getattr(args, "exec_command", None) == "sweep"):
                _sweep_exec_records(console, quiet=not verbose_mode)
        except Exception:
            pass
        config = _load_config()
        if args.command == "info":
            payload = {
                "status": "ok",
                "repository": config.get("repository_name"),
                "operator_schema": config.get("schema_version"),
                "default_gate": config.get("default_gate"),
                "root": str(ROOT),
                "head": _head(),
            }
            _workspace_identity_fields(payload)
            if args.json:
                _print_json(payload)
            else:
                console.emit("ok", f"repository={payload['repository']} head={payload['head']}")
            return 0

        if args.command == "surface":
            # B6 (DG-2): discovery introspection - one call names every
            # gate/task; no config-file spelunking
            return _surface(config, console, args.json)

        if args.command == "records":
            # B6 (DG-3): the read-back surface for the write-only Common
            # Records (bounded view via the adopted record_projection)
            if args.name:
                return _record_show(args.name, console, args.json)
            return _records_list(console, args.json)

        tasks = config.get("tasks")
        if not isinstance(tasks, dict):
            raise OperatorError("config tasks must be an object")

        if args.command == "evidence-read":
            # consumer utility (ADR-0060 D6): no gate registration, no
            # custody - a bounded read of retained evidence
            return _evidence_read(args.path, args.offset, args.count, args.json, console)

        if args.command == "gate":
            gate_name = args.gate or args.gate_flag or config.get("default_gate")
            gates = config.get("gates")
            if not isinstance(gates, dict) or not isinstance(gates.get(gate_name), list):
                available = ", ".join(sorted(gates)) if isinstance(gates, dict) else "none"
                raise OperatorError(f"unknown gate: {gate_name} (available: {available})")
            sequence = list(gates[gate_name])
            if args.expect_head:
                sequence.insert(0, "exact-head")
            started = time.monotonic()
            results = _run_sequence(sequence, tasks, console, args.expect_head)
            failed = [result for result in results if result.returncode]
            payload = {
                "status": "fail" if failed else "pass",
                "gate": gate_name,
                "head": _head(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "results": [asdict(result) for result in results],
            }
            _workspace_identity_fields(payload)
            _write_gate_receipt(payload)
            # Common Record v1 (additive; ADR-0060 D3): one record per
            # gate invocation, PASS and FAIL. The FAIL human view gains
            # exactly ONE next-action summary line after the existing
            # banner/detail flow - markers, exit codes and receipts are
            # unchanged.
            gate_next = _emit_gate_record(
                payload, results, args.expect_head, config.get("repository_name")
            )
            if args.json:
                _print_json(_spill_large_logs(payload))
            else:
                # ONE summary line carrying class + action + reference
                # (D3 selector law: the documented FAIL/receipt selectors
                # and head/tail previews receive class, next action and
                # locator in the selected summary line - E-batch fix; the
                # marker prefix and status word are byte-stable). ASCII-
                # safe control syntax: plain-hyphen separators.
                verdict_word = str(payload["status"]).upper()
                if failed and gate_next:
                    # B1 (D3): the bounded model view of the SAME record
                    # rides the FAIL carrier in the DETAIL region (before
                    # the summary) - the selector-law summary line stays
                    # the TAIL line (E-batch recency law: the last line a
                    # truncated preview keeps carries class+action+locator).
                    if gate_next.get("projection"):
                        console.block(str(gate_next["projection"]))
                    console.emit(
                        "fail",
                        f"gate:{gate_name}: {verdict_word}"
                        f" - NEXT action: {gate_next['action']}"
                        f" - {_utf8_prefix(gate_next.get('supported_by') or '', 200)}"
                        f" - evidence: {_utf8_prefix(gate_next.get('reference') or 'none retained', 200)}",
                    )
                else:
                    receipt_note = ""
                    if not failed:
                        # observe the receipt, never assume it: a degraded
                        # receipt write (_write_gate_receipt swallows OSError,
                        # fail-closed for proof) must not be claimed as an
                        # existing locator in the model-facing summary line -
                        # the same honest wording the record carries
                        receipt = _receipt_path(gate_name, str(payload["head"]))
                        receipt_note = (
                            f" - receipt: {_utf8_prefix(str(receipt), 200)}"
                            if receipt.is_file()
                            else " - receipt: none (receipt write degraded at "
                                 f"{_utf8_prefix(str(receipt), 200)})"
                        )
                    console.emit(
                        "fail" if failed else "ok",
                        f"gate:{gate_name}: {verdict_word}{receipt_note}",
                    )
            return 1 if failed else 0

        if args.command == "run":
            started = time.monotonic()
            sequence: list[Any] = [list(args.tasks)] if args.parallel else list(args.tasks)
            results = _run_sequence(sequence, tasks, console, None)
            failed = [result for result in results if result.returncode]
            payload = {
                "status": "fail" if failed else "pass",
                # additive (B1): record identity for the task-run record
                "head": _git_head_or_empty(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "results": [asdict(result) for result in results],
            }
            _workspace_identity_fields(payload)
            # B1 (D3): `run` stops being the emission asymmetry - one
            # task-run record per invocation (PASS and FAIL), and the FAIL
            # human view gains the same selector-law summary line + record
            # view the gate carries. The PASS line stays byte-stable.
            run_next = _emit_run_record(payload, results, config.get("repository_name"))
            if args.json:
                _print_json(_spill_large_logs(payload))
            else:
                if failed and run_next:
                    # B1 (D3): view first, actionable tail line last (the
                    # same recency law the gate FAIL carrier obeys).
                    if run_next.get("projection"):
                        console.block(str(run_next["projection"]))
                    console.emit(
                        "fail",
                        f"run: {payload['status'].upper()}"
                        f" - NEXT action: {run_next['action']}"
                        f" - {_utf8_prefix(run_next.get('supported_by') or '', 200)}"
                        f" - evidence: {_utf8_prefix(run_next.get('reference') or 'none retained', 200)}",
                    )
                else:
                    console.emit("fail" if failed else "ok", f"run: {payload['status'].upper()}")
            return 1 if failed else 0

        if args.command == "ci" and args.ci_command == "start":
            payload = _ci_start(config, args.profile, console,
                                getattr(args, "candidate", None),
                                getattr(args, "workspace_ref", None))
            _workspace_identity_fields(payload)
            # B1 (D3): the dispatch success names its own watch handle
            # (NEXT, supported_by = the exact re-call) and leaves a
            # ci-dispatch record; additive, json payload unchanged.
            _emit_ci_dispatch_record(payload, config.get("repository_name"))
            if args.json:
                _print_json(payload)
            elif not console.json_mode:
                console.block(
                    f"      repository:  {payload['repository']}\n"
                    f"      branch:      {payload['branch']}\n"
                    f"      head:        {payload['head']}\n"
                    f"      remote-head: {payload['remote_head']}\n"
                    f"      workflow:    {payload['workflow']}\n"
                    f"      candidate:   {payload['candidate']}"
                    f" (via {payload['candidate_origin']})"
                    + (f"\n      workspace:   {payload['workspace_ref']}"
                       if payload.get("workspace_ref") is not None else "")
                )
                console.emit(
                    "run",
                    f"ci:start:{args.profile}: dispatched"
                    f" - NEXT action: qiven ci watch {args.profile}"
                    f" (run_in_background; terminal verdict + receipt)",
                )
            return 0

        if args.command == "ci" and args.ci_command == "watch":
            identity = None
            if args.repo is not None:
                missing = [flag for flag, value in (
                    ("--workflow", args.workflow), ("--branch", args.branch), ("--head", args.head),
                ) if not value]
                if missing:
                    raise OperatorError(f"ci:watch explicit identity requires {'+'.join(missing)} alongside --repo")
                if args.profile:
                    raise OperatorError("ci:watch explicit identity does not take a PROFILE argument")
                identity = {"repo": args.repo, "workflow": args.workflow,
                            "branch": args.branch, "head": args.head}
            payload = _ci_watch(config, args.profile, console, args.timeout,
                                args.receipt or console.json_mode, identity)
            _workspace_identity_fields(payload)
            return payload.pop("_exit")

        if args.command == "exec":
            if args.exec_command == "start":
                command = list(args.command_args)
                if command and command[0] == "--":
                    command = command[1:]
                if not command:
                    # ADR-0062 d5: an invocation-precondition refusal is the
                    # class where the mechanism mechanically knows the
                    # correction - it carries the canonical FIX channel
                    # (JSON next_action field / human NEXT line) beside the
                    # frozen error text, as the one recovery channel.
                    raise OperatorError(
                        "exec start requires a command after '--'",
                        next_action=asdict(_cr.next_action_for(
                            "invocation-rejected",
                            "supply the command to run after the '--' separator"
                            " (qiven exec start -- <command> [args...]) and"
                            " re-invoke",
                        )),
                    )
                payload, exit_code = _exec_start_frontend(
                    command, float(args.timeout), float(args.max_lifetime), console
                )
                _workspace_identity_fields(payload)
                if args.json:
                    _print_json(payload)
                return exit_code
            if args.exec_command == "status":
                # unknown running operations (ADR-0060 D15): a query for a
                # run id with no record yields the typed CLI answer AND one
                # additive record with completion=unknown (a corrupt record
                # is a different class - it exists - and stays unrecorded
                # here)
                if not _exec_record_path(args.run_id).is_file():
                    _emit_exec_unknown_record(args.run_id)
                record = _read_exec_record(args.run_id)
                snapshot = _exec_snapshot(record)
                tail = _tail_text(Path(snapshot["log"]), max(0, int(args.tail)))
                # additive Common Record: one status observation (the 124
                # law rides the record: still-running vs indeterminate
                # stay DISTINCT; deadline_reached only from custody
                # observation - see _EXEC_RECORD_MAP)
                _emit_exec_record(f"status-{snapshot['state']}", record, snapshot["state"])
                payload = dict(snapshot, status=snapshot["state"], tail=tail)
                _workspace_identity_fields(payload)
                if args.json:
                    _print_json(payload)
                else:
                    console.emit(
                        "ok" if snapshot["state"] == "done" else "wait",
                        f"exec {snapshot['id']}: {snapshot['state']}"
                        + (f", exit {snapshot['exit_code']}" if snapshot["exit_code"] is not None else "")
                        + f", log {snapshot['log_bytes']} bytes"
                        + (f", lease {snapshot['deadline_utc']}" if snapshot["deadline_utc"] else ""),
                    )
                    if tail:
                        console.block(tail)
                return 0
            if args.exec_command == "stop":
                record = _read_exec_record(args.run_id)
                payload, exit_code = _exec_stop(record, console)
                _workspace_identity_fields(payload)
                if args.json:
                    _print_json(payload)
                return exit_code
            if args.exec_command == "list":
                runs = []
                directory = _exec_dir()
                if directory.is_dir():
                    for record_path in sorted(directory.glob("*.json")):
                        record = _read_exec_record_path(record_path)
                        if record is not None:
                            runs.append(_exec_snapshot(record))
                payload = {"status": "ok", "runs": runs}
                _workspace_identity_fields(payload)
                if args.json:
                    _print_json(payload)
                else:
                    if not runs:
                        # B1: silent success is not a result - an empty
                        # list states itself (D3: a model view retains
                        # requested data; empty is data).
                        console.emit(
                            "ok",
                            "exec list: no runs (nothing to reconcile)",
                        )
                    for snapshot in runs:
                        console.emit(
                            "wait" if snapshot["state"] in ("running", "reaping", "orphaned") else "ok",
                            f"exec {snapshot['id']}: {snapshot['state']}"
                            + (f", exit {snapshot['exit_code']}" if snapshot["exit_code"] is not None else "")
                            + (f", lease {snapshot['deadline_utc']}" if snapshot["deadline_utc"] else ""),
                        )
                return 0
            if args.exec_command == "sweep":
                actions = _sweep_exec_records(console, quiet=False)
                payload = {"status": "ok", "actions": actions}
                _workspace_identity_fields(payload)
                if args.json:
                    _print_json(payload)
                elif not actions:
                    # B5 (four-element law): silent success is not a
                    # result (the B1 exec-list law) - an empty sweep
                    # states itself with NEXT NONE
                    console.emit(
                        "ok",
                        "exec sweep: no actions (no expired or stale runs;"
                        " NEXT action: NONE - nothing to reconcile)",
                    )
                else:
                    # B5 (four-element law): reconciled actions state WHY
                    # they happened (lease law) and the read-back route;
                    # the per-action lines above stay byte-stable
                    console.block(
                        f"  why: {len(actions)} run(s) past their lease or stale were\n"
                        f"  reconciled (expired runs are terminated at their lease - the\n"
                        f"  business exit code is unknown and never guessed)\n"
                        f"  NEXT action: DIAGNOSE - read each run's log under\n"
                        f"  .generated-temp/operator/exec/ to classify the outcomes;\n"
                        f"  `qiven exec list` inventories the remaining runs"
                    )
                return 0

        raise OperatorError("unsupported command")
    except OperatorError as exc:
        if args.json:
            error_payload = {"status": "error", "error": str(exc)}
            if exc.next_action is not None:
                # ADR-0062 d5: the canonical recovery channel rides as one
                # ADDITIVE field beside the frozen error shape (other
                # failure paths keep their published bytes unchanged).
                error_payload["next_action"] = exc.next_action
            try:
                _workspace_identity_fields(error_payload)
            except Exception:
                pass
            _print_json(error_payload)
        else:
            console.emit("fail", str(exc))
            if exc.next_action is not None:
                # the human mirror of the same single channel (the exec
                # surface's NEXT action line idiom), never a second one
                console.block(
                    f"  NEXT action: {exc.next_action['action']}"
                    f" - {exc.next_action.get('supported_by', '')}"
                )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
