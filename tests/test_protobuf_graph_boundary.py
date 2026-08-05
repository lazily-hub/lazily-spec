import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
PROTO = ROOT / "proto/lazily/graph_boundary/v1/graph_boundary.proto"
LEDGER = ROOT / "proto/field-ledger.json"
FIXTURE = ROOT / "conformance/protobuf/graph_boundary_traces.json"
SCHEMA = ROOT / "schemas/protobuf-graph-boundary-fixture.json"


def test_graph_boundary_fixture_validates() -> None:
    fixture = json.loads(FIXTURE.read_text())
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)
    assert len({trace["id"] for trace in fixture["scenarios"]}) == 6


def test_proto_keeps_snapshots_out_of_the_splice_shape() -> None:
    proto = PROTO.read_text()
    graph_input = re.search(r"message GraphInput \{(?P<body>.*?)\n\}", proto, re.S)
    assert graph_input is not None
    body = graph_input.group("body")
    assert "CellTextSplice cell_text_splice = 4;" in body
    assert "GraphSnapshot bootstrap_snapshot = 5;" in body
    splice = re.search(r"message CellTextSplice \{(?P<body>.*?)\n\}", proto, re.S)
    assert splice is not None
    assert "GraphSnapshot" not in splice.group("body")
    assert "document_snapshot" not in splice.group("body")


def test_field_ledger_classifies_every_boundary_family() -> None:
    ledger = json.loads(LEDGER.read_text())
    assert ledger["package"] == "lazily.graph_boundary.v1"
    assert ledger["canonical_logical_hash"] == "canonical-json-fnv1a64"
    assert ledger["capability"] == {
        "codec": "protobuf",
        "feature": "protobuf-graph-boundary-v1",
        "default": "disabled",
        "rule": (
            "Both peers must advertise the codec, feature, and an overlapping "
            "protocol range."
        ),
    }
    assert set(ledger["binding_parity"]) == {
        "rust",
        "kotlin",
        "typescript",
        "python",
        "go",
        "cpp",
        "dart",
        "zig",
        "csharp",
    }
    assert {
        binding
        for binding, state in ledger["binding_parity"].items()
        if state == "generated-and-six-trace-conformant"
    } == {"rust", "kotlin", "typescript"}
    assert set(ledger["messages"]) == {
        "ProtocolEnvelope",
        "CellTextSplice",
        "DerivedProjection",
        "EffectIntent",
        "DeliveryReceipt",
    }
    assert "reserved 9 to 19;" in PROTO.read_text()
