"""Strict validation for the qiven workspace schema family (WR-1, ADR-0052).

Validates workspace.json, workspace.lock.json and .qiven/dependencies.json
against the schema documents in docs/schemas/ using a stdlib-only
JSON-Schema-subset engine. Strictness is the contract (architecture doc 01
section 10): duplicate JSON keys, floats, numbers outside the integer
vocabulary, unknown fields and non-canonical identifiers are typed
rejections, never warnings.

Usage (exit 0 pass / 1 validation failure / 2 environment or usage error):
    python tools/workspace_schemas.py --check <file> --schema <schema-file>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_DEVKIT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = _DEVKIT_ROOT / "docs" / "schemas"

INT_SAFE_LIMIT = 1 << 53

_TYPE_NAMES = {
    str: "string",
    bool: "boolean",
    dict: "object",
    list: "array",
    int: "integer",
    type(None): "null",
}


class SchemaError(Exception):
    """A typed schema failure carrying a JSON path for diagnostics."""

    def __init__(self, error_type: str, path: str, message: str) -> None:
        super().__init__(f"{error_type} at {path or '<root>'}: {message}")
        self.error_type = error_type
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"type": self.error_type, "path": self.path, "message": self.message}


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise SchemaError("DuplicateKey", "", f'duplicate object key "{key}"')
        seen.add(key)
    return dict(pairs)


def _walk_vocabulary(value: Any, path: str) -> None:
    """Reject floats and out-of-range integers anywhere in the document."""
    if isinstance(value, float):
        raise SchemaError("FloatRejected", path, "floats are outside the integer vocabulary")
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > INT_SAFE_LIMIT:
            raise SchemaError(
                "NonIntegerVocabulary",
                path,
                f"integer {value} outside the safe-integer range",
            )
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_vocabulary(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_vocabulary(child, f"{path}[{index}]")


def parse_strict(text: str) -> Any:
    """Parse JSON with duplicate-key rejection and integer-vocabulary law."""
    value = json.loads(text, object_pairs_hook=_pairs_hook)
    _walk_vocabulary(value, "")
    return value


def load_strict(path: Path) -> Any:
    return parse_strict(path.read_text(encoding="utf-8-sig"))


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):  # bool is an int subclass; check it first
        return "boolean"
    for native, name in _TYPE_NAMES.items():
        if native is not bool and isinstance(value, native):
            return name
    return "unknown"


def _validate(value: Any, schema: dict[str, Any], path: str) -> list[SchemaError]:
    errors: list[SchemaError] = []

    expected = schema.get("type")
    if expected is not None:
        actual = _json_type_name(value)
        if actual != expected:
            errors.append(
                SchemaError("TypeMismatch", path, f"expected {expected}, got {actual}")
            )
            return errors  # further keywords would only cascade noise

    if "const" in schema and value != schema["const"]:
        errors.append(
            SchemaError("ConstMismatch", path, f"expected const {schema['const']!r}")
        )
    if "enum" in schema and value not in schema["enum"]:
        errors.append(SchemaError("EnumMismatch", path, f"{value!r} not in {schema['enum']}"))

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(SchemaError("PatternMismatch", path, f"{value!r} fails /{pattern}/"))
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            errors.append(SchemaError("TooShort", path, f"shorter than {min_length}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(SchemaError("TooFewItems", path, f"fewer than {min_items} items"))
        if schema.get("uniqueItems") and len(value) != len({json.dumps(i, sort_keys=True) for i in value}):
            errors.append(SchemaError("NotUnique", path, "array items are not unique"))
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                errors.extend(_validate(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(SchemaError("MissingField", path, f'required field "{name}" absent'))
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            name_schema = schema.get("propertyNames")
            if name_schema is not None:
                errors.extend(_validate(key, name_schema, child_path))
            if key in properties:
                errors.extend(_validate(child, properties[key], child_path))
            elif additional is False:
                errors.append(SchemaError("UnknownField", child_path, "field not in schema"))
            elif isinstance(additional, dict):
                errors.extend(_validate(child, additional, child_path))

    return errors


def validate(instance: Any, schema: dict[str, Any]) -> list[SchemaError]:
    return _validate(instance, schema, "")


def load_schema(name: str) -> dict[str, Any]:
    """Load a schema document from docs/schemas/ by file name."""
    return load_strict(SCHEMA_DIR / name)


def check_file(instance_path: Path, schema_path: Path) -> list[SchemaError]:
    schema = load_strict(schema_path)
    try:
        instance = load_strict(instance_path)
    except SchemaError as error:
        return [error]
    return validate(instance, schema)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict qiven workspace schema validator")
    parser.add_argument("--check", metavar="FILE", help="instance file to validate")
    parser.add_argument("--schema", metavar="FILE", help="schema document to validate against")
    args = parser.parse_args(argv)

    if not args.check or not args.schema:
        parser.print_usage(sys.stderr)
        return 2

    instance_path = Path(args.check)
    schema_path = Path(args.schema)
    if not instance_path.is_file():
        print(f"[FAIL] instance file not found: {instance_path}", file=sys.stderr)
        return 2
    if not schema_path.is_file():
        print(f"[FAIL] schema file not found: {schema_path}", file=sys.stderr)
        return 2

    print(f"[ RUN] schema-check {instance_path.name} against {schema_path.name}")
    errors = check_file(instance_path, schema_path)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print("[ OK ] schema-check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
