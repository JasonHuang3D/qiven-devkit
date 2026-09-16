#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
QIVEN_OPERATOR_PY="$SCRIPT_DIR/qiven.py"

check_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

if [ -n "${QIVEN_PYTHON:-}" ]; then
  if ! check_python "$QIVEN_PYTHON"; then
    printf '%s\n' "[FAIL] QIVEN_PYTHON must point to Python 3.9 or newer: $QIVEN_PYTHON" >&2
    exit 2
  fi
  exec "$QIVEN_PYTHON" "$QIVEN_OPERATOR_PY" "$@"
fi

if command -v python3 >/dev/null 2>&1 && check_python python3; then
  exec python3 "$QIVEN_OPERATOR_PY" "$@"
fi

if command -v python >/dev/null 2>&1 && check_python python; then
  exec python "$QIVEN_OPERATOR_PY" "$@"
fi

printf '%s\n' '[FAIL] Qiven Operator requires Python 3.9 or newer. Set QIVEN_PYTHON or make a supported python available on PATH.' >&2
exit 2
