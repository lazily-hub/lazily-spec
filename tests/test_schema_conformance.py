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
    "receipts",
    "lossless-tree",
    "lossless-tree-delta",
    "message-passing",
    "reliable-sync",
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
    ("delta_zero_copy_arrow.json", "delta"),
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
# Causal receipt fixtures — generic outcome projection, not transport ACKs
# ---------------------------------------------------------------------------

_RECEIPT_DIR = FIXTURE_DIR / "receipts"


def _receipt_fixtures() -> list[Path]:
    if not _RECEIPT_DIR.is_dir():
        return []
    return sorted(_RECEIPT_DIR.glob("*.json"))


@pytest.mark.parametrize("path", _receipt_fixtures(), ids=lambda p: p.name)
def test_receipt_fixture_validates_schema(path: Path) -> None:
    fixture = json.loads(path.read_text())
    assert fixture["protocol_version"] == 1
    errors = sorted(
        _validator("receipts").iter_errors(fixture["wire"]), key=lambda e: list(e.path)
    )
    assert not errors, (
        f"receipt fixture {path.name!r} does not validate against receipts.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_receipt_schema_rejects_ack_outcome() -> None:
    bad = {
        "CausalReceipts": {
            "receipts": [
                {
                    "receipt_id": "receipt-ack",
                    "causation_id": "patch-123",
                    "observer": "editor",
                    "generation": 7,
                    "outcome": "ack",
                    "reason": None,
                    "payload_hash": None,
                }
            ]
        }
    }
    assert _validator("receipts").iter_errors(bad), (
        "transport ACK must not be a terminal lazily receipt outcome"
    )


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
# Queue models: reactive queue shell + storage backend.
_QUEUE_MODELS = {"QueueCell"}
# Broadcast topic: keyed per-subscriber cursor state and retention.
_TOPIC_MODELS = {"TopicCell"}
# Competing-consumer work queue: pending/in-flight/dead-letter lifecycle.
_WORK_QUEUE_MODELS = {"WorkQueueCell"}
# Compute/convergence models: `scenarios`-based CRDT / semantic-tree fixtures.
_SCENARIO_MODELS = {"SemTree", "SeqCrdt", "StableId", "TextCrdt"}
# Merge-algebra models (#relaycell): `scenarios` of {policy, flags, initial, steps}.
_MERGE_MODELS = {"MergeCell"}
_KNOWN_MODELS = (
    _KEYED_MODELS
    | _QUEUE_MODELS
    | _TOPIC_MODELS
    | _WORK_QUEUE_MODELS
    | _SCENARIO_MODELS
    | _MERGE_MODELS
)


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

    if obj["model"] in _MERGE_MODELS:
        scenarios = obj.get("scenarios")
        assert isinstance(scenarios, list) and scenarios, f"{name}: model {obj['model']!r} needs non-empty 'scenarios'"
        for sc in scenarios:
            assert isinstance(sc.get("policy"), str) and sc["policy"], f"{name}: merge scenario missing 'policy'"
            flags = sc.get("flags")
            assert isinstance(flags, dict) and {"commutative", "idempotent"} <= set(flags), (
                f"{name}: scenario {sc['policy']!r} flags must name commutative + idempotent"
            )
            assert "initial" in sc, f"{name}: scenario {sc['policy']!r} missing 'initial'"
            steps = sc.get("steps")
            assert isinstance(steps, list) and steps, f"{name}: scenario {sc['policy']!r} needs non-empty 'steps'"
            for step in steps:
                assert "merge" in step and "expected" in step, f"{name}: merge step missing merge/expected"
                exp = step["expected"]
                assert "value" in exp and "invalidates" in exp, (
                    f"{name}: merge step expected must name value + invalidates"
                )
        return

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

    if obj["model"] in _TOPIC_MODELS:
        initial = obj.get("initial")
        assert isinstance(initial, dict), f"{name}: TopicCell needs an initial state"
        assert {"base_offset", "elements", "subscriptions"} <= set(initial), (
            f"{name}: TopicCell initial state must name base_offset/elements/subscriptions"
        )

        def assert_topic_state(state: dict, label: str) -> None:
            base_offset = state.get("base_offset")
            elements = state.get("elements")
            subscriptions = state.get("subscriptions")
            assert isinstance(base_offset, int) and base_offset >= 0, (
                f"{name}: {label} needs a non-negative base_offset"
            )
            assert isinstance(elements, list), f"{name}: {label} elements must be an array"
            assert isinstance(subscriptions, dict), (
                f"{name}: {label} subscriptions must be an object"
            )
            end_offset = base_offset + len(elements)
            for sub_id, sub in subscriptions.items():
                assert isinstance(sub_id, str) and sub_id, (
                    f"{name}: subscriber ids must be non-empty"
                )
                assert sub.get("durability") in {"durable", "ephemeral"}, (
                    f"{name}: subscriber {sub_id!r} has invalid durability"
                )
                assert isinstance(sub.get("connected"), bool), (
                    f"{name}: subscriber {sub_id!r} needs boolean connected"
                )
                assert isinstance(sub.get("cursor"), int) and (
                    base_offset <= sub["cursor"] <= end_offset
                ), (
                    f"{name}: subscriber {sub_id!r} cursor must be in the retained offset range"
                )
                assert sub["durability"] != "ephemeral" or sub["connected"], (
                    f"{name}: disconnected ephemeral subscriber {sub_id!r} must be removed"
                )

        assert_topic_state(initial, "initial state")
        steps = obj.get("steps")
        assert isinstance(steps, list) and steps, f"{name}: TopicCell needs non-empty 'steps'"
        for step in steps:
            assert "op" in step and "expected" in step, f"{name}: step missing op/expected"
            exp = step["expected"]
            assert {"base_offset", "elements", "subscriptions", "reads", "invalidates"} <= set(exp), (
                f"{name}: TopicCell expected state is incomplete"
            )
            assert isinstance(exp["subscriptions"], dict), f"{name}: subscriptions must be an object"
            assert isinstance(exp["reads"], dict), f"{name}: reads must be an object"
            assert isinstance(exp["invalidates"], dict), f"{name}: invalidates must be an object"
            assert all(isinstance(v, bool) for v in exp["invalidates"].values()), (
                f"{name}: invalidation values must be booleans"
            )
            assert_topic_state(exp, "expected state")
            assert set(exp["reads"]) <= {
                sub_id
                for sub_id, sub in exp["subscriptions"].items()
                if sub["connected"]
            }, f"{name}: reads may name only connected subscribers"
        return

    if obj["model"] in _WORK_QUEUE_MODELS:
        config = obj.get("config")
        assert isinstance(config, dict), f"{name}: WorkQueueCell needs config"
        assert isinstance(config.get("visibility_timeout"), int) and config["visibility_timeout"] > 0, (
            f"{name}: visibility_timeout must be a positive integer"
        )
        assert isinstance(config.get("max_deliveries"), int) and config["max_deliveries"] >= 1, (
            f"{name}: max_deliveries must be at least one"
        )

        def assert_workqueue_state(state: dict, label: str) -> None:
            assert {"pending", "in_flight", "dead_letters", "reads", "invalidates"} <= set(state), (
                f"{name}: {label} is incomplete"
            )
            assert isinstance(state["pending"], list), f"{name}: {label} pending must be an array"
            assert isinstance(state["in_flight"], list), f"{name}: {label} in_flight must be an array"
            assert isinstance(state["dead_letters"], list), f"{name}: {label} dead_letters must be an array"
            reads = state["reads"]
            assert isinstance(reads, dict) and {
                "pending_len", "is_empty", "in_flight_len", "dead_letter_len"
            } <= set(reads), f"{name}: {label} reads are incomplete"
            assert reads["pending_len"] == len(state["pending"])
            assert reads["is_empty"] is (len(state["pending"]) == 0)
            assert reads["in_flight_len"] == len(state["in_flight"])
            assert reads["dead_letter_len"] == len(state["dead_letters"])
            invalidates = state["invalidates"]
            assert isinstance(invalidates, dict) and {
                "pending_len", "is_empty", "in_flight_len", "dead_letter_len"
            } <= set(invalidates), f"{name}: {label} invalidates are incomplete"
            assert all(isinstance(v, bool) for v in invalidates.values())

        initial = obj.get("initial")
        assert isinstance(initial, dict), f"{name}: WorkQueueCell needs initial state"
        initial_with_observation = {
            **initial,
            "reads": {
                "pending_len": len(initial.get("pending", [])),
                "is_empty": len(initial.get("pending", [])) == 0,
                "in_flight_len": len(initial.get("in_flight", [])),
                "dead_letter_len": len(initial.get("dead_letters", [])),
            },
            "invalidates": {
                "pending_len": False,
                "is_empty": False,
                "in_flight_len": False,
                "dead_letter_len": False,
            },
        }
        assert_workqueue_state(initial_with_observation, "initial state")
        steps = obj.get("steps")
        assert isinstance(steps, list) and steps, f"{name}: WorkQueueCell needs non-empty 'steps'"
        for step in steps:
            assert "op" in step and "expected" in step, f"{name}: step missing op/expected"
            assert_workqueue_state(step["expected"], "expected state")
        return

    assert "reconcile" in obj or "steps" in obj, f"{name}: must define 'steps' or 'reconcile'"
    if "steps" in obj:
        for step in obj["steps"]:
            assert "op" in step and "expected" in step, f"{name}: step missing op/expected"
            assert "invalidates" in step["expected"], f"{name}: expected missing 'invalidates'"
            inv = step["expected"]["invalidates"]
            if obj["model"] in _QUEUE_MODELS:
                valid_kinds = {"head", "len", "is_empty", "is_full", "closed"}
                assert set(inv) <= valid_kinds, (
                    f"{name}: invalidates keys must be in {valid_kinds}"
                )
            else:
                assert set(inv) >= {"value", "membership", "order"}, (
                    f"{name}: invalidates must name value/membership/order reader classes"
                )


# ---------------------------------------------------------------------------
# Reactive graph disposal / teardown scopes (conformance/reactive-graph/) —
# structural guard (#lzspecedgeindex)
# ---------------------------------------------------------------------------

_REACTIVE_GRAPH_DIR = FIXTURE_DIR / "reactive-graph"

# The op vocabulary documented in docs/conformance.md § Reactive graph disposal
# conformance. A fixture may not invent an op a binding has no way to replay.
_REACTIVE_GRAPH_OPS = {
    "cell",
    "computed",
    "effect",
    "read",
    "set_cell",
    "dispose",
    "fanout",
    "dispose_fanout",
    "churn",
    "begin_scope",
    "end_scope",
    "disarm",
    "dispose_stale_handle",
    # Cell observers (#lzdartobservercow)
    "subscribe",
    "unsubscribe",
    # Signal eagerness (#lzsignaleager). `batch` is a single op carrying its
    # writes rather than a begin/end pair, so a runner needs no nesting state.
    "signal",
    "dispose_signal",
    "batch",
}

# A reactive-graph fixture must cite the contract it conforms to, so a rule can
# not be silently widened by editing prose alone.
_REACTIVE_GRAPH_TAGS = ("#lzspecedgeindex", "#lzdartobservercow", "#lzsignaleager")

# Assertion keys are observable effects only. Deliberately absent: anything
# naming a promotion threshold, a hash strategy, or an index layout — the spec's
# implementation note keeps those out of the contract.
_REACTIVE_GRAPH_EXPECT_KEYS = {
    "value",
    "read",
    "error",
    "readable",
    "dependents_of",
    "dependencies_of",
    "observed_by",
    "observed_count",
    # Observer firing sequence / per-observer invocation counts
    # (#lzdartobservercow). `observed_order` is an exact sequence; `observed_by`
    # stays set-valued.
    "observed_order",
    "observed_counts",
    "cleanup_order",
    "scope_owned_count",
    # Cumulative compute-invocation count per node, from scenario start
    # (#lzsignaleager). The only caller-observable difference between an eager
    # signal and the lazy memo it is built on — values are identical for every
    # read sequence, so a corpus without this cannot tell `signal()` from
    # `memo()`.
    "computes_of",
    "note",
}


def _reactive_graph_fixtures() -> list[str]:
    if not _REACTIVE_GRAPH_DIR.is_dir():
        return []
    return sorted(p.name for p in _REACTIVE_GRAPH_DIR.glob("*.json"))


def _check_reactive_graph_steps(name: str, steps: object, where: str) -> None:
    assert isinstance(steps, list) and steps, f"{name}: {where} needs a non-empty 'steps' list"
    for i, step in enumerate(steps):
        op = step.get("op")
        assert isinstance(op, dict), f"{name}: {where} step {i} missing 'op' object"
        op_type = op.get("type")
        assert op_type in _REACTIVE_GRAPH_OPS, f"{name}: {where} step {i} unknown op {op_type!r}"
        expect = step.get("expect")
        if expect is None:
            continue
        assert isinstance(expect, dict), f"{name}: {where} step {i} 'expect' must be an object"
        unknown = set(expect) - _REACTIVE_GRAPH_EXPECT_KEYS
        assert not unknown, f"{name}: {where} step {i} unknown expect keys {sorted(unknown)}"


@pytest.mark.parametrize("name", _reactive_graph_fixtures())
def test_reactive_graph_fixture_is_well_formed(name: str) -> None:
    """Guard the disposal / teardown-scope fixtures against shape drift.

    These are compute fixtures replayed by each binding, so this asserts only
    the language-agnostic top-level shape and the documented op / assertion
    vocabulary — never any binding's runtime semantics, and never an
    implementation detail the spec leaves free.
    """
    obj = json.loads((_REACTIVE_GRAPH_DIR / name).read_text())
    assert obj["kind"] == "ReactiveGraph", f"{name}: kind must be 'ReactiveGraph'"
    assert obj["model"] == "Context", f"{name}: model must be 'Context'"
    assert isinstance(obj["description"], str) and obj["description"], f"{name}: missing description"
    assert any(tag in obj["description"] for tag in _REACTIVE_GRAPH_TAGS), (
        f"{name}: description must cite one of {list(_REACTIVE_GRAPH_TAGS)}"
    )

    # The variant is DECLARED, not inferred. A runner should switch on `shape`
    # rather than probing for whichever key happens to be present -- the first
    # binding to write a runner special-cased the scenarios fixture by
    # *filename*, which goes stale silently the moment a second one is added.
    shape = obj.get("shape")
    assert shape in {"steps", "scenarios"}, (
        f"{name}: 'shape' must be declared as 'steps' or 'scenarios', got {shape!r}"
    )
    # Cross-check the declaration against reality so `shape` cannot drift from
    # the fixture it describes.
    assert ("scenarios" in obj) == (shape == "scenarios"), (
        f"{name}: shape={shape!r} contradicts the keys present"
    )
    assert ("steps" in obj) == (shape == "steps"), (
        f"{name}: shape={shape!r} contradicts the keys present"
    )

    scenarios = obj.get("scenarios")
    if scenarios is not None:
        assert isinstance(scenarios, list) and len(scenarios) >= 2, (
            f"{name}: 'scenarios' exists to compare runs, so it needs at least two"
        )
        names = []
        for sc in scenarios:
            assert isinstance(sc.get("name"), str) and sc["name"], f"{name}: scenario missing 'name'"
            names.append(sc["name"])
            _check_reactive_graph_steps(name, sc.get("steps"), f"scenario {sc['name']!r}")
        assert len(set(names)) == len(names), f"{name}: duplicate scenario names"
        equal = obj.get("expected", {}).get("observationally_equal")
        assert isinstance(equal, list) and len(equal) >= 2, (
            f"{name}: a multi-scenario fixture must name the scenarios that must agree"
        )
        assert set(equal) <= set(names), f"{name}: observationally_equal names an unknown scenario"
        return

    _check_reactive_graph_steps(name, obj.get("steps"), "fixture")


def test_reactive_graph_fixtures_cover_the_disposal_contract() -> None:
    """Every clause of the disposal contract keeps a fixture.

    Deleting one of these is how a binding quietly stops being held to a rule,
    so the set is pinned rather than merely globbed.
    """
    required = {
        "dispose_detaches_edges_both_directions.json",
        "read_after_dispose_is_an_error.json",
        "recycled_id_inherits_nothing.json",
        "scope_teardown_equals_fold_of_disposals.json",
        "scoping_bounds_teardown_not_visibility.json",
        "disarm_disposes_nothing.json",
        "cross_scope_teardown_hazard.json",
        "churn_returns_to_baseline.json",
    }
    present = set(_reactive_graph_fixtures())
    assert required <= present, f"missing disposal fixtures: {sorted(required - present)}"


def test_reactive_graph_has_no_observer_fixtures() -> None:
    """The observer contract was removed, so its fixtures must stay removed.

    `#lzdartobservercow` ended by *banning* observer APIs on every reactive
    rather than specifying them: six normative clauses across four bindings
    still left the family diverging, and the last clause -- per-write delivery,
    unsuppressed by `batch` -- contradicted the batching model it sat beside. A
    binding now conforms by NOT having the API.

    Asserting the absence, rather than merely deleting the old checks, because
    the failure mode is someone re-adding a fixture for a mechanism the spec
    forbids and a runner dutifully replaying it.
    """
    stragglers = sorted(n for n in _reactive_graph_fixtures() if n.startswith("observer_"))
    assert not stragglers, (
        "observer fixtures must not exist -- reactives have no observer API: "
        f"{stragglers}"
    )


# ---------------------------------------------------------------------------
# Lossless tree CRDT (conformance/lossless-tree/) — compute fixtures + wire
# schema for the op delta (#lzlosstree)
# ---------------------------------------------------------------------------

_LOSSLESS_TREE_DIR = FIXTURE_DIR / "lossless-tree"


def _lossless_tree_fixtures() -> list[str]:
    if not _LOSSLESS_TREE_DIR.is_dir():
        return []
    return sorted(p.name for p in _LOSSLESS_TREE_DIR.glob("*.json"))


@pytest.mark.parametrize("name", _lossless_tree_fixtures())
def test_lossless_tree_fixture_is_well_formed(name: str) -> None:
    """Structural guard for the lossless-tree compute fixtures. Every binding
    (Rust reference + Kotlin/JS ports) replays these `{seed, steps, expect}`
    scenarios and asserts exact rendered text, live-node counts, and convergence;
    here we only pin the language-agnostic top-level shape."""
    obj = json.loads((_LOSSLESS_TREE_DIR / name).read_text())
    assert obj["kind"] == "LosslessTree", f"{name}: kind must be 'LosslessTree'"
    assert obj["model"] == "LosslessTreeCrdt", f"{name}: model must be 'LosslessTreeCrdt'"
    assert isinstance(obj["description"], str) and obj["description"], f"{name}: missing description"
    scenarios = obj.get("scenarios")
    assert isinstance(scenarios, list) and scenarios, f"{name}: needs non-empty 'scenarios'"
    for sc in scenarios:
        assert isinstance(sc.get("name"), str) and sc["name"], f"{name}: scenario missing name"
        seed = sc.get("seed")
        assert isinstance(seed, dict) and "peer" in seed and "tree" in seed, (
            f"{name}: scenario {sc.get('name')!r} needs seed.peer + seed.tree"
        )
        assert "expect" in sc, f"{name}: scenario {sc['name']!r} missing 'expect'"


def _canonical_tree_delta() -> dict:
    """A hand-authored `TreeUpdate` covering every M1 op variant, in the exact
    serde form lazily-rs emits (PascalCase externally-tagged ops/seeds, `frac`
    as a u8 array, dotted `{counter, peer}` ids). The Rust reference validates
    its *own* serde output against this schema in `lazily-rs`; this pins the
    same wire shape from the spec side so a drift on either side fails."""
    op = lambda counter, kind: {"id": {"counter": counter, "peer": 1}, "kind": kind}
    node = lambda counter: {"counter": counter, "peer": 1}
    sort = {"frac": [128], "peer": 1}
    return {
        "ops": [
            op(1, {"CreateNode": {"id": node(1), "parent": {"counter": 0, "peer": 0}, "sort": sort, "seed": {"Element": {"kind": "para"}}}}),
            op(2, {"CreateNode": {"id": node(2), "parent": node(1), "sort": sort, "seed": {"Leaf": {"kind": "Raw", "text": "hello"}}}}),
            op(3, {"LeafEdit": {"node": node(2), "prev": node(2), "ops": [{"id": node(9), "ch": "X", "origin": node(5), "deleted": None}]}}),
            op(4, {"SplitLeaf": {"node": node(2), "new": node(4), "sort": sort, "at_char": 3, "prev": node(3)}}),
            op(5, {"MergeLeaves": {"left": node(2), "right": node(4), "prev_left": node(4), "prev_right": node(4)}}),
            op(6, {"Reorder": {"node": node(2), "sort": {"frac": [64], "peer": 1}}}),
            op(7, {"Tombstone": {"node": node(2)}}),
        ]
    }


def test_canonical_tree_delta_validates_schema() -> None:
    delta = _canonical_tree_delta()
    errors = sorted(
        _validator("lossless-tree-delta").iter_errors(delta), key=lambda e: list(e.path)
    )
    assert not errors, (
        "canonical TreeUpdate does not validate against lossless-tree-delta.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_lossless_tree_delta_rejects_base64_frac() -> None:
    # `frac` is a u8 array on the wire, never base64 (the drift this repo guards
    # against for every CRDT payload).
    bad = _canonical_tree_delta()
    bad["ops"][0]["kind"]["CreateNode"]["sort"] = {"frac": "gA==", "peer": 1}
    assert _validator("lossless-tree-delta").iter_errors(bad), (
        "schema must reject a base64 `frac` sort key"
    )


def test_lossless_tree_delta_rejects_lowercase_leaf_kind() -> None:
    # Leaf kind is PascalCase on the wire; the lowercase fixture-DSL form must not
    # validate as a wire value.
    bad = _canonical_tree_delta()
    bad["ops"][1]["kind"]["CreateNode"]["seed"]["Leaf"]["kind"] = "raw"
    assert _validator("lossless-tree-delta").iter_errors(bad), (
        "schema must reject a lowercase leaf kind on the wire"
    )


def test_lossless_tree_frontier_rejects_per_peer_max_shortcut() -> None:
    # A dotted frontier keeps holes representable; a bare per-peer integer max
    # (the version-vector shortcut the design explicitly rejects) is not a valid
    # frontier shape.
    validator = _validator("lossless-tree")
    frontier_schema = {"$ref": "https://lazily.dev/schemas/lossless-tree.json#/$defs/TreeVersionFrontier"}
    v = jsonschema.Draft202012Validator(frontier_schema, registry=_registry())
    assert v.iter_errors({"dots": {"1": 3}}), (
        "a per-peer integer max must not validate as a dotted DotRange"
    )
    assert not list(v.iter_errors({"dots": {"1": {"contiguous": 2, "sparse": [4]}}})), (
        "a proper dotted frontier with a hole must validate"
    )


# ---------------------------------------------------------------------------
# Command / RPC message plane (conformance/message-passing/) — every frame in
# every fixture validates against its declared schema, and the stale
# "accepted-is-terminal" / "ack" forms are rejected.
# ---------------------------------------------------------------------------

_MSG_PASSING_DIR = FIXTURE_DIR / "message-passing"


def _message_passing_fixtures() -> list[Path]:
    if not _MSG_PASSING_DIR.is_dir():
        return []
    return sorted(_MSG_PASSING_DIR.glob("*.json"))


def _iter_frames(obj: dict) -> list[dict]:
    """Frames live either at top-level `frames` or under each `scenarios[*].frames`."""
    frames: list[dict] = []
    frames.extend(obj.get("frames", []))
    for sc in obj.get("scenarios", []):
        frames.extend(sc.get("frames", []))
    return frames


@pytest.mark.parametrize(
    "path", _message_passing_fixtures(), ids=lambda p: p.name
)
def test_message_passing_fixture_frames_validate(path: Path) -> None:
    fixture = json.loads(path.read_text())
    assert fixture["protocol_version"] == 1
    assert fixture["kind"] == "Command", f"{path.name}: kind must be 'Command'"
    frames = _iter_frames(fixture)
    assert frames, f"{path.name}: fixture defines no frames"
    for i, fr in enumerate(frames):
        schema = fr["schema"]
        assert schema in {"message-passing", "receipts"}, (
            f"{path.name}: frame {i} names unknown schema {schema!r}"
        )
        errors = sorted(
            _validator(schema).iter_errors(fr["wire"]), key=lambda e: list(e.path)
        )
        assert not errors, (
            f"{path.name}: frame {i} does not validate against {schema}.json:\n"
            + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
        )


def test_message_passing_rejects_ack_event_kind() -> None:
    # Command events carry progress kinds only; a transport "ack" is not one and
    # must never be smuggled in as a command event.
    bad = {
        "CommandEvents": {
            "events": [
                {
                    "event_id": "ev-1",
                    "command_id": "cmd-1",
                    "kind": "ack",
                    "generation": 1,
                    "detail": None,
                }
            ]
        }
    }
    assert _validator("message-passing").iter_errors(bad), (
        "message-passing schema must reject a transport 'ack' command-event kind"
    )


def test_message_passing_rejects_applied_projection_without_terminal_flag_field() -> None:
    # A projection entry MUST carry the terminal flag; accepted/queued must not be
    # able to omit it and imply completion.
    bad = {
        "CommandProjection": {
            "generation": 1,
            "commands": [
                {"command_id": "cmd-1", "status": "applied", "generation": 1, "reason": None}
            ],
        }
    }
    assert _validator("message-passing").iter_errors(bad), (
        "CommandProjectionEntry must require the explicit `terminal` flag"
    )


def test_message_passing_submit_requires_payload_hash() -> None:
    incomplete = {
        "CommandSubmit": {
            "command_id": "cmd-1",
            "causation_id": "cmd-1",
            "source": "vscode-plugin",
            "target": "project-controller",
            "namespace": "agent-doc",
            "name": "editor_route",
            "authority_generation": 1,
            "idempotency_key": "k",
            "deadline_ms": 0,
            "policy": {"dedupe": "none", "supersede": False, "cancel_on_preempt": False},
            "payload_type": "agent-doc.editor_route.v1",
            "payload": {"Inline": [1, 2, 3]},
            "required_features": [],
        }
    }
    assert _validator("message-passing").iter_errors(incomplete), (
        "CommandSubmit must require payload_hash"
    )


# ---------------------------------------------------------------------------
# Reliable Sync (conformance/reliable-sync/) — ResyncCoordinator / DurableOutbox
# / SyncDriver / OR-set-LWW liveness compute fixtures + control-frame wire
# schema (#lzsync). These are replayed by each binding (Rust reference +
# Kotlin/JS ports) as the cross-language pins for the reliable-sync protocol.
# ---------------------------------------------------------------------------

_RELIABLE_SYNC_DIR = FIXTURE_DIR / "reliable-sync"

_RELIABLE_SYNC_MODELS = {
    "MultiEpochDelta",
    "ResyncCoordinator",
    "DurableOutbox",
    "OutboxStore",
    "LivenessCells",
    "OutboxCoalesce",
    "PartitionEviction",
}

# Which schema a fixture's top-level `wire` frame (when present) validates against,
# by the externally-tagged envelope key.
_WIRE_ENVELOPE_SCHEMA = {
    "Snapshot": "snapshot",
    "Delta": "delta",
    "CrdtSync": "distributed",
    "ResyncRequest": "reliable-sync",
    "OutboxAck": "reliable-sync",
}


def _reliable_sync_fixtures() -> list[str]:
    if not _RELIABLE_SYNC_DIR.is_dir():
        return []
    return sorted(p.name for p in _RELIABLE_SYNC_DIR.glob("*.json"))


@pytest.mark.parametrize("name", _reliable_sync_fixtures())
def test_reliable_sync_fixture_is_well_formed(name: str) -> None:
    """Structural guard for the reliable-sync compute fixtures. Every binding
    replays these `{scenarios: [{name, expect}]}` models against its
    ResyncCoordinator / DurableOutbox / liveness implementation. This asserts
    only the language-agnostic top-level shape."""
    obj = json.loads((_RELIABLE_SYNC_DIR / name).read_text())
    assert obj["protocol_version"] == 1, f"{name}: protocol_version must be 1"
    assert obj["kind"] == "ReliableSync", f"{name}: kind must be 'ReliableSync'"
    assert obj["model"] in _RELIABLE_SYNC_MODELS, f"{name}: unknown model {obj['model']!r}"
    assert isinstance(obj["description"], str) and obj["description"], f"{name}: missing description"

    scenarios = obj.get("scenarios")
    assert isinstance(scenarios, list) and scenarios, f"{name}: needs non-empty 'scenarios'"
    for sc in scenarios:
        assert isinstance(sc.get("name"), str) and sc["name"], f"{name}: scenario missing name"
        assert "expect" in sc, f"{name}: scenario {sc['name']!r} missing 'expect'"


@pytest.mark.parametrize("name", _reliable_sync_fixtures())
def test_reliable_sync_wire_frame_validates_schema(name: str) -> None:
    """When a reliable-sync fixture carries a top-level `wire` frame, it MUST be
    the externally-tagged IpcMessage envelope and validate against the schema
    for its variant (Snapshot/Delta/CrdtSync/ResyncRequest/OutboxAck)."""
    obj = json.loads((_RELIABLE_SYNC_DIR / name).read_text())
    wire = obj.get("wire")
    if wire is None:
        return
    assert isinstance(wire, dict) and len(wire) == 1, (
        f"{name}: `wire` must be a single-key externally-tagged envelope"
    )
    (tag,) = wire.keys()
    assert tag in _WIRE_ENVELOPE_SCHEMA, f"{name}: unknown wire envelope tag {tag!r}"
    schema = _WIRE_ENVELOPE_SCHEMA[tag]
    errors = sorted(_validator(schema).iter_errors(wire), key=lambda e: list(e.path))
    assert not errors, (
        f"{name} wire {tag} does not validate against {schema}.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_reliable_sync_resync_request_frame_validates() -> None:
    """The ResyncRequest control frame validates against reliable-sync.json."""
    frame = {"ResyncRequest": {"from_epoch": 7}}
    errors = list(_validator("reliable-sync").iter_errors(frame))
    assert not errors, f"ResyncRequest frame should validate: {[e.message for e in errors]}"


def test_reliable_sync_outbox_ack_frame_validates() -> None:
    """The OutboxAck control frame validates against reliable-sync.json."""
    frame = {"OutboxAck": {"through_epoch": 41}}
    errors = list(_validator("reliable-sync").iter_errors(frame))
    assert not errors, f"OutboxAck frame should validate: {[e.message for e in errors]}"


def test_reliable_sync_control_frame_rejects_unknown_field() -> None:
    """additionalProperties:false — a control frame with an unknown field is rejected."""
    bad = {"OutboxAck": {"through_epoch": 41, "bogus": 1}}
    assert list(_validator("reliable-sync").iter_errors(bad)), (
        "OutboxAck with an unknown field must be rejected"
    )
