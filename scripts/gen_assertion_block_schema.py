#!/usr/bin/env python3
"""Generate the fail-closed schema for canonical assertion blocks.

The conformance corpus uses three historical spellings for executable output
claims: ``assertions``, ``expect``, and ``expected``. This generator inventories
all three, normalizes array indexes in their JSON pointers, and emits one routed
Draft 2020-12 schema. The generated artifact is checked in so a fixture edit
must carry an explicit schema update rather than silently teaching every runner
a new key.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "conformance"
OUTPUT = ROOT / "schemas" / "assertion-blocks.json"
BLOCK_NAMES = frozenset({"assertions", "expect", "expected"})

Json = Any
Route = tuple[str, str]


def fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.rglob("*.json"))


def _pointer(parts: Sequence[str | int]) -> str:
    encoded = []
    for part in parts:
        if isinstance(part, int):
            encoded.append("*")
        else:
            encoded.append(part.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(encoded)


def iter_assertion_blocks(
    value: Json, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[str, dict[str, Json]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key in BLOCK_NAMES and isinstance(child, dict):
                yield _pointer(child_path), child
            yield from iter_assertion_blocks(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_assertion_blocks(child, (*path, index))


def records() -> list[tuple[str, str, dict[str, Json]]]:
    found = []
    for path in fixture_paths():
        fixture = path.relative_to(FIXTURE_DIR).as_posix()
        document = json.loads(path.read_text())
        for pointer, block in iter_assertion_blocks(document):
            found.append((fixture, pointer, block))
    return found


def _kind(value: Json) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _schema_for_kind(kind: str, values: Sequence[Json]) -> dict[str, Json]:
    if kind == "object":
        keys = sorted({key for value in values for key in value})
        required = set(values[0])
        for value in values[1:]:
            required.intersection_update(value)
        schema: dict[str, Json] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                key: infer_schema([value[key] for value in values if key in value])
                for key in keys
            },
        }
        if required:
            schema["required"] = sorted(required)
        return schema
    if kind == "array":
        items = [item for value in values for item in value]
        schema = {"type": "array"}
        if items:
            schema["items"] = infer_schema(items)
        return schema
    return {"type": kind}


def infer_schema(values: Sequence[Json]) -> dict[str, Json]:
    grouped: dict[str, list[Json]] = defaultdict(list)
    for value in values:
        grouped[_kind(value)].append(value)

    # JSON integers are numbers too. A route carrying both forms should accept
    # the wider JSON number domain without a redundant anyOf branch.
    if "integer" in grouped and "number" in grouped:
        grouped["number"].extend(grouped.pop("integer"))

    order = ("null", "boolean", "integer", "number", "string", "array", "object")
    branches = [
        _schema_for_kind(kind, grouped[kind]) for kind in order if kind in grouped
    ]
    if len(branches) == 1:
        return branches[0]
    return {"anyOf": branches}


def build_schema(
    source_records: Iterable[tuple[str, str, dict[str, Json]]] | None = None,
) -> dict[str, Json]:
    grouped: dict[Route, list[dict[str, Json]]] = defaultdict(list)
    for fixture, pointer, block in source_records or records():
        grouped[(fixture, pointer)].append(block)

    definitions: dict[str, Json] = {}
    route_cases = []
    route_ledger = []
    for index, ((fixture, pointer), blocks) in enumerate(sorted(grouped.items()), 1):
        name = f"route_{index:04d}"
        definitions[name] = infer_schema(blocks)
        route_cases.append(
            {
                "title": f"{fixture}#{pointer}",
                "properties": {
                    "fixture": {"const": fixture},
                    "pointer": {"const": pointer},
                    "value": {"$ref": f"#/$defs/{name}"},
                },
            }
        )
        route_ledger.append(
            {"fixture": fixture, "pointer": pointer, "schema": name}
        )

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://lazily.dev/schemas/assertion-blocks.json",
        "title": "Lazily canonical conformance assertion block",
        "description": (
            "Fail-closed routed schemas for every assertions/expect/expected "
            "object in the canonical corpus. Array indexes in pointers are "
            "normalized to '*'. Generated by scripts/gen_assertion_block_schema.py."
        ),
        "type": "object",
        "required": ["fixture", "pointer", "value"],
        "additionalProperties": False,
        "properties": {
            "fixture": {"type": "string"},
            "pointer": {"type": "string", "pattern": "^/"},
            "value": {"type": "object"},
        },
        "oneOf": route_cases,
        "$defs": definitions,
        "x-block-names": sorted(BLOCK_NAMES),
        "x-fixture-routes": route_ledger,
    }


def rendered_schema() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when schemas/assertion-blocks.json is not regenerated",
    )
    args = parser.parse_args()
    rendered = rendered_schema()
    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != rendered:
            print(
                "schemas/assertion-blocks.json is stale; run "
                "python3 scripts/gen_assertion_block_schema.py",
                file=sys.stderr,
            )
            return 1
        return 0
    OUTPUT.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
