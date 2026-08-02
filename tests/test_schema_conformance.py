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
    "stdlib-fixture.schema",
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


def test_signaling_negative_fixtures_are_rejected() -> None:
    fixture = json.loads((_SIGNALING_DIR / "frames.json").read_text())
    schema = _load_schema("signaling")
    direction_schemas = {
        "client": schema["oneOf"][0],
        "server": schema["oneOf"][1],
    }
    for reject in fixture["rejects"]:
        wire = reject["wire"]
        if reject["label"] == "welcome_roster_contains_joining_peer":
            assert wire["peer"] in wire["peers"], reject["label"]
            continue
        validator = jsonschema.Draft202012Validator(
            direction_schemas[reject["direction"]],
            registry=_registry(),
        )
        assert list(validator.iter_errors(wire)), (
            f"{reject['label']}: direction-specific signaling schema accepted {wire}"
        )

    session = json.loads((_SIGNALING_DIR / "anti_spoof_session.json").read_text())
    client_validator = jsonschema.Draft202012Validator(
        direction_schemas["client"],
        registry=_registry(),
    )
    for reject in session["rejects"]:
        wire = reject["input"]["recv"]
        assert list(client_validator.iter_errors(wire)), (
            f"{reject['label']}: client signaling schema accepted {wire}"
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
# Frame-codec round-trip fixtures (conformance/codec/) — `#lzmsgpackparity`
# ---------------------------------------------------------------------------
#
# protocol.md § Frame codecs makes `json` and `msgpack` MUST-level and requires
# every frame to round-trip through both for all three `IpcMessage` variants.
# That requirement lived only in prose: the conformance ladder verifies fixture
# CONTENT replay (opened / consumed / asserted / every scenario replayed), and
# content replay never exercises a codec, so a binding could carve out a
# MUST-level codec and stay green everywhere.
#
# These tests guard the fixtures that make the obligation executable. They do
# NOT test a codec — lazily-spec ships no encoder. They pin the invariants a
# binding runner depends on: both flavors exist, they cover the same three
# variants, they carry BYTE-IDENTICAL `wire` values (so one runner shape serves
# both codecs), and every `wire` validates against its schema.

_CODEC_DIR = FIXTURE_DIR / "codec"
_CODEC_FLAVORS = {"json": "frame_roundtrip_json.json", "msgpack": "frame_roundtrip_msgpack.json"}
_VARIANT_SCHEMA = {"Snapshot": "snapshot", "Delta": "delta", "CrdtSync": "distributed"}


def _codec_fixture(codec: str) -> dict:
    return json.loads((_CODEC_DIR / _CODEC_FLAVORS[codec]).read_text())


def _codec_scenarios() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for codec, name in _CODEC_FLAVORS.items():
        if not (_CODEC_DIR / name).is_file():
            continue
        for scenario in _codec_fixture(codec)["scenarios"]:
            out.append((codec, scenario))
    return out


@pytest.mark.parametrize("codec", sorted(_CODEC_FLAVORS))
def test_codec_fixture_is_well_formed(codec: str) -> None:
    obj = _codec_fixture(codec)
    assert obj["protocol_version"] == 1
    assert obj["kind"] == "FrameCodecRoundTrip"
    assert obj["codec"] == codec, "the `codec` field must match the file it lives in"

    fixture_assertions = obj["assertions"]
    assert fixture_assertions["codec"] == codec
    assert fixture_assertions["required_of_binding"] == "MUST"
    # Both MUST-level codecs are self-describing; only json is byte-canonical.
    # Conflating the two senses of "canonical" is the confusion protocol.md
    # § Frame codecs exists to prevent, so the fixtures pin them separately.
    assert fixture_assertions["self_describing"] is True
    assert fixture_assertions["byte_canonical"] is (codec == "json")

    scenarios = obj["scenarios"]
    assert fixture_assertions["scenario_count"] == len(scenarios)
    # One scenario per IpcMessage variant, and ids are unique — the scenario
    # ledger (`#lzscenariocoverage`) resolves `id` first, so a duplicate id
    # would let one replayed scenario mark another as covered.
    assert [s["variant"] for s in scenarios] == list(_VARIANT_SCHEMA)
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == len(ids)
    for scenario in scenarios:
        assert scenario["id"] == scenario["name"]
        assert codec in scenario["id"], (
            f"scenario id {scenario['id']!r} must name its codec: the two flavors "
            "share a corpus namespace and a binding excuses them independently"
        )


def test_codec_flavors_pin_identical_wire_values() -> None:
    """The json and msgpack fixtures differ only in codec, never in payload.

    A runner proves a codec by sending the SAME frame through a different
    encoder. If the two fixtures drifted apart, a msgpack failure could be a
    payload difference rather than a codec difference, and the parity claim
    the pair exists to make would be untestable.
    """
    json_scenarios = _codec_fixture("json")["scenarios"]
    msgpack_scenarios = _codec_fixture("msgpack")["scenarios"]
    assert len(json_scenarios) == len(msgpack_scenarios)
    for js, ms in zip(json_scenarios, msgpack_scenarios):
        assert js["variant"] == ms["variant"]
        assert js["wire"] == ms["wire"], (
            f"{js['variant']} wire drifted between the json and msgpack fixtures"
        )


@pytest.mark.parametrize(
    "codec,scenario", _codec_scenarios(), ids=lambda v: v if isinstance(v, str) else v["id"]
)
def test_codec_scenario_wire_validates_schema(codec: str, scenario: dict) -> None:
    schema = _VARIANT_SCHEMA[scenario["variant"]]
    errors = sorted(
        _validator(schema).iter_errors(scenario["wire"]), key=lambda e: list(e.path)
    )
    assert not errors, (
        f"{codec} scenario {scenario['id']!r} wire does not validate against {schema}.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


@pytest.mark.parametrize(
    "codec,scenario", _codec_scenarios(), ids=lambda v: v if isinstance(v, str) else v["id"]
)
def test_codec_scenario_expect_block_is_discriminating(codec: str, scenario: dict) -> None:
    """Every scenario asserts the round trip itself plus real decoded values.

    `round_trip_equals_source` alone is satisfiable by a runner that never
    re-encodes — it is the runner's own boolean. The value keys are what make
    the block falsifiable: they are read off the SECOND decode, so a codec that
    drops or reshapes a field fails them.
    """
    expect = scenario["expect"]
    assert expect["round_trip_equals_source"] is True
    value_keys = [k for k in expect if k != "round_trip_equals_source"]
    assert len(value_keys) >= 4, (
        f"{scenario['id']} pins only {value_keys}; a round-trip flag plus one or two "
        "scalars cannot distinguish a lossy codec from a correct one"
    )
    if codec == "msgpack":
        # The named-field rule (protocol.md § Frame codecs) is the one msgpack
        # property a value round trip CANNOT catch: a positional encoder
        # round-trips correctly and is still non-conforming.
        assert expect["encoded_envelope_key"] == scenario["variant"]
        names = expect["encoded_body_field_names"]
        assert names == sorted(names), (
            "msgpack map key order is encoder-defined; the fixture must pin a SORTED "
            "field-name list so a runner compares sets, not encoder order"
        )


def test_coverage_matrix_carries_a_row_per_codec_flavor() -> None:
    """The feature matrix must show codec parity, not just protocol features.

    This is the surface the carve-out was invisible on: seven bindings declared
    `msgpack` as an interop-peer carve_out and `coverage.json` had no codec row
    at all, so a MUST-level codec implemented by two of nine read as full
    parity.
    """
    rows = json.loads((ROOT / "coverage.json").read_text())["rows"]
    features = [r["feature"] for r in rows]
    for codec in ("json", "msgpack", "postcard"):
        matching = [f for f in features if f.startswith("Frame codec —") and f"`{codec}`" in f]
        assert len(matching) == 1, f"expected exactly one `{codec}` frame-codec row, got {matching}"


# ---------------------------------------------------------------------------
# NodeId exact-representation bound (conformance/codec/) — `#lzspecdecoderbound`
# ---------------------------------------------------------------------------
#
# protocol.md § NodeId / PeerId stated the 2^53 bound as a PRODUCER obligation
# and said nothing about the receiving half, which is where the bindings
# diverged. The clause is now normative — a decoder that cannot represent a
# received identifier exactly MUST reject the frame rather than round it — and
# `nodeid_exact_range.json` replays it.
#
# These tests do NOT test a decoder; lazily-spec ships none. They guard the
# properties a binding runner depends on, and one of them is unusual enough to
# state plainly: the fixture must not carry any identifier as a JSON *number*.
# This file is JSON, so a runner that loaded a bare 9007199254740993 through a
# double-backed parser would round the fixture's own expected value before the
# test ran, and would then pass against a decoder that rounds. The fixture
# carries wire frames as text/hex and expectations as decimal strings; that is
# the invariant `test_nodeid_fixture_carries_no_unsafe_json_number` enforces.

_NODEID_FIXTURE = FIXTURE_DIR / "codec" / "nodeid_exact_range.json"
_MAX_SAFE = 2**53 - 1


def _nodeid_fixture() -> dict:
    return json.loads(_NODEID_FIXTURE.read_text())


def _nodeid_scenarios() -> list[dict]:
    if not _NODEID_FIXTURE.is_file():
        return []
    return _nodeid_fixture()["scenarios"]


def _unpack_msgpack(data: bytes, pos: int = 0):
    """Minimal MessagePack reader — returns (value, next_pos).

    Written independently of `scripts/gen_nodeid_exact_range_fixture.py`'s
    encoder on purpose: a fixture whose bytes are only ever checked by the
    encoder that produced them is checked by nothing.
    """
    tag = data[pos]
    pos += 1
    if tag == 0xC0:  # nil — the explicit-null form (`#lzkeynullstrict`)
        return None, pos
    if tag < 0x80:
        return tag, pos
    if 0x80 <= tag <= 0x8F or tag == 0xDE:
        if tag == 0xDE:
            count = int.from_bytes(data[pos : pos + 2], "big")
            pos += 2
        else:
            count = tag & 0x0F
        out = {}
        for _ in range(count):
            key, pos = _unpack_msgpack(data, pos)
            value, pos = _unpack_msgpack(data, pos)
            out[key] = value
        return out, pos
    if 0x90 <= tag <= 0x9F:
        out_list = []
        for _ in range(tag & 0x0F):
            item, pos = _unpack_msgpack(data, pos)
            out_list.append(item)
        return out_list, pos
    if 0xA0 <= tag <= 0xBF:
        length = tag & 0x1F
        return data[pos : pos + length].decode("utf-8"), pos + length
    if tag == 0xD9:
        length = data[pos]
        pos += 1
        return data[pos : pos + length].decode("utf-8"), pos + length
    if tag in (0xCC, 0xCD, 0xCE, 0xCF):
        width = {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}[tag]
        return int.from_bytes(data[pos : pos + width], "big"), pos + width
    raise AssertionError(f"fixture uses an unexpected msgpack tag 0x{tag:02x} at {pos - 1}")


def test_nodeid_fixture_is_well_formed() -> None:
    obj = _nodeid_fixture()
    assert obj["protocol_version"] == 1
    assert obj["kind"] == "NodeIdExactRange"

    fixture_assertions = obj["assertions"]
    assert fixture_assertions["required_of_binding"] == "MUST"
    assert fixture_assertions["codecs"] == ["json", "msgpack"]

    scenarios = obj["scenarios"]
    assert fixture_assertions["scenario_count"] == len(scenarios)
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == len(ids), "duplicate ids let one replayed scenario cover another"
    for scenario in scenarios:
        assert scenario["id"] == scenario["name"]
        assert scenario["codec"] in ("json", "msgpack")
        assert scenario["codec"] in scenario["id"], (
            f"scenario id {scenario['id']!r} must name its codec: a binding excuses the "
            "two codecs independently, so the ledger has to tell them apart"
        )


def test_nodeid_fixture_carries_an_anti_vacuity_control_per_codec() -> None:
    """Every codec needs at least one `exact` scenario.

    `exact_or_reject` is satisfiable by a runner that reports "rejected" without
    decoding anything — the same class of vacuous green the conformance ladder
    exists to remove. The `exact` scenarios (2^53 - 1, which EVERY binding
    represents) are what force the runner to prove it decodes at all.
    """
    for codec in ("json", "msgpack"):
        outcomes = [
            s["expect"]["outcome"] for s in _nodeid_scenarios() if s["codec"] == codec
        ]
        assert "exact" in outcomes, f"{codec} has no `exact` control scenario"
        assert "exact_or_reject" in outcomes, f"{codec} pins no over-range identifier"


def test_nodeid_fixture_carries_no_unsafe_json_number() -> None:
    """No identifier above 2^53 - 1 may appear anywhere as a JSON number.

    The fixture is JSON. A bare 9007199254740993 in it is rounded by any
    double-backed JSON parser *while the fixture is being loaded*, so the test
    would compare a rounded expectation against a rounded decode and pass. Wire
    frames are therefore text (json) or hex (msgpack) and expectations are
    decimal strings.
    """

    def walk(node, path: str) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            assert node <= _MAX_SAFE, (
                f"{path} carries {node} as a JSON number; a double-backed parser rounds "
                "it while loading the fixture. Use a decimal string."
            )
        elif isinstance(node, float):
            raise AssertionError(f"{path} is a float; identifiers are exact integers")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(_nodeid_fixture(), "fixture")


@pytest.mark.parametrize("scenario", _nodeid_scenarios(), ids=lambda s: s["id"])
def test_nodeid_scenario_wire_matches_its_expectation(scenario: dict) -> None:
    """The wire frame really carries the identifier the `expect` block names.

    Both codecs are decoded here — the json text with Python's arbitrary-precision
    parser, the msgpack bytes with the independent reader above — so a generator
    bug that emitted a rounded or truncated identifier is caught in this repo
    rather than nine repos downstream.
    """
    expect = scenario["expect"]
    expected = int(expect["node_id_decimal"])

    if scenario["codec"] == "json":
        frame = json.loads(scenario["wire_json"])
    else:
        raw = bytes.fromhex(scenario["wire_msgpack_hex"])
        frame, end = _unpack_msgpack(raw)
        assert end == len(raw), "trailing bytes after the msgpack frame"
        if expected > _MAX_SAFE:
            # The identifier must ride the `uint 64` family, not a signed or
            # float encoding — a decoder that reads it through the wrong path is
            # otherwise invisible.
            assert b"\xcf" + expected.to_bytes(8, "big") in raw, (
                f"{scenario['id']} does not encode {expected} as a msgpack uint 64"
            )

    body = frame["Snapshot"]
    assert body["epoch"] == expect["epoch"]
    assert len(body["nodes"]) == expect["node_count"]
    node = body["nodes"][0]
    assert node["node"] == expected
    assert node["type_tag"] == expect["type_tag"]
    assert node["state"]["Payload"] == expect["payload"]
    assert body["roots"] == [int(expect["root_id_decimal"])]


@pytest.mark.parametrize("scenario", _nodeid_scenarios(), ids=lambda s: s["id"])
def test_nodeid_scenario_wire_validates_schema(scenario: dict) -> None:
    """The over-range frames are schema-VALID; refusing them is a decoder decision.

    This is the point defs.json got wrong before the audit: it capped `PeerId`
    at 2^53 - 1, which made a legal u64 frame schema-invalid and pushed a
    runtime-capability question into wire validity.
    """
    if scenario["codec"] == "json":
        frame = json.loads(scenario["wire_json"])
    else:
        frame, _ = _unpack_msgpack(bytes.fromhex(scenario["wire_msgpack_hex"]))
    errors = sorted(_validator("snapshot").iter_errors(frame), key=lambda e: list(e.path))
    assert not errors, (
        f"{scenario['id']} wire does not validate against snapshot.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_nodeid_scenario_expect_block_is_discriminating() -> None:
    """An outcome plus one scalar cannot tell a rounding decoder from a correct one."""
    for scenario in _nodeid_scenarios():
        value_keys = [k for k in scenario["expect"] if k != "outcome"]
        assert len(value_keys) >= 4, (
            f"{scenario['id']} pins only {value_keys}; the block must also force the "
            "runner to prove it decoded the surrounding frame"
        )


# ---------------------------------------------------------------------------
# NodeKey null-leniency on decode (conformance/codec/) — `#lzkeynullstrict`
# ---------------------------------------------------------------------------
#
# protocol.md § NodeKey settled the OMITTED form and left an explicit
# `key: null` undefined. Three bindings diverged there — two refused it and one
# decoded it into a real key named "null" — so the clause now says
# omit-when-absent binds the ENCODER and a decoder must read both forms as
# absent.
#
# These tests guard the fixture, not a decoder. The property worth stating
# plainly: the null scenarios must be schema-VALID. Making them invalid would
# push a decoder-leniency question into wire validity and contradict the clause,
# which is exactly the mistake defs.json made for PeerId's upper bound.

_NODEKEY_FIXTURE = FIXTURE_DIR / "codec" / "nodekey_null_leniency.json"
_NODEKEY_VARIANT_SCHEMA = {"Snapshot": "snapshot", "Delta": "delta"}


def _nodekey_fixture() -> dict:
    return json.loads(_NODEKEY_FIXTURE.read_text())


def _nodekey_scenarios() -> list[dict]:
    if not _NODEKEY_FIXTURE.is_file():
        return []
    return _nodekey_fixture()["scenarios"]


def _nodekey_wire(scenario: dict) -> dict:
    if scenario["codec"] == "json":
        return json.loads(scenario["wire_json"])
    frame, end = _unpack_msgpack(bytes.fromhex(scenario["wire_msgpack_hex"]))
    assert end == len(bytes.fromhex(scenario["wire_msgpack_hex"])), "trailing bytes"
    return frame


def test_nodekey_fixture_is_well_formed() -> None:
    obj = _nodekey_fixture()
    assert obj["protocol_version"] == 1
    assert obj["kind"] == "NodeKeyNullLeniency"

    fixture_assertions = obj["assertions"]
    assert fixture_assertions["required_of_binding"] == "MUST"
    assert fixture_assertions["codecs"] == ["json", "msgpack"]
    assert fixture_assertions["fields"] == ["snapshot", "node_add"]
    assert fixture_assertions["key_forms"] == ["omitted", "null", "present"]

    scenarios = obj["scenarios"]
    assert fixture_assertions["scenario_count"] == len(scenarios)
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == len(ids), "duplicate ids let one replayed scenario cover another"
    for scenario in scenarios:
        assert scenario["id"] == scenario["name"]
        assert scenario["codec"] in scenario["id"]
        assert scenario["key_form"] in scenario["id"]


def test_nodekey_fixture_covers_every_field_form_and_codec() -> None:
    """The cross product, not a sample.

    Every binding that got `NodeSnapshot` wrong got `NodeAdd` wrong the same way,
    in the same file — and in lazily-kt the two were separate expressions, so a
    fix applied to one would have left the other inventing a key named "null".
    Sampling one field would have missed that.
    """
    seen = {(s["field"], s["key_form"], s["codec"]) for s in _nodekey_scenarios()}
    expected = {
        (field, form, codec)
        for field in ("snapshot", "node_add")
        for form in ("omitted", "null", "present")
        for codec in ("json", "msgpack")
    }
    assert seen == expected, f"missing: {sorted(expected - seen)}"


@pytest.mark.parametrize("scenario", _nodekey_scenarios(), ids=lambda s: s["id"])
def test_nodekey_scenario_wire_carries_the_form_it_claims(scenario: dict) -> None:
    """The bytes really carry an absent field / an explicit null / a real key.

    A generator bug that emitted the omitted form for a `null` scenario would
    make the whole fixture pass against a decoder that refuses null, which is
    the defect it exists to catch — so the wire form is verified here rather
    than trusted.
    """
    frame = _nodekey_wire(scenario)
    if scenario["field"] == "snapshot":
        node = frame["Snapshot"]["nodes"][0]
    else:
        node = frame["Delta"]["ops"][0]["NodeAdd"]

    form = scenario["key_form"]
    if form == "omitted":
        assert "key" not in node, "an omitted scenario must not carry the field at all"
    elif form == "null":
        assert "key" in node and node["key"] is None, "a null scenario carries an explicit null"
        if scenario["codec"] == "msgpack":
            # 0xc0 is msgpack `nil`. Pinned because an encoder that dropped the
            # entry instead would produce a valid-looking `omitted` scenario.
            assert b"\xc0" in bytes.fromhex(scenario["wire_msgpack_hex"])
    else:
        assert node["key"] == scenario["expect"]["decoded_key"]

    assert node["node"] == scenario["expect"]["node"]
    assert node["type_tag"] == scenario["expect"]["type_tag"]
    assert node["state"]["Payload"] == scenario["expect"]["payload"]


@pytest.mark.parametrize("scenario", _nodekey_scenarios(), ids=lambda s: s["id"])
def test_nodekey_scenario_wire_validates_schema(scenario: dict) -> None:
    """Including the null form — refusing it is a decoder decision, not a validity one.

    snapshot.json and delta.json carried a bare `NodeKey` $ref for this field
    until the audit, which made a frame the clause now REQUIRES decoders to
    accept schema-invalid. Same mistake as PeerId's 2^53-1 maximum, one field
    over.
    """
    schema = _NODEKEY_VARIANT_SCHEMA[scenario["variant"]]
    frame = _nodekey_wire(scenario)
    errors = sorted(_validator(schema).iter_errors(frame), key=lambda e: list(e.path))
    assert not errors, (
        f"{scenario['id']} wire does not validate against {schema}.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


def test_nodekey_expect_pins_the_reencode_obligation() -> None:
    """Reading the null form as absent is only half the rule.

    A binding that round-trips `key: null` straight back out has a correct
    decoded value and a non-conforming encoder. `reencoded_key_field_present` is
    the only key in the block a decode assertion cannot reach, so its
    relationship to `key_form` is pinned here rather than left to each runner.
    """
    for scenario in _nodekey_scenarios():
        expect = scenario["expect"]
        present = scenario["key_form"] == "present"
        assert expect["reencoded_key_field_present"] is present, scenario["id"]
        assert (expect["decoded_key"] is not None) is present, scenario["id"]
        value_keys = [k for k in expect if k != "reencoded_key_field_present"]
        assert len(value_keys) >= 4, (
            f"{scenario['id']} pins only {value_keys}; the block must also force the "
            "runner to prove it decoded the surrounding frame"
        )


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
#
# `CellMap` / `SlotMap` / `CellTree` are the DEPRECATED spellings of `SourceMap` /
# `ComputedMap` / `SourceTree`, kept accepted here because the `model` field is wire data that
# nine independent runners read — at least one of them dispatches on it. Rejecting the old
# spelling would break every binding that has not migrated yet, in the same commit that renames
# the fixtures. They are accepted, not emitted: no fixture in this repo carries them any more.
_KEYED_MODELS = {"SourceMap", "SourceTree", "CellMap", "CellTree"}
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
    # MergeCell fed from a reactive (#lzmergefeed). `merge_cell` constructs a
    # cell whose write folds under a declared `policy`; `merge` folds one op
    # into it. A `Source` never acquires a dependency edge, so "feed this merge
    # cell from that reactive" is an ordinary `effect` that reads and merges —
    # no new node kind, and no new op for the feeding itself.
    "merge_cell",
    "merge",
    # A failed compute is never cached. `fail_next` arms the next `count`
    # computes of an existing node to raise, so a fixture can assert on
    # `computes_of` that the node re-runs per read instead of replaying a
    # stored error. It creates nothing and changes no dependency set.
    "fail_next",
}

# A reactive-graph fixture must cite the contract it conforms to, so a rule can
# not be silently widened by editing prose alone.
_REACTIVE_GRAPH_TAGS = (
    "#lzspecedgeindex",
    "#lzdartobservercow",
    "#lzsignaleager",
    # MergeCell fed from a reactive via an effect, and the drain bound that
    # makes a divergent feedback loop testable instead of hanging the runner.
    "#lzmergefeed",
    "#lzfeedbackdrain",
    # A failed compute is never cached: the next read re-runs the body rather
    # than replaying the stored error (`Error -> Computing` on the async plane).
    "#lzasyncerrfixture",
)

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
    # `Computed` and the lazy `Computed` it is built on — values are identical for every
    # read sequence, so a corpus without this cannot tell `computed().eager()`
    # from `computed()`.
    "computes_of",
    # Cumulative merge-fold count per merge cell, from scenario start
    # (#lzmergefeed). Delivery through a dependency edge is per settled cone,
    # not per write, and under an idempotent policy the VALUE converges either
    # way — only the count separates a conforming binding from one that merges
    # per write. Hence a count assertion, and hence the fixtures use a
    # non-idempotent policy where the two also diverge in value.
    "merges_of",
    # Effect-drain exhaustion (#lzfeedbackdrain). A scheduler-closed feedback
    # loop is a flat unbounded drain, so a runner replaying a divergent loop
    # hangs unless the binding bounds the drain and reports being cut short.
    # Exhaustion is NOT convergence — asserting it is asserting that the
    # binding failed safely, not that the loop terminated.
    "drain_exhausted",
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


# ---------------------------------------------------------------------------
# Blob-backend discriminator strictness (`#lzblobbackendstrict`)
# ---------------------------------------------------------------------------
#
# These tests guard the FIXTURE, not a decoder. The property worth stating
# plainly is the inverse of the one nodekey_null_leniency asserts: the `reject`
# scenarios must be schema-INVALID, because `schemas/defs.json` closes `backend`
# to an enum and that enum binds a conforming ENCODER. A fixture whose reject
# case validated would be asserting that a conforming producer may emit the
# token — which is the opposite of the clause. The `accept` scenarios must
# validate, for the same reason nodekey's null scenarios must: pushing a decoder
# question into wire validity is how defs.json got PeerId's upper bound wrong.

_BACKEND_FIXTURE = FIXTURE_DIR / "codec" / "blob_backend_discriminator.json"
_KNOWN_BACKENDS = ("shm", "arrow", "in_process")


def _backend_fixture() -> dict:
    return json.loads(_BACKEND_FIXTURE.read_text())


def _backend_scenarios() -> list[dict]:
    if not _BACKEND_FIXTURE.is_file():
        return []
    return _backend_fixture()["scenarios"]


def _backend_wire(scenario: dict) -> dict:
    if scenario["codec"] == "json":
        return json.loads(scenario["wire_json"])
    raw = bytes.fromhex(scenario["wire_msgpack_hex"])
    frame, end = _unpack_msgpack(raw)
    assert end == len(raw), "trailing bytes"
    return frame


def _backend_descriptor(scenario: dict) -> dict:
    ops = _backend_wire(scenario)["Delta"]["ops"]
    assert len(ops) == 1, "each scenario carries exactly one op, so the arm under test is unambiguous"
    return ops[0]["SlotValue"]["payload"]["SharedBlob"]


def test_backend_fixture_is_well_formed() -> None:
    obj = _backend_fixture()
    assert obj["protocol_version"] == 1
    assert obj["kind"] == "BlobBackendDiscriminator"

    fixture_assertions = obj["assertions"]
    assert fixture_assertions["required_of_binding"] == "MUST"
    assert fixture_assertions["codecs"] == ["json", "msgpack"]
    assert fixture_assertions["backends"] == list(_KNOWN_BACKENDS)
    assert fixture_assertions["outcomes"] == ["accept", "reject"]

    scenarios = obj["scenarios"]
    assert scenarios, "an empty scenario list satisfies every per-scenario test below"
    assert fixture_assertions["scenario_count"] == len(scenarios)
    ids = [s["id"] for s in scenarios]
    assert len(set(ids)) == len(ids), "duplicate ids let one replayed scenario cover another"
    for scenario in scenarios:
        assert scenario["id"] == scenario["name"]
        assert scenario["codec"] in scenario["id"]
        assert scenario["outcome"] in ("accept", "reject")


def test_backend_fixture_covers_every_form_and_codec() -> None:
    """The cross product, not a sample.

    Both codecs matter on both sides of the clause: an absent map entry and a
    present short string are different bytes in msgpack than in json, and a
    binding with two codec paths can (and lazily-cpp did, for NodeKey) get one
    right and the other wrong in the same file.
    """
    seen = {(s["backend_form"], s["codec"]) for s in _backend_scenarios()}
    expected = {
        (form, codec)
        for form in ("omitted", "shm", "arrow", "rdma")
        for codec in ("json", "msgpack")
    }
    assert seen == expected, f"missing: {sorted(expected - seen)}"


def test_backend_fixture_has_both_outcomes() -> None:
    """Anti-vacuity at the fixture level.

    A fixture carrying only `reject` scenarios is satisfied by a decoder that
    refuses every frame; one carrying only `accept` scenarios is satisfied by a
    decoder that refuses nothing. The clause is the pair.
    """
    outcomes = [s["outcome"] for s in _backend_scenarios()]
    assert outcomes.count("accept") >= 6, "need omitted + shm + arrow in both codecs"
    assert outcomes.count("reject") >= 2, "need the unknown token in both codecs"


@pytest.mark.parametrize("scenario", _backend_scenarios(), ids=lambda s: s["id"])
def test_backend_scenario_wire_carries_the_form_it_claims(scenario: dict) -> None:
    """The bytes really carry an absent field / the named token.

    A generator bug that emitted the omitted form for the `rdma` scenario would
    make the whole fixture pass against a decoder that normalizes silently —
    the exact defect it exists to catch — so the wire form is verified rather
    than trusted. Both codecs are decoded from their raw form here; the json and
    msgpack halves are checked for equality in the parity test below.
    """
    descriptor = _backend_descriptor(scenario)
    form = scenario["backend_form"]
    if form == "omitted":
        assert "backend" not in descriptor, "the omitted scenario must omit the key entirely"
    else:
        assert descriptor.get("backend") == form


def test_backend_json_and_msgpack_halves_are_the_same_frame() -> None:
    """The two codecs must differ only in encoding, never in payload.

    A runner proves a codec by sending the SAME frame through a different
    encoder. If the halves diverged, a red would be a payload difference
    wearing a codec difference's clothes.
    """
    by_form: dict[str, dict[str, dict]] = {}
    for scenario in _backend_scenarios():
        by_form.setdefault(scenario["backend_form"], {})[scenario["codec"]] = _backend_wire(scenario)
    assert by_form, "no scenarios to compare"
    for form, halves in sorted(by_form.items()):
        assert set(halves) == {"json", "msgpack"}, f"{form} is missing a codec half"
        assert halves["json"] == halves["msgpack"], f"{form}: json and msgpack frames differ"


@pytest.mark.parametrize(
    "scenario",
    [s for s in _backend_scenarios() if s["outcome"] == "accept"],
    ids=lambda s: s["id"],
)
def test_backend_accept_scenarios_are_schema_valid(scenario: dict) -> None:
    """An accepted frame is a frame a conforming producer may emit."""
    errors = sorted(_validator("delta").iter_errors(_backend_wire(scenario)), key=lambda e: list(e.path))
    assert not errors, (
        f"{scenario['id']} must validate against delta.json:\n"
        + "\n".join(f"  - {list(e.path)}: {e.message}" for e in errors)
    )


@pytest.mark.parametrize(
    "scenario",
    [s for s in _backend_scenarios() if s["outcome"] == "reject"],
    ids=lambda s: s["id"],
)
def test_backend_reject_scenarios_are_schema_invalid(scenario: dict) -> None:
    """The enum binds the ENCODER, so the reject frames must NOT validate.

    This is the assertion that keeps the clause coherent. If someone widens
    `backend` to a bare string to make this fixture "validate cleanly", the
    schema stops saying that a conforming producer may only emit a known
    backend — and the reject scenarios stop meaning anything. This test fails
    in that world, which is the point.
    """
    errors = list(_validator("delta").iter_errors(_backend_wire(scenario)))
    assert errors, (
        f"{scenario['id']} carries backend={scenario['backend_form']!r}, which is outside "
        "the defs.json enum and MUST NOT validate — the enum binds a conforming encoder"
    )


def test_backend_reject_token_is_absent_from_the_known_enum() -> None:
    """The probe must name a backend nothing ships.

    A mutation aimed at a value the corpus never carries is one of the three
    ways a check reports a false green; the fixture-side twin is a reject
    scenario aimed at a value that is actually legal. If `rdma` is ever added
    to the enum, this fails and the fixture must pick a new token.
    """
    for scenario in _backend_scenarios():
        if scenario["outcome"] == "reject":
            assert scenario["expect"]["error_names_token"] not in _KNOWN_BACKENDS
            assert scenario["backend_form"] == scenario["expect"]["error_names_token"]


def test_backend_accept_scenarios_pin_the_encoder_half() -> None:
    """`shm` (explicit or omitted) must re-encode WITHOUT the field; `arrow` with it.

    Without this split a binding satisfies the clause by echoing back whatever
    it received, and a pre-`backend` descriptor stops round-tripping
    byte-identically — the same encoder obligation `#lzkeynullstrict` carries.
    """
    checked = 0
    for scenario in _backend_scenarios():
        if scenario["outcome"] != "accept":
            continue
        expect = scenario["expect"]
        assert expect["reencoded_backend_field_present"] is (expect["decoded_backend"] != "shm")
        checked += 1
    assert checked == 6, f"expected 6 accept scenarios, checked {checked}"
