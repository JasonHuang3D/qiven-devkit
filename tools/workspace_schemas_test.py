"""Self-test for tools/workspace_schemas.py (WR-1 schema layer).

Each case asserts ONE named schema law; the case id rides in the failure
message. Fixtures are disposable temp files (testing law: tests never touch
developer repositories).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workspace_schemas as ws  # noqa: E402

Z40 = "0" * 40
O40 = "1" * 40
T40 = "2" * 40
D64 = "3" * 64

VALID_WORKSPACE = (
    "{\n"
    '  "schema": "qiven-workspace-v1",\n'
    '  "workspace_id": "qiven",\n'
    '  "repositories": {\n'
    '    "qiven-foundation": {"url": "https://github.com/O/qiven-foundation.git"},\n'
    '    "qiven-toolchain-win": {"url": "https://github.com/O/qiven-toolchain-win.git", "platform": "windows"},\n'
    '    "qiven-docs": {"url": "https://github.com/O/qiven-docs.git", "selection": "only-when-referenced"}\n'
    "  }\n"
    "}\n"
)

VALID_LOCK = (
    "{\n"
    '  "schema": "qiven-workspace-lock-v1",\n'
    '  "workspace_id": "qiven",\n'
    f'  "generation": "sha256:{D64}",\n'
    '  "nodes": {\n'
    '    "qiven-foundation": {\n'
    f'      "commit": "{Z40}",\n'
    f'      "tree": "{O40}",\n'
    '      "declaration": {\n'
    '        "origin": "census-wr0",\n'
    '        "path": "census/wr0-declarations.json",\n'
    f'        "blob": "{T40}",\n'
    f'        "digest": "sha256:{D64}",\n'
    '        "shadow_only": true\n'
    "      }\n"
    "    }\n"
    "  }\n"
    "}\n"
)

VALID_DEPS = (
    "{\n"
    '  "schema": "qiven-dependencies-v1",\n'
    '  "repository": "qiven-runtime",\n'
    '  "supported_platforms": ["windows"],\n'
    '  "provides": [{"contract": "qiven-runtime-api-v1", "targets": ["qiven::runtime"]}],\n'
    '  "dependencies": [\n'
    "    {\n"
    '      "id": "qiven-foundation",\n'
    '      "kind": "first-party-source",\n'
    '      "contract": "qiven-foundation-api-v1",\n'
    f'      "legacy_consumer_pin": {{"sha": "{Z40}", "equals_lock_node": true}}\n'
    "    }\n"
    "  ]\n"
    "}\n"
)


def _expect_pass(case: str, text: str, schema: dict) -> None:
    instance = ws.parse_strict(text)
    errors = ws.validate(instance, schema)
    assert not errors, f"{case}: expected PASS, got {[e.as_dict() for e in errors]}"


def _expect_typed(case: str, text: str, schema: dict, error_type: str) -> None:
    try:
        instance = ws.parse_strict(text)
    except ws.SchemaError as error:
        assert error.error_type == error_type, (
            f"{case}: parse-stage type {error.error_type} != {error_type}"
        )
        return
    errors = ws.validate(instance, schema)
    matched = [e for e in errors if e.error_type == error_type]
    assert matched, f"{case}: expected typed {error_type}, got {[e.as_dict() for e in errors]}"


def main() -> int:
    workspace_schema = ws.load_schema("qiven-workspace-v1.schema.json")
    lock_schema = ws.load_schema("qiven-workspace-lock-v1.schema.json")
    deps_schema = ws.load_schema("qiven-dependencies-v1.schema.json")

    _expect_pass("S2-valid-workspace", VALID_WORKSPACE, workspace_schema)
    _expect_pass("S4-valid-lock", VALID_LOCK, lock_schema)
    _expect_pass("S7-valid-deps", VALID_DEPS, deps_schema)

    _expect_typed(
        "S3-duplicate-key",
        '{"schema": "qiven-workspace-v1", "schema": "qiven-workspace-v1",'
        ' "workspace_id": "q", "repositories": {}}',
        workspace_schema,
        "DuplicateKey",
    )
    _expect_typed(
        "S3a-duplicate-node",
        '{"schema": "qiven-workspace-lock-v1", "workspace_id": "q",'
        f' "generation": "sha256:{D64}",'
        f' "nodes": {{"qiven-foundation": {{"commit": "{Z40}", "tree": "{O40}",'
        f' "declaration": {{"origin": "leaf", "digest": "sha256:{D64}", "shadow_only": false}}}},'
        f' "qiven-foundation": {{"commit": "{Z40}", "tree": "{O40}",'
        f' "declaration": {{"origin": "leaf", "digest": "sha256:{D64}", "shadow_only": false}}}}}}}}',
        lock_schema,
        "DuplicateKey",
    )
    _expect_typed(
        "S5-unknown-field",
        VALID_WORKSPACE.replace(
            '"workspace_id": "qiven",', '"workspace_id": "qiven", "surprise": 1,'
        ),
        workspace_schema,
        "UnknownField",
    )
    _expect_typed(
        "S6-bad-generation",
        VALID_LOCK.replace(f'"generation": "sha256:{D64}"', f'"generation": "sha256:{D64[:-1]}"'),
        lock_schema,
        "PatternMismatch",
    )
    _expect_typed(
        "S7a-bad-kind",
        VALID_DEPS.replace('"kind": "first-party-source"', '"kind": "magic"'),
        deps_schema,
        "EnumMismatch",
    )
    _expect_typed(
        "S8-float-rejected",
        VALID_DEPS.replace(
            '"kind": "first-party-source",', '"kind": "first-party-source", "amount": 1.5,'
        ),
        deps_schema,
        "FloatRejected",
    )
    _expect_typed(
        "S9-bad-node-id",
        VALID_LOCK.replace('"qiven-foundation"', '"Qiven-Foundation"'),
        lock_schema,
        "PatternMismatch",
    )
    _expect_typed(
        "S10-not-unique",
        VALID_DEPS.replace('["windows"]', '["windows", "windows"]'),
        deps_schema,
        "NotUnique",
    )
    _expect_typed(
        "S11-wrong-const",
        VALID_WORKSPACE.replace('"qiven-workspace-v1"', '"qiven-workspace-v2"'),
        workspace_schema,
        "ConstMismatch",
    )
    _expect_typed(
        "S12-missing-required",
        VALID_WORKSPACE.replace('"workspace_id": "qiven",', ""),
        workspace_schema,
        "MissingField",
    )

    # S1: the shipped schema documents themselves parse under the strict law.
    for name in (
        "qiven-workspace-v1.schema.json",
        "qiven-workspace-lock-v1.schema.json",
        "qiven-dependencies-v1.schema.json",
    ):
        doc = ws.load_schema(name)
        assert isinstance(doc, dict) and "properties" in doc, f"S1: {name} malformed"

    # S13: the CLI path round-trips one pass and one fail through files.
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "workspace.json"
        good.write_text(VALID_WORKSPACE, encoding="utf-8")
        rc_pass = ws.main(
            [
                "--check",
                str(good),
                "--schema",
                str(ws.SCHEMA_DIR / "qiven-workspace-v1.schema.json"),
            ]
        )
        assert rc_pass == 0, "S13: CLI pass path returned non-zero"
        bad = Path(tmp) / "bad.json"
        bad.write_text(
            VALID_WORKSPACE.replace('"workspace_id": "qiven",', '"workspace_id": "qiven", "x": "y",'),
            encoding="utf-8",
        )
        rc_fail = ws.main(
            [
                "--check",
                str(bad),
                "--schema",
                str(ws.SCHEMA_DIR / "qiven-workspace-v1.schema.json"),
            ]
        )
        assert rc_fail == 1, "S13: CLI fail path did not return 1"

    print("[ OK ] workspace-schemas self-test (S1-S13)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
