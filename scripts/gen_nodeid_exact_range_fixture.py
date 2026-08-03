#!/usr/bin/env python3
"""Regenerate conformance/codec/nodeid_exact_range.json (`#lzspecdecoderbound`).

The fixture pins the decoder half of the `NodeId`/`PeerId` bound: a decoder that
cannot represent a received identifier exactly MUST reject the frame rather than
round it (protocol.md § NodeId / PeerId).

Why a generator rather than a hand-written file: the msgpack half is a byte
string, and the whole point of the fixture is that the identifier survives
without rounding. Hand-pasted hex cannot be reviewed for that; a generator that
emits the `uint 64` family (0xcf) explicitly can. The json half is emitted as
raw TEXT for the same reason a decimal string carries the expectation — see
`assertions.wire_encoding` in the emitted file.

Run: python3 scripts/gen_nodeid_exact_range_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "conformance" / "codec" / "nodeid_exact_range.json"

MAX_SAFE = 2**53 - 1  # 9007199254740991
ABOVE_SAFE = 2**53 + 1  # 9007199254740993 — the smallest odd integer a double cannot hold
U64_MAX = 2**64 - 1  # 18446744073709551615
FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3

TYPE_TAG = "i32"
PAYLOAD = [1, 2, 3]
EPOCH = 1


def _fnv1a64_hex(data: bytes) -> str:
    digest = FNV1A64_OFFSET
    for byte in data:
        digest ^= byte
        digest = (digest * FNV1A64_PRIME) & U64_MAX
    return f"{digest:016x}"


# --- minimal MessagePack encoder ------------------------------------------
#
# Named-field maps keyed by the json field names, externally-tagged envelope —
# protocol.md § Frame codecs. Deliberately minimal and explicit: identifiers go
# out through `_uint`, which selects the narrowest family that holds the value,
# so the `u64_max` scenario provably rides a `uint 64` (0xcf) and not a float.


def _uint(n: int) -> bytes:
    if n < 0:
        raise ValueError(f"identifiers are unsigned: {n}")
    if n < 0x80:
        return bytes([n])
    if n <= 0xFF:
        return b"\xcc" + n.to_bytes(1, "big")
    if n <= 0xFFFF:
        return b"\xcd" + n.to_bytes(2, "big")
    if n <= 0xFFFFFFFF:
        return b"\xce" + n.to_bytes(4, "big")
    if n <= U64_MAX:
        return b"\xcf" + n.to_bytes(8, "big")
    raise ValueError(f"not a u64: {n}")


def _str(s: str) -> bytes:
    raw = s.encode("utf-8")
    if len(raw) < 32:
        return bytes([0xA0 | len(raw)]) + raw
    if len(raw) <= 0xFF:
        return b"\xd9" + bytes([len(raw)]) + raw
    raise ValueError("fixture strings stay short")


def _array(items: list[bytes]) -> bytes:
    if len(items) < 16:
        return bytes([0x90 | len(items)]) + b"".join(items)
    raise ValueError("fixture arrays stay short")


def _map(pairs: list[tuple[str, bytes]]) -> bytes:
    if len(pairs) < 16:
        return bytes([0x80 | len(pairs)]) + b"".join(_str(k) + v for k, v in pairs)
    raise ValueError("fixture maps stay short")


def _snapshot_msgpack(node_id: int) -> bytes:
    node = _map(
        [
            ("node", _uint(node_id)),
            ("type_tag", _str(TYPE_TAG)),
            ("state", _map([("Payload", _array([_uint(b) for b in PAYLOAD]))])),
        ]
    )
    body = _map(
        [
            ("epoch", _uint(EPOCH)),
            ("nodes", _array([node])),
            ("edges", _array([])),
            ("roots", _array([_uint(node_id)])),
        ]
    )
    return _map([("Snapshot", body)])


def _snapshot_json(node_id: int) -> str:
    # Emitted by hand rather than via json.dumps so the identifier is written as
    # an exact decimal literal from a Python int, which is arbitrary-precision.
    payload = ", ".join(str(b) for b in PAYLOAD)
    return (
        '{"Snapshot": {'
        f'"epoch": {EPOCH}, '
        '"nodes": [{'
        f'"node": {node_id}, '
        f'"type_tag": "{TYPE_TAG}", '
        f'"state": {{"Payload": [{payload}]}}'
        "}], "
        '"edges": [], '
        f'"roots": [{node_id}]'
        "}}"
    )


CASES = [
    (
        "max_safe",
        MAX_SAFE,
        "exact",
        "2^53 - 1 — the largest identifier an IEEE-754 double holds exactly. Every "
        "binding, including the two whose identity type IS a double, MUST decode this "
        "to exactly 9007199254740991. This is the anti-vacuity control: a runner that "
        "reports 'rejected' for every frame satisfies the two `exact_or_reject` "
        "scenarios trivially and fails here.",
    ),
    (
        "above_safe",
        ABOVE_SAFE,
        "exact_or_reject",
        "2^53 + 1 — the smallest odd integer a double cannot represent; it rounds to "
        "9007199254740992. A binding with a u64 or i64 identity type decodes it "
        "exactly; a double-backed one MUST refuse. The failing behaviour this pins is "
        "the third option: returning 9007199254740992, which addresses a different "
        "node and is undetectable downstream.",
    ),
    (
        "u64_max",
        U64_MAX,
        "exact_or_reject",
        "The top of the declared u64 wire range. Only lazily-rs, lazily-zig, and "
        "lazily-cs represent it; the i64-backed and double-backed bindings MUST refuse. "
        "It also pins the msgpack encoding family — the identifier rides a `uint 64` "
        "(0xcf), so a decoder that reads it through a signed or float path is visible.",
    ),
]

DESCRIPTION = (
    "Decoder obligation for the NodeId/PeerId exact-representation bound "
    "(protocol.md § NodeId / PeerId, `#lzspecdecoderbound`). protocol.md stated the "
    "2^53 bound as a PRODUCER obligation and said nothing about what a decoder does "
    "when it receives a violation, which is exactly where the bindings diverged: "
    "lazily-js and lazily-dart refuse deliberately, and the other seven happen to "
    "fail closed because their json parser overflows — a property no test held in "
    "place. The clause is now normative — a decoder that cannot represent a received "
    "identifier exactly MUST reject the frame rather than round it — and this fixture "
    "replays it instead of asserting it in prose. Silent rounding is the worst of the "
    "three available behaviours because the frame decodes cleanly, the identifier "
    "addresses a DIFFERENT node, and nothing downstream can tell."
)

WIRE_ENCODING_NOTE = (
    "json scenarios carry `wire_json` as RAW TEXT, msgpack scenarios carry "
    "`wire_msgpack_hex` as lowercase hex, and the expectation is "
    "`expect.node_id_decimal`, a decimal STRING. None of the three is a JSON number "
    "on purpose: this file is itself JSON, so a runner that loaded a bare "
    "9007199254740993 through a double-backed JSON parser would round the fixture's "
    "own expected value to 9007199254740992 before the test could compare anything, "
    "and the test would pass against a decoder that rounds. A runner MUST parse "
    "`wire_json` with the codec under test, not re-serialize a pre-parsed object, "
    "MUST compare `expect.wire_input_fnv1a64` against the exact bytes it hands to "
    "that decoder, and MUST compare the decoded identifier by its decimal rendering."
)


def build() -> dict:
    scenarios = []
    for slug, node_id, outcome, why in CASES:
        for codec in ("json", "msgpack"):
            scenario = {
                "id": f"nodeid_{slug}_{codec}",
                "name": f"nodeid_{slug}_{codec}",
                "codec": codec,
                "variant": "Snapshot",
                "description": why,
            }
            if codec == "json":
                wire_input = _snapshot_json(node_id).encode("utf-8")
                scenario["wire_json"] = wire_input.decode("utf-8")
            else:
                wire_input = _snapshot_msgpack(node_id)
                scenario["wire_msgpack_hex"] = wire_input.hex()
            scenario["expect"] = {
                "wire_input_fnv1a64": _fnv1a64_hex(wire_input),
                "outcome": outcome,
                "node_id_decimal": str(node_id),
                "root_id_decimal": str(node_id),
                "epoch": EPOCH,
                "node_count": 1,
                "type_tag": TYPE_TAG,
                "payload": list(PAYLOAD),
            }
            scenarios.append(scenario)

    return {
        "description": DESCRIPTION,
        "protocol_version": 1,
        "kind": "NodeIdExactRange",
        "assertions": {
            # Prose keys (#lzprosekeyconvention) — discharged by naming the
            # executable keys that carry the obligation, never asserted and never
            # excused with free text. See docs/conformance.md.
            "prose": ["clause", "wire_encoding", "anti_vacuity"],
            "clause": (
                "a decoder that cannot represent a received NodeId/PeerId exactly MUST "
                "reject the frame; it MUST NOT round, truncate, saturate, or wrap"
            ),
            "required_of_binding": "MUST",
            "codecs": ["json", "msgpack"],
            "scenario_count": len(scenarios),
            "wire_encoding": WIRE_ENCODING_NOTE,
            "outcomes": {
                "exact": "the decoder MUST accept the frame and yield exactly `node_id_decimal`",
                "exact_or_reject": (
                    "the decoder MUST either yield exactly `node_id_decimal` or fail the "
                    "decode with an error; yielding any other value is the violation"
                ),
            },
            "anti_vacuity": (
                "the two `exact` scenarios are the control. `exact_or_reject` alone is "
                "satisfied by a runner that never decodes anything, so a binding must "
                "prove it decodes the boundary value correctly before its refusals count."
            ),
            "generator": "scripts/gen_nodeid_exact_range_fixture.py",
        },
        "scenarios": scenarios,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
