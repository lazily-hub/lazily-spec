"""Schema-vs-fixture drift tests for the lazily wire protocol.

These tests are the permanent guard against the schema drift this repo
previously suffered: ``schemas/snapshot.json`` and ``schemas/delta.json`` had
silently drifted to a stale ``slot_id`` / base64 / ``"type"``-discriminant form
that contradicted the normative ``protocol.md`` (externally-tagged, byte-array,
``node``) form every binding actually serializes.

Every IPC conformance fixture's ``wire`` field MUST validate against its schema,
and the schemas MUST reject the stale form. If a future edit re-introduces the
drift, these tests fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import jsonschema
from referencing import Registry
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
FIXTURE_DIR = ROOT / "conformance"

_SCHEMA_NAMES = [
    "defs",
    "snapshot",
    "delta",
    "distributed",
    "ffi",
    "signaling",
    "statechart",
]


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text())


def _load_schemas() -> dict[str, dict]:
    return {
        f"https://lazily.dev/schemas/{name}.json": _load_schema(name)
        for name in _SCHEMA_NAMES
    }


def _registry() -> Registry:
    schemas = _load_schemas()
    resources = [
        (uri, DRAFT202012.create_resource(schema)) for uri, schema in schemas.items()
    ]
    return Registry().with_resources(resources)


def _validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schemas = _load_schemas()
    return jsonschema.Draft202012Validator(
        schemas[f"https://lazily.dev/schemas/{schema_name}.json"],
        registry=_registry(),
    )


# ---------------------------------------------------------------------------
# Meta: every schema is itself a valid Draft 2020-12 document
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _SCHEMA_NAMES)
def test_schema_is_meta_valid(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(_load_schema(name))


# ---------------------------------------------------------------------------
# Every IPC conformance fixture validates against its schema
# ---------------------------------------------------------------------------

_FIXTURE_TO_SCHEMA = [
    ("snapshot_minimal.json", "snapshot"),
    ("snapshot_multi_node.json", "snapshot"),
    ("snapshot_shared_blob.json", "snapshot"),
    ("delta_sequential.json", "delta"),
    ("delta_non_sequential.json", "delta"),
    ("delta_shared_blob.json", "delta"),
]


@pytest.mark.parametrize("fixture,schema", _FIXTURE_TO_SCHEMA)
def test_fixture_wire_validates_schema(fixture: str, schema: str) -> None:
    fixture_obj = json.loads((FIXTURE_DIR / fixture).read_text())
    assert fixture_obj["protocol_version"] == 1
    wire = fixture_obj["wire"]
    errors = sorted(_validator(schema).iter_errors(wire), key=lambda e: list(e.path))
    assert not errors, (
        f"{fixture} wire does not validate against {schema}.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


# ---------------------------------------------------------------------------
# Regression: the stale (slot_id / base64 / "type" discriminant) form is REJECTED
# ---------------------------------------------------------------------------


def test_stale_snapshot_form_with_slot_id_is_rejected() -> None:
    # The exact shape the old snapshot.json described — which contradicts protocol.md.
    stale = {
        "Snapshot": {
            "epoch": 1,
            "nodes": [
                {"node": 1, "type_tag": "i32", "state": {"Payload": [1]}, "slot_id": 1}
            ],
            "edges": [],
            "roots": [1],
        }
    }
    assert _validator("snapshot").iter_errors(stale), (
        "schema must reject extra `slot_id` (the stale SlotId-based addressing)"
    )


def test_stale_base64_payload_is_rejected() -> None:
    stale = {
        "Snapshot": {
            "epoch": 1,
            "nodes": [
                {"node": 1, "type_tag": "i32", "state": "AAAAAQID"}  # base64 str
            ],
            "edges": [],
            "roots": [1],
        }
    }
    assert _validator("snapshot").iter_errors(stale), (
        "schema must reject base64 state bytes (normative form is a u8 array)"
    )


def test_stale_type_discriminant_envelope_is_rejected() -> None:
    # Stale envelope used {"type": "snapshot"} instead of {"Snapshot": {...}}.
    stale = {"type": "snapshot", "epoch": 1, "nodes": [], "edges": [], "roots": []}
    assert _validator("snapshot").iter_errors(stale), (
        "schema must reject the `type`-discriminant envelope (normative is externally-tagged)"
    )


def test_stale_lowercase_base64_delta_op_is_rejected() -> None:
    stale = {
        "Delta": {
            "base_epoch": 1,
            "epoch": 2,
            "ops": [{"cell_set": {"node": 1, "payload": "Cg=="}}],
        }
    }
    assert _validator("delta").iter_errors(stale), (
        "schema must reject lowercase-snake_case base64 delta ops "
        "(normative is PascalCase externally-tagged, u8-array payloads)"
    )


# ---------------------------------------------------------------------------
# CrdtSync message (distributed.json root) — the third IpcMessage variant
# ---------------------------------------------------------------------------


def test_crdt_sync_message_validates_with_keyed_and_keyless_ops() -> None:
    msg = {
        "CrdtSync": {
            "frontier": [[1, {"wall_time": 5, "logical": 0, "peer": 1}]],
            "ops": [
                {  # keyless op: key is null (matches lazily-rs derived struct)
                    "node": 1,
                    "key": None,
                    "stamp": {"wall_time": 5, "logical": 0, "peer": 1},
                    "state": {"Inline": [1]},
                },
                {  # keyed op with shared-blob state
                    "node": 2,
                    "key": "scores/alice",
                    "stamp": {"wall_time": 6, "logical": 1, "peer": 2},
                    "state": {
                        "SharedBlob": {
                            "offset": 0,
                            "len": 3,
                            "generation": 1,
                            "epoch": 1,
                            "checksum": 9,
                        }
                    },
                },
            ],
        }
    }
    errors = list(_validator("distributed").iter_errors(msg))
    assert not errors, "\n".join(f"  - {e.message}" for e in errors)


def test_crdt_sync_rejects_peer_id_field_name() -> None:
    # WireStamp uses `peer`, NOT `peer_id`. Regression for the old HLCStamp shape.
    bad = {
        "CrdtSync": {
            "frontier": [[1, {"wall_time": 5, "logical": 0, "peer_id": 1}]],
            "ops": [],
        }
    }
    assert _validator("distributed").iter_errors(bad), (
        "WireStamp must use `peer` (not `peer_id`)"
    )


# ---------------------------------------------------------------------------
# NodeKey bounds: empty/leading/double-slash paths are rejected by the pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key", ["", "/leading", "trailing/", "a//b", "a/", "/a"]
)
def test_node_key_pattern_rejects_empty_segments(bad_key: str) -> None:
    snap = {
        "Snapshot": {
            "epoch": 1,
            "nodes": [
                {"node": 1, "type_tag": "i32", "state": {"Payload": [1]}, "key": bad_key}
            ],
            "edges": [],
            "roots": [1],
        }
    }
    assert _validator("snapshot").iter_errors(snap), (
        f"NodeKey pattern must reject empty-segment path {bad_key!r}"
    )


def test_node_key_valid_path_validates() -> None:
    snap = {
        "Snapshot": {
            "epoch": 1,
            "nodes": [
                {
                    "node": 1,
                    "type_tag": "i32",
                    "state": {"Payload": [1]},
                    "key": "outer/k1/inner/k2",
                }
            ],
            "edges": [],
            "roots": [1],
        }
    }
    assert not list(_validator("snapshot").iter_errors(snap))


# ---------------------------------------------------------------------------
# Signaling frames (conformance/signaling/) — every variant validates
# ---------------------------------------------------------------------------

_SIGNALING_DIR = FIXTURE_DIR / "signaling"


def _signaling_frames() -> list[dict]:
    path = _SIGNALING_DIR / "frames.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text())["frames"]


@pytest.mark.parametrize(
    "frame", _signaling_frames(), ids=lambda f: f["label"]
)
def test_signaling_frame_validates_schema(frame: dict) -> None:
    errors = sorted(
        _validator("signaling").iter_errors(frame["wire"]), key=lambda e: list(e.path)
    )
    assert not errors, (
        f"signaling frame {frame['label']!r} does not validate against signaling.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_signaling_forwarded_frames_carry_from_not_to() -> None:
    """Anti-spoof: server->client forwarded frames carry `from`, never `to`."""
    for frame in _signaling_frames():
        if frame["direction"] == "server" and frame["variant"] in {
            "offer",
            "answer",
            "ice",
            "relay",
        }:
            wire = frame["wire"]
            assert "from" in wire and "to" not in wire, (
                f"{frame['label']}: forwarded frame must carry server-stamped `from`, not `to`"
            )


def test_signaling_client_directed_frames_carry_to_not_from() -> None:
    for frame in _signaling_frames():
        if frame["direction"] == "client" and frame["variant"] in {
            "offer",
            "answer",
            "ice",
            "relay",
        }:
            wire = frame["wire"]
            assert "to" in wire and "from" not in wire, (
                f"{frame['label']}: client directed frame must carry `to`, not `from`"
            )


def test_signaling_welcome_roster_excludes_self() -> None:
    for frame in _signaling_frames():
        if frame["variant"] == "welcome":
            wire = frame["wire"]
            assert wire["peer"] not in wire["peers"], (
                f"{frame['label']}: welcome roster must exclude the joining peer's own id"
            )


def test_signaling_stale_camelcase_tag_is_rejected() -> None:
    # kebab-case tags are normative: peerJoined / peer_joined must be rejected.
    for bad in ({"type": "peerJoined", "peer": 5}, {"type": "peer_joined", "peer": 5}):
        assert _validator("signaling").iter_errors(bad), (
            "signaling schema must reject non-kebab-case peer-joined tag"
        )


def test_signaling_anti_spoof_session_frames_validate() -> None:
    """The routing transcript's every emitted frame validates against the schema,
    and forwarded frames rewrite `to` -> server-stamped `from`."""
    path = _SIGNALING_DIR / "anti_spoof_session.json"
    if not path.is_file():
        return
    session = json.loads(path.read_text())
    assert session["protocol_version"] == 1
    for step in session["steps"]:
        recv = step["input"]["recv"]
        assert not list(_validator("signaling").iter_errors(recv)), (
            f"session input {recv} does not validate"
        )
        for out in step["expect"]:
            frame = out["frame"]
            assert not list(_validator("signaling").iter_errors(frame)), (
                f"session output {frame} does not validate"
            )
            if frame["type"] in {"offer", "answer", "ice", "relay"}:
                assert "from" in frame and "to" not in frame, (
                    f"forwarded {frame['type']} must carry server-stamped `from`"
                )


# ---------------------------------------------------------------------------
# Distributed CrdtSync frames (conformance/distributed/) — every variant validates
# ---------------------------------------------------------------------------

_DISTRIBUTED_DIR = FIXTURE_DIR / "distributed"


def _crdt_sync_frames() -> list[dict]:
    path = _DISTRIBUTED_DIR / "crdt_sync_frames.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text())["frames"]


@pytest.mark.parametrize(
    "frame", _crdt_sync_frames(), ids=lambda f: f["label"]
)
def test_crdt_sync_frame_validates_schema(frame: dict) -> None:
    errors = sorted(
        _validator("distributed").iter_errors(frame["wire"]), key=lambda e: list(e.path)
    )
    assert not errors, (
        f"CrdtSync frame {frame['label']!r} does not validate against distributed.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_anti_entropy_converge_scenarios_well_formed() -> None:
    """Structural guard for the distributed CRDT-plane replay fixture (bindings
    replay it against their CrdtPlaneRuntime; here we only assert the shape)."""
    path = _DISTRIBUTED_DIR / "anti_entropy_converge.json"
    if not path.is_file():
        return
    obj = json.loads(path.read_text())
    assert obj["kind"] == "Distributed" and obj["model"] == "CrdtPlane"
    scenarios = obj["scenarios"]
    assert isinstance(scenarios, list) and scenarios
    for sc in scenarios:
        assert isinstance(sc.get("name"), str) and sc["name"]
        assert isinstance(sc.get("ops"), list) and sc["ops"]
        # every op must itself be a schema-valid CrdtOp (wrap as a one-op CrdtSync)
        for op in sc["ops"]:
            msg = {"CrdtSync": {"frontier": [], "ops": [op]}}
            assert not list(_validator("distributed").iter_errors(msg)), (
                f"scenario {sc['name']!r} op does not validate: {op}"
            )
        expect = sc["expect"]
        assert "converged" in expect and isinstance(expect["converged"], list)


# ---------------------------------------------------------------------------
# Keyed cell collection fixtures (conformance/collections/) — structural guard
# ---------------------------------------------------------------------------

_COLLECTIONS_DIR = FIXTURE_DIR / "collections"


def _collection_fixtures() -> list[str]:
    if not _COLLECTIONS_DIR.is_dir():
        return []
    return sorted(p.name for p in _COLLECTIONS_DIR.glob("*.json"))


# Keyed-collection models: top-level `steps`/`reconcile` keyed reactivity.
_KEYED_MODELS = {"CellMap", "CellTree"}
# Compute/convergence models: `scenarios`-based CRDT / semantic-tree fixtures.
_SCENARIO_MODELS = {"SemTree", "SeqCrdt", "StableId", "TextCrdt"}
_KNOWN_MODELS = _KEYED_MODELS | _SCENARIO_MODELS


@pytest.mark.parametrize("name", _collection_fixtures())
def test_collection_fixture_is_well_formed(name: str) -> None:
    """Guard against malformed-JSON / shape drift in the collections fixtures.

    These are compute fixtures (replayed by each binding, like the statechart
    fixtures), so this asserts only the language-agnostic top-level shape, not
    any binding's runtime semantics.
    """
    obj = json.loads((_COLLECTIONS_DIR / name).read_text())
    assert obj["kind"] == "Collection", f"{name}: kind must be 'Collection'"
    assert obj["model"] in _KNOWN_MODELS, f"{name}: unknown model {obj['model']!r}"
    assert isinstance(obj["description"], str) and obj["description"], f"{name}: missing description"

    if obj["model"] in _SCENARIO_MODELS:
        scenarios = obj.get("scenarios")
        assert isinstance(scenarios, list) and scenarios, f"{name}: model {obj['model']!r} needs non-empty 'scenarios'"
        for sc in scenarios:
            assert isinstance(sc.get("name"), str) and sc["name"], f"{name}: scenario missing name"
            has_expect = any(
                k in sc for k in ("expect", "expect_initial", "expect_after")
            )
            assert has_expect, f"{name}: scenario {sc['name']!r} missing an expect* field"
        return

    assert "reconcile" in obj or "steps" in obj, f"{name}: must define 'steps' or 'reconcile'"
    if "steps" in obj:
        for step in obj["steps"]:
            assert "op" in step and "expected" in step, f"{name}: step missing op/expected"
            assert "invalidates" in step["expected"], f"{name}: expected missing 'invalidates'"
            inv = step["expected"]["invalidates"]
            assert set(inv) >= {"value", "membership", "order"}, (
                f"{name}: invalidates must name value/membership/order reader classes"
            )
