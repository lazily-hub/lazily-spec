"""Structural contract for the graph IR compute document.

The schema is not a wire message. These tests pin the examples and the
rejections a host closure or a Snapshot envelope must hit. Cycle detection is
semantic: ``examples/graph-ir/cycle.json`` is schema-valid and the reference
interpreter rejects it.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from referencing import Registry
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "graph-ir.json").read_text())
EXAMPLES = ROOT / "examples" / "graph-ir"
VALID = [
    "counter.json",
    "counter-edit.json",
    "dynamic.json",
    "policy.json",
    "structures.json",
    "cycle.json",
]


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(SCHEMA)


def _errors(document: object) -> list[jsonschema.ValidationError]:
    return sorted(_validator().iter_errors(document), key=lambda error: list(error.path))


def test_graph_ir_schema_is_meta_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_examples_match_the_schema() -> None:
    for name in VALID:
        document = json.loads((EXAMPLES / name).read_text())
        errors = _errors(document)
        assert not errors, name + "\n" + "\n".join(error.message for error in errors)


def test_empty_graph_is_a_document() -> None:
    assert not _errors({"kind": "graph", "ir": "1", "nodes": []})


def test_cycle_is_structurally_valid() -> None:
    document = json.loads((EXAMPLES / "cycle.json").read_text())
    assert document["nodes"][0]["expr"] == {"ref": "b"}
    assert not _errors(document)


pytest_rejects = [
    ("snapshot", {"Snapshot": {"epoch": 0, "nodes": [], "edges": [], "roots": []}}),
    ("delta", {"Delta": {"epoch": 0, "ops": []}}),
    ("string formula", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "c", "kind": "computed", "expr": {"expr": "count + 1"}}
    ]}),
    ("host closure", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "c", "kind": "computed", "expr": {"fn": "sum"}}
    ]}),
    ("source expr", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "s", "kind": "source", "init": 1, "expr": {"lit": 1}}
    ]}),
    ("missing init", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "s", "kind": "source"}
    ]}),
    ("bad version", {"kind": "graph", "ir": "2", "nodes": []}),
    ("bad id", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "1count", "kind": "source", "init": 0}
    ]}),
    ("unknown policy", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "s", "kind": "source", "init": 0, "policy": "product"}
    ]}),
    ("eager string", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "c", "kind": "computed", "eager": "yes", "expr": {"lit": 1}}
    ]}),
    ("add arity", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "c", "kind": "computed", "expr": {"op": "add", "args": [{"lit": 1}]}}
    ]}),
    ("unknown op", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "c", "kind": "computed", "expr": {"op": "pow", "args": [{"lit": 2}, {"lit": 3}]}}
    ]}),
    ("effect string", {"kind": "graph", "ir": "1", "nodes": [
        {"id": "e", "kind": "effect", "body": "log"}
    ]}),
    ("empty edit", {"kind": "edit", "ir": "1", "ops": []}),
    ("remove without id", {"kind": "edit", "ir": "1", "ops": [{"op": "remove"}]}),
]


def test_rejections() -> None:
    for name, document in pytest_rejects:
        assert _errors(document), name


def test_graph_document_is_not_a_snapshot() -> None:
    graph = json.loads((EXAMPLES / "counter.json").read_text())
    defs = json.loads((ROOT / "schemas" / "defs.json").read_text())
    snapshot = json.loads((ROOT / "schemas" / "snapshot.json").read_text())
    registry = Registry().with_resources([
        (
            "https://lazily.dev/schemas/defs.json",
            DRAFT202012.create_resource(defs),
        ),
        (
            "https://lazily.dev/schemas/snapshot.json",
            DRAFT202012.create_resource(snapshot),
        ),
    ])
    validator = jsonschema.Draft202012Validator(snapshot, registry=registry)
    assert list(validator.iter_errors(graph))
    assert _errors({"Snapshot": {"epoch": 0, "nodes": [], "edges": [], "roots": []}})
