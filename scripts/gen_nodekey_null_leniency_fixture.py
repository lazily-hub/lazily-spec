#!/usr/bin/env python3
"""Regenerate conformance/codec/nodekey_null_leniency.json (`#lzkeynullstrict`).

protocol.md § NodeKey: omit-when-absent binds the ENCODER; a decoder MUST accept
both the omitted `key` field and an explicit `key: null`, and read both as
absent — refusing the null form and constructing a key from it are both
non-conforming.

Why a generator rather than a hand-written file: the msgpack half is a byte
string, and the interesting cases differ by ONE byte (`c0` nil versus an absent
map entry, which also changes the map header). Hand-pasted hex cannot be
reviewed for that; a generator that emits `nil` explicitly can.

Run: python3 scripts/gen_nodekey_null_leniency_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "conformance" / "codec" / "nodekey_null_leniency.json"

NODE = 7
TYPE_TAG = "i32"
PAYLOAD = [1, 2, 3]
EPOCH = 4
BASE_EPOCH = 3
PRESENT_KEY = "scores/alice"
FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3
U64_MASK = 2**64 - 1


def _fnv1a64_hex(data: bytes) -> str:
    digest = FNV1A64_OFFSET
    for byte in data:
        digest ^= byte
        digest = (digest * FNV1A64_PRIME) & U64_MASK
    return f"{digest:016x}"


# --- minimal MessagePack encoder ------------------------------------------
#
# Named-field maps keyed by the json field names, externally-tagged envelope —
# protocol.md § Frame codecs. `nil` is emitted explicitly so the "explicit null"
# scenarios provably carry a 0xc0 rather than just omitting the entry.


def _uint(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n <= 0xFF:
        return b"\xcc" + n.to_bytes(1, "big")
    raise ValueError("fixture integers stay small")


def _str(s: str) -> bytes:
    raw = s.encode("utf-8")
    if len(raw) < 32:
        return bytes([0xA0 | len(raw)]) + raw
    raise ValueError("fixture strings stay short")


NIL = b"\xc0"


def _array(items: list[bytes]) -> bytes:
    if len(items) < 16:
        return bytes([0x90 | len(items)]) + b"".join(items)
    raise ValueError("fixture arrays stay short")


def _map(pairs: list[tuple[str, bytes]]) -> bytes:
    if len(pairs) < 16:
        return bytes([0x80 | len(pairs)]) + b"".join(_str(k) + v for k, v in pairs)
    raise ValueError("fixture maps stay short")


def _node_fields(key_form: str) -> list[tuple[str, bytes]]:
    """`key_form` is 'omitted', 'null', or 'present'."""
    fields: list[tuple[str, bytes]] = [
        ("node", _uint(NODE)),
        ("type_tag", _str(TYPE_TAG)),
        ("state", _map([("Payload", _array([_uint(b) for b in PAYLOAD]))])),
    ]
    if key_form == "null":
        fields.append(("key", NIL))
    elif key_form == "present":
        fields.append(("key", _str(PRESENT_KEY)))
    return fields


def _snapshot_msgpack(key_form: str) -> bytes:
    body = _map(
        [
            ("epoch", _uint(EPOCH)),
            ("nodes", _array([_map(_node_fields(key_form))])),
            ("edges", _array([])),
            ("roots", _array([_uint(NODE)])),
        ]
    )
    return _map([("Snapshot", body)])


def _delta_msgpack(key_form: str) -> bytes:
    op = _map([("NodeAdd", _map(_node_fields(key_form)))])
    body = _map(
        [
            ("base_epoch", _uint(BASE_EPOCH)),
            ("epoch", _uint(EPOCH)),
            ("ops", _array([op])),
        ]
    )
    return _map([("Delta", body)])


def _node_json(key_form: str) -> str:
    payload = ", ".join(str(b) for b in PAYLOAD)
    fields = [
        f'"node": {NODE}',
        f'"type_tag": "{TYPE_TAG}"',
        f'"state": {{"Payload": [{payload}]}}',
    ]
    if key_form == "null":
        fields.append('"key": null')
    elif key_form == "present":
        fields.append(f'"key": "{PRESENT_KEY}"')
    return "{" + ", ".join(fields) + "}"


def _snapshot_json(key_form: str) -> str:
    return (
        '{"Snapshot": {'
        f'"epoch": {EPOCH}, '
        f'"nodes": [{_node_json(key_form)}], '
        '"edges": [], '
        f'"roots": [{NODE}]'
        "}}"
    )


def _delta_json(key_form: str) -> str:
    return (
        '{"Delta": {'
        f'"base_epoch": {BASE_EPOCH}, '
        f'"epoch": {EPOCH}, '
        f'"ops": [{{"NodeAdd": {_node_json(key_form)}}}]'
        "}}"
    )


# `field` names WHERE the optional key lives; `key_form` names WHICH wire form
# the scenario carries. The cross product is the point: every binding that got
# NodeSnapshot wrong got NodeAdd wrong the same way, in the same file.
CASES = [
    (
        "snapshot",
        "omitted",
        "Snapshot",
        "The form a conforming encoder emits. Every binding already read it, so this "
        "is the control: a runner that reports 'absent' without decoding satisfies the "
        "null scenarios trivially and has to prove it decodes something here first.",
    ),
    (
        "snapshot",
        "null",
        "Snapshot",
        "The form the clause is about. A serde-based peer that did not apply "
        "skip_serializing_if emits it, and rmp_serde's own decoder reads it as absent. "
        "lazily-py and lazily-zig REFUSED this frame; lazily-kt decoded it into a real "
        "key named `null`, because JsonNull is a JsonPrimitive whose content is the "
        "string \"null\". The re-encode assertion is what catches the third behaviour: "
        "reading it as absent is only half the rule, since the frame must go back out "
        "with the field OMITTED.",
    ),
    (
        "snapshot",
        "present",
        "Snapshot",
        "A real key, so the leniency above cannot be implemented by ignoring the field "
        "outright. A decoder that returns absent for everything passes both scenarios "
        "above and fails here.",
    ),
    (
        "node_add",
        "omitted",
        "Delta",
        "The same three forms on the OTHER field carrying an optional NodeKey. The "
        "NodeAdd delta op is where the same defect lived in all three bindings — one "
        "fix per binding covers both, but only a fixture that replays both proves it.",
    ),
    (
        "node_add",
        "null",
        "Delta",
        "The null form on NodeAdd. Worth replaying separately rather than assuming it "
        "shares NodeSnapshot's path: in lazily-kt the two sites were separate "
        "expressions, and a fix applied to one would have left the other inventing a "
        "key named `null`.",
    ),
    (
        "node_add",
        "present",
        "Delta",
        "A real key on NodeAdd, for the same reason as the Snapshot case.",
    ),
]

DESCRIPTION = (
    "NodeKey null-leniency on decode (protocol.md § NodeKey, `#lzkeynullstrict`). "
    "protocol.md said a self-describing codec OMITS an absent `key`, and that a decoder "
    "seeing no `key` field treats it as absent. That settled the omitted form and left "
    "the explicit `key: null` form undefined — and three bindings diverged there. The "
    "clause is now explicit: omit-when-absent binds the ENCODER, and a decoder MUST "
    "accept both forms as absent, refusing neither and constructing a key from neither. "
    "The null form is not hypothetical; a serde peer that did not apply "
    "`skip_serializing_if` emits it. Note the asymmetry every diverging binding tripped "
    "on: `CrdtOp.key` is ALWAYS written, null when unset, so each of them already read "
    "`key: null` correctly ONE FIELD OVER, in the same file."
)

WIRE_ENCODING_NOTE = (
    "json scenarios carry `wire_json` as RAW TEXT and msgpack scenarios carry "
    "`wire_msgpack_hex` as lowercase hex, so the exact wire form under test — an ABSENT "
    "map entry versus an explicit `null` / msgpack `nil` (0xc0) — survives into the "
    "runner. A pre-parsed object cannot express the difference between the two in every "
    "host language, and re-serializing one from a decoded value would test the runner's "
    "encoder instead of the fixture's bytes. A runner MUST compare "
    "`expect.wire_input_fnv1a64` against the exact bytes it hands to the decoder."
)

REENCODE_NOTE = (
    "`expect.reencoded_key_field_present` is the half a decode assertion cannot reach. "
    "Reading `key: null` as absent is only half the rule: the encoder must still emit "
    "the OMITTED form, so a binding that round-trips the null straight back out is "
    "non-conforming even though its decoded value looks right. A runner MUST re-encode "
    "the decoded message and inspect the resulting frame for the presence of the field."
)


def build() -> dict:
    scenarios = []
    for field, key_form, variant, why in CASES:
        for codec in ("json", "msgpack"):
            scenario = {
                "id": f"{field}_key_{key_form}_{codec}",
                "name": f"{field}_key_{key_form}_{codec}",
                "codec": codec,
                "field": field,
                "key_form": key_form,
                "variant": variant,
                "description": why,
            }
            if codec == "json":
                builder = _snapshot_json if field == "snapshot" else _delta_json
                wire_input = builder(key_form).encode("utf-8")
                scenario["wire_json"] = wire_input.decode("utf-8")
            else:
                builder = _snapshot_msgpack if field == "snapshot" else _delta_msgpack
                wire_input = builder(key_form)
                scenario["wire_msgpack_hex"] = wire_input.hex()
            scenario["expect"] = {
                "wire_input_fnv1a64": _fnv1a64_hex(wire_input),
                "decoded_key": PRESENT_KEY if key_form == "present" else None,
                "reencoded_key_field_present": key_form == "present",
                "node": NODE,
                "type_tag": TYPE_TAG,
                "payload": list(PAYLOAD),
                "epoch": EPOCH,
            }
            scenarios.append(scenario)

    return {
        "description": DESCRIPTION,
        "protocol_version": 1,
        "kind": "NodeKeyNullLeniency",
        "generator": "scripts/gen_nodekey_null_leniency_fixture.py",
        "assertions": {
            # Prose keys (#lzprosekeyconvention) — discharged by naming the
            # executable keys that carry the obligation, never asserted and never
            # excused with free text. See docs/conformance.md.
            "prose": [
                "clause",
                "wire_encoding",
                "reencode_obligation",
                "anti_vacuity",
            ],
            "clause": (
                "omit-when-absent binds the ENCODER; a decoder MUST accept both an "
                "omitted `key` and an explicit `key: null` and read both as absent, "
                "refusing neither and constructing a key from neither"
            ),
            "required_of_binding": "MUST",
            "codecs": ["json", "msgpack"],
            "fields": ["snapshot", "node_add"],
            "key_forms": ["omitted", "null", "present"],
            "scenario_count": len(scenarios),
            "wire_encoding": WIRE_ENCODING_NOTE,
            "reencode_obligation": REENCODE_NOTE,
            "anti_vacuity": (
                "the `omitted` and `present` scenarios are the controls. A runner that "
                "reports 'absent' without decoding satisfies every `null` scenario, and "
                "one that never decodes at all satisfies all of them; `present` forces a "
                "real key through and `omitted` forces a real decode."
            ),
        },
        "scenarios": scenarios,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
