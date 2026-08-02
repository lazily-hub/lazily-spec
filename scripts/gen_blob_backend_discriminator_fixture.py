#!/usr/bin/env python3
"""Regenerate conformance/codec/blob_backend_discriminator.json (`#lzblobbackendstrict`).

protocol.md § Zero-copy blob descriptor: `backend` is OPTIONAL and defaults to
`shm`, so a decoder MUST accept a descriptor that omits it — that absence is the
forward-compatibility channel, carrying every descriptor minted before the field
existed. A decoder MUST NOT extend the same tolerance to a *present* value
outside the enum: it must reject the frame and name the offending token.

Why the asymmetry needs a fixture. Nine bindings audited this site independently
and split 5-2 the wrong way: lazily-rs and lazily-js rejected an unknown token
while lazily-go, lazily-py, lazily-kt, lazily-zig and lazily-cpp normalized it to
`shm`, each documenting the normalization as deliberate wire forward-compat. The
five lenient bindings defended it identically — the shm backend then fails the
generation/epoch/checksum verification, so the descriptor resolves to nothing
rather than to another backend's bytes. That defence inverts the
`resolve_wrong_backend` theorem (docs/zero-copy-transport.md): the theorem
guarantees non-resolution STRUCTURALLY, by routing on `kind`, and normalizing an
unknown kind to `shm` is precisely routing a non-shm descriptor into the shm
table and then asking a 64-bit checksum to catch it. A new backend arrives by
adding an enum value — a spec change, not a wire event — so an unknown token is
not a newer peer, it is a corrupt or non-conforming one.

Why a generator rather than a hand-written file: the msgpack half is a byte
string, and the interesting scenarios differ by one map entry — an absent
`backend` key versus a present one whose value is a short string. Hand-pasted hex
cannot be reviewed for that.

Run: python3 scripts/gen_blob_backend_discriminator_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = (
    Path(__file__).resolve().parent.parent
    / "conformance"
    / "codec"
    / "blob_backend_discriminator.json"
)

NODE = 7
BASE_EPOCH = 8
EPOCH = 9
OFFSET = 40
LEN = 17
GENERATION = 2
CHECKSUM = 987654321

# The token no binding ships a backend for. Deliberately plausible: an RDMA/verbs
# adapter is named in docs/zero-copy-transport.md as an anticipated backend, so
# this is exactly the frame a peer running ahead of this build would emit.
UNKNOWN_BACKEND = "rdma"


# --- minimal MessagePack encoder ------------------------------------------
#
# Named-field maps keyed by the json field names, externally-tagged envelope —
# protocol.md § Frame codecs. Mirrors scripts/gen_nodekey_null_leniency_fixture.py
# so the two codec fixtures are byte-comparable by eye.


def _uint(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n <= 0xFF:
        return b"\xcc" + n.to_bytes(1, "big")
    if n <= 0xFFFF:
        return b"\xcd" + n.to_bytes(2, "big")
    if n <= 0xFFFFFFFF:
        return b"\xce" + n.to_bytes(4, "big")
    raise ValueError("fixture integers stay within u32")


def _str(s: str) -> bytes:
    raw = s.encode("utf-8")
    if len(raw) < 32:
        return bytes([0xA0 | len(raw)]) + raw
    raise ValueError("fixture strings stay short")


def _array(items: list[bytes]) -> bytes:
    if len(items) < 16:
        return bytes([0x90 | len(items)]) + b"".join(items)
    raise ValueError("fixture arrays stay short")


def _map(pairs: list[tuple[str, bytes]]) -> bytes:
    if len(pairs) < 16:
        return bytes([0x80 | len(pairs)]) + b"".join(_str(k) + v for k, v in pairs)
    raise ValueError("fixture maps stay short")


# --- the descriptor under test --------------------------------------------


def _descriptor_fields(backend_form: str) -> list[tuple[str, bytes]]:
    """`backend_form` is 'omitted' or a literal token to place in the field."""
    fields: list[tuple[str, bytes]] = [
        ("offset", _uint(OFFSET)),
        ("len", _uint(LEN)),
        ("generation", _uint(GENERATION)),
        ("epoch", _uint(EPOCH)),
        ("checksum", _uint(CHECKSUM)),
    ]
    if backend_form != "omitted":
        fields.append(("backend", _str(backend_form)))
    return fields


def _delta_msgpack(backend_form: str) -> bytes:
    payload = _map([("SharedBlob", _map(_descriptor_fields(backend_form)))])
    op = _map([("SlotValue", _map([("node", _uint(NODE)), ("payload", payload)]))])
    return _map(
        [
            (
                "Delta",
                _map(
                    [
                        ("base_epoch", _uint(BASE_EPOCH)),
                        ("epoch", _uint(EPOCH)),
                        ("ops", _array([op])),
                    ]
                ),
            )
        ]
    )


def _delta_json(backend_form: str) -> str:
    backend = "" if backend_form == "omitted" else f', "backend": "{backend_form}"'
    return (
        '{"Delta": {"base_epoch": %d, "epoch": %d, "ops": [{"SlotValue": '
        '{"node": %d, "payload": {"SharedBlob": {"offset": %d, "len": %d, '
        '"generation": %d, "epoch": %d, "checksum": %d%s}}}}]}}'
    ) % (
        BASE_EPOCH,
        EPOCH,
        NODE,
        OFFSET,
        LEN,
        GENERATION,
        EPOCH,
        CHECKSUM,
        backend,
    )


WIRE_ENCODING_NOTE = (
    "json scenarios carry `wire_json` as RAW TEXT and msgpack scenarios carry "
    "`wire_msgpack_hex` as lowercase hex, so the exact wire form under test — an "
    "ABSENT map entry versus a present short string — survives into the runner. The "
    "reject scenarios additionally CANNOT be carried as a parsed object: "
    "`schemas/defs.json` closes `backend` to an enum, so a fixture embedding "
    '`"backend": "rdma"` as structured JSON would fail the corpus\'s own schema '
    "gate. The enum binds a conforming ENCODER; these frames are what a decoder "
    "must survive, which is the same split `nodekey_null_leniency.json` makes."
)

REJECT_NOTE = (
    "A rejecting binding MUST name the offending token in its error. The failure "
    "this pins is not 'the frame was refused' but 'the frame was refused for the "
    "stated reason': a decoder that rejects the descriptor because it mis-parsed "
    "`checksum` passes a bare is-error assertion while implementing none of the "
    "clause. `error_names_token` is the assertion that separates them."
)

ANTI_VACUITY_NOTE = (
    "Three controls, each defeating a different way to pass without implementing "
    "the clause. (1) `backend_omitted` forces a real decode — a runner that reports "
    "`shm` without decoding satisfies it only by accident and fails `backend_arrow`. "
    "(2) `backend_arrow` forces the field to actually be READ — a decoder that "
    "ignores `backend` entirely and hardcodes `shm` passes the omitted and explicit-"
    "shm scenarios and fails here. (3) `backend_shm_explicit` forces the ENCODER "
    "half: `reencoded_backend_field_present` is false for shm and true for arrow, so "
    "a binding cannot satisfy the clause by round-tripping whatever it received. "
    "Without (2) and (3) a decoder that discards the discriminator passes four of "
    "six scenarios."
)

THEOREM_NOTE = (
    "resolve_wrong_backend (docs/zero-copy-transport.md) — a descriptor of one kind "
    "never resolves against a different backend's table, so receivers route by kind. "
    "Normalizing an unknown kind to `shm` routes rather than refuses, which is what "
    "makes it non-conforming even though the checksum usually hides the consequence."
)


def build() -> dict:
    scenarios: list[dict] = []

    accept_forms = [
        (
            "omitted",
            "omitted",
            "shm",
            False,
            "The forward-compatibility channel, and the only one. Every descriptor "
            "minted before `backend` existed has this shape, which is why the field "
            "is optional and why a decoder MUST read its absence as `shm`. This is "
            "also the control that forces a real decode.",
        ),
        (
            "shm_explicit",
            "shm",
            "shm",
            False,
            "The redundant-but-legal form. A conforming encoder OMITS `backend` when "
            "it is `shm`, so a decoder must accept this on the way in and must not "
            "emit it on the way out — `reencoded_backend_field_present` is false "
            "here and true for arrow, which is the encoder half of the clause.",
        ),
        (
            "arrow",
            "arrow",
            "arrow",
            True,
            "A second real backend, so the leniency above cannot be implemented by "
            "ignoring the field outright. A decoder that hardcodes `shm` passes both "
            "scenarios above and fails here. It is also the scenario that proves the "
            "enum is genuinely multi-valued on the wire, which is what makes routing "
            "by `kind` (the resolve_wrong_backend theorem) meaningful at all.",
        ),
    ]

    for suffix, form, expected, reencoded, description in accept_forms:
        for codec in ("json", "msgpack"):
            scenario = {
                "id": f"backend_{suffix}_{codec}",
                "name": f"backend_{suffix}_{codec}",
                "codec": codec,
                "backend_form": form,
                "outcome": "accept",
                "variant": "Delta",
                "description": description,
            }
            if codec == "json":
                scenario["wire_json"] = _delta_json(form)
            else:
                scenario["wire_msgpack_hex"] = _delta_msgpack(form).hex()
            scenario["expect"] = {
                "decoded_backend": expected,
                "reencoded_backend_field_present": reencoded,
                "node": NODE,
                "offset": OFFSET,
                "len": LEN,
                "generation": GENERATION,
                "epoch": EPOCH,
                "checksum": CHECKSUM,
            }
            scenarios.append(scenario)

    reject_description = (
        "The clause. A present `backend` outside the enum MUST be refused, naming "
        "the token. Five of nine bindings normalized it to `shm` and documented the "
        "normalization as forward-compat; that is the case this scenario exists to "
        "make non-conforming. Normalizing routes a non-shm descriptor into the shm "
        "table, which is the exact misroute resolve_wrong_backend proves cannot "
        "happen — the lenient bindings were relying on the generation/epoch/checksum "
        "verification to produce, probabilistically and downstream, the outcome the "
        "routing rule guarantees structurally. Note also what the normalization "
        "costs on the OTHER side: `shm` is a real backend this build resolves, so a "
        "checksum collision returns bytes, whereas a refusal is a visible protocol "
        "error the peer recovers from by resync."
    )
    for codec in ("json", "msgpack"):
        scenario = {
            "id": f"backend_unknown_{codec}",
            "name": f"backend_unknown_{codec}",
            "codec": codec,
            "backend_form": UNKNOWN_BACKEND,
            "outcome": "reject",
            "variant": "Delta",
            "description": reject_description,
        }
        if codec == "json":
            scenario["wire_json"] = _delta_json(UNKNOWN_BACKEND)
        else:
            scenario["wire_msgpack_hex"] = _delta_msgpack(UNKNOWN_BACKEND).hex()
        scenario["expect"] = {
            "rejected": True,
            "error_names_token": UNKNOWN_BACKEND,
        }
        scenarios.append(scenario)

    return {
        "description": (
            "Blob-backend discriminator strictness on decode (protocol.md § Zero-copy "
            "blob descriptor, `#lzblobbackendstrict`). `backend` is optional and "
            "defaults to `shm`, and that OPTIONALITY is the forward-compatibility "
            "channel — it carries every descriptor minted before the field existed. A "
            "present value outside the enum is a different fact and gets the opposite "
            "answer: the decoder MUST reject the frame and name the token. Audited "
            "across nine bindings, which split 5-2 the wrong way while each documented "
            "its choice as deliberate; an undocumented default and a deliberate one are "
            "indistinguishable from the outside, and so, it turns out, are two "
            "deliberate ones pointing in opposite directions."
        ),
        "protocol_version": 1,
        "kind": "BlobBackendDiscriminator",
        "assertions": {
            "clause": (
                "an OMITTED `backend` MUST decode as `shm`; a PRESENT `backend` outside "
                "{shm, arrow, in_process} MUST be rejected, naming the token, and MUST "
                "NOT be normalized to `shm` or to any other backend"
            ),
            "required_of_binding": "MUST",
            "codecs": ["json", "msgpack"],
            "backends": ["shm", "arrow", "in_process"],
            "outcomes": ["accept", "reject"],
            "scenario_count": len(scenarios),
            "wire_encoding": WIRE_ENCODING_NOTE,
            "reject_obligation": REJECT_NOTE,
            "anti_vacuity": ANTI_VACUITY_NOTE,
            "theorem": THEOREM_NOTE,
            "generator": "scripts/gen_blob_backend_discriminator_fixture.py",
        },
        "scenarios": scenarios,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
