"""Fail-closed JSON Schema coverage for conformance assertion blocks."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_assertion_block_schema as generator  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "assertion-blocks.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _record(fixture: str, pointer: str, value: dict) -> dict:
    return {"fixture": fixture, "pointer": pointer, "value": value}


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_schema())


def _records() -> list[tuple[str, str, dict]]:
    return generator.records()


def test_assertion_block_schema_is_meta_valid_and_generated() -> None:
    schema = _schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema == generator.build_schema(), (
        "assertion-block schema drifted from the canonical corpus; run "
        "`python3 scripts/gen_assertion_block_schema.py`"
    )


def test_every_assertion_block_validates_and_every_route_is_live() -> None:
    schema = _schema()
    validator = _validator()
    actual_routes = set()
    for fixture, pointer, value in _records():
        errors = list(validator.iter_errors(_record(fixture, pointer, value)))
        assert not errors, (
            f"{fixture}#{pointer} does not validate:\n"
            + "\n".join(f"  - {error.message}" for error in errors)
        )
        actual_routes.add((fixture, pointer))

    declared_routes = {
        (route["fixture"], route["pointer"])
        for route in schema["x-fixture-routes"]
    }
    assert declared_routes == actual_routes, (
        "the route ledger must be exact in both directions: no unvalidated "
        "corpus block and no stale schema route"
    )


def test_unknown_assertion_key_is_rejected_in_every_fixture_area() -> None:
    validator = _validator()
    representative_by_area = {}
    for fixture, pointer, value in _records():
        area = fixture.split("/", 1)[0] if "/" in fixture else "<root>"
        representative_by_area.setdefault(area, (fixture, pointer, value))

    # This proves the formerly schema-less families (including collections,
    # ingress, materialization, reactive-graph, and temporal) are under the same
    # fail-closed additionalProperties guard as the wire-focused families.
    for area, (fixture, pointer, value) in representative_by_area.items():
        mutated = copy.deepcopy(value)
        mutated["__unknown_assertion__"] = True
        assert list(
            validator.iter_errors(_record(fixture, pointer, mutated))
        ), f"{area}: an unknown assertion key must be rejected"


def test_missing_required_assertion_key_is_rejected() -> None:
    schema = _schema()
    records = {
        (fixture, pointer): value for fixture, pointer, value in _records()
    }
    for route in schema["x-fixture-routes"]:
        block_schema = schema["$defs"][route["schema"]]
        required = block_schema.get("required", [])
        value = records[(route["fixture"], route["pointer"])]
        present_required = [key for key in required if key in value]
        if present_required:
            mutated = copy.deepcopy(value)
            del mutated[present_required[0]]
            assert list(
                _validator().iter_errors(
                    _record(route["fixture"], route["pointer"], mutated)
                )
            )
            return
    pytest.fail("corpus exposed no required assertion key to mutation-check")


def test_assertion_value_type_drift_is_rejected() -> None:
    schema = _schema()
    records = {
        (fixture, pointer): value for fixture, pointer, value in _records()
    }
    incompatible = {
        "null": 0,
        "boolean": "not-a-boolean",
        "integer": "not-an-integer",
        "number": "not-a-number",
        "string": {},
        "array": {},
        "object": [],
    }
    for route in schema["x-fixture-routes"]:
        block_schema = schema["$defs"][route["schema"]]
        value = records[(route["fixture"], route["pointer"])]
        for key in block_schema.get("required", []):
            property_schema = block_schema["properties"][key]
            kind = property_schema.get("type")
            if isinstance(kind, str) and key in value:
                mutated = copy.deepcopy(value)
                mutated[key] = incompatible[kind]
                assert list(
                    _validator().iter_errors(
                        _record(route["fixture"], route["pointer"], mutated)
                    )
                )
                return
    pytest.fail("corpus exposed no simple required assertion value to mutation-check")


def test_unknown_fixture_pointer_route_is_rejected() -> None:
    fixture, _, value = _records()[0]
    assert list(
        _validator().iter_errors(
            _record(fixture, "/__unknown_assertion_route__", value)
        )
    )
