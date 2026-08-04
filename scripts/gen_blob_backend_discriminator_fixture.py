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

# The Delta frame's epoch and the ShmBlobRef descriptor's epoch are DIFFERENT
# numbers on purpose. v1 carried 9 in both, so a runner that read the frame's
# epoch and a runner that read the descriptor's both satisfied a single
# `expect.epoch` — the assertion could not tell them apart, and two bindings
# reported it independently. They are separate facts on the wire (the frame
# epoch orders deltas; the descriptor epoch is the arena incarnation the blob
# was written into), so the fixture now names both and gives them different
# values. `expect.epoch` is deliberately GONE rather than redefined: a runner
# still reading it fails loudly instead of silently reading the other one.
FRAME_EPOCH = 9
BLOB_EPOCH = 5

OFFSET = 40
LEN = 17
GENERATION = 2
CHECKSUM = 987654321

# The token no binding ships a backend for. Deliberately plausible: an RDMA/verbs
# adapter is named in docs/zero-copy-transport.md as an anticipated backend, so
# this is exactly the frame a peer running ahead of this build would emit.
UNKNOWN_BACKEND = "rdma"

# The non-string probe (`#lzblobbackendstrict` v2). The clause is written
# entirely about TOKENS, so a runtime whose reader coerces rather than throws on
# a number in a string position normalizes silently through a door the clause
# does not describe — one binding's only real defect was exactly this, and it
# escaped as an exception type outside the family its own codec documents. A
# small positive integer is the cheapest form of it: msgpack encodes it as a
# single positive-fixint byte in the slot a fixstr would occupy.
NON_STRING_BACKEND = 7
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


def _nil() -> bytes:
    return b"\xc0"


# A `backend_form` is the fixture's LABEL for a wire shape, not the token itself.
# Three of the seven forms carry no token at all — `omitted` writes no map entry,
# `null` writes an explicit nil, and `non_string` writes an integer where a token
# belongs — so the label and the value are separate from here down.
_OMITTED = "omitted"
_NULL = "null"
_NON_STRING = "non_string"
_TOKEN_FORMS = ("shm", "arrow", "in_process", UNKNOWN_BACKEND)


def _backend_msgpack(backend_form: str) -> bytes | None:
    """The msgpack value for `backend`, or None when the entry is absent."""
    if backend_form == _OMITTED:
        return None
    if backend_form == _NULL:
        return _nil()
    if backend_form == _NON_STRING:
        return _uint(NON_STRING_BACKEND)
    return _str(backend_form)


def _backend_json(backend_form: str) -> str | None:
    """The raw json text for `backend`, or None when the entry is absent."""
    if backend_form == _OMITTED:
        return None
    if backend_form == _NULL:
        return "null"
    if backend_form == _NON_STRING:
        return str(NON_STRING_BACKEND)
    return f'"{backend_form}"'


def _descriptor_fields(backend_form: str) -> list[tuple[str, bytes]]:
    fields: list[tuple[str, bytes]] = [
        ("offset", _uint(OFFSET)),
        ("len", _uint(LEN)),
        ("generation", _uint(GENERATION)),
        ("epoch", _uint(BLOB_EPOCH)),
        ("checksum", _uint(CHECKSUM)),
    ]
    backend = _backend_msgpack(backend_form)
    if backend is not None:
        fields.append(("backend", backend))
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
                        ("epoch", _uint(FRAME_EPOCH)),
                        ("ops", _array([op])),
                    ]
                ),
            )
        ]
    )


def _delta_json(backend_form: str) -> str:
    value = _backend_json(backend_form)
    backend = "" if value is None else f', "backend": {value}'
    return (
        '{"Delta": {"base_epoch": %d, "epoch": %d, "ops": [{"SlotValue": '
        '{"node": %d, "payload": {"SharedBlob": {"offset": %d, "len": %d, '
        '"generation": %d, "epoch": %d, "checksum": %d%s}}}}]}}'
    ) % (
        BASE_EPOCH,
        FRAME_EPOCH,
        NODE,
        OFFSET,
        LEN,
        GENERATION,
        BLOB_EPOCH,
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
    "must survive, which is the same split `nodekey_null_leniency.json` makes. A "
    "runner MUST compare `expect.wire_input_fnv1a64` against the exact bytes it "
    "hands to the decoder."
)

REJECT_NOTE = (
    "A rejecting binding MUST name the offending token in its error. The failure "
    "this pins is not 'the frame was refused' but 'the frame was refused for the "
    "stated reason': a decoder that rejects the descriptor because it mis-parsed "
    "`checksum` passes a bare is-error assertion while implementing none of the "
    "clause. `error_names_token` is the assertion that separates them."
)

ANTI_VACUITY_NOTE = (
    "Four controls, each defeating a different way to pass without implementing "
    "the clause. (1) `backend_omitted` forces a real decode — a runner that reports "
    "`shm` without decoding satisfies it only by accident and fails `backend_arrow`. "
    "(2) `backend_arrow` forces the field to actually be READ — a decoder that "
    "ignores `backend` entirely and hardcodes `shm` passes the omitted and explicit-"
    "shm scenarios and fails here. (3) `backend_shm_explicit` forces the ENCODER "
    "half: `reencoded_backend_field_present` is false for shm and true for arrow, so "
    "a binding cannot satisfy the clause by round-tripping whatever it received. "
    "(4) `backend_in_process` forces the VOCABULARY to be complete: v1 declared "
    "three backends in `assertions.backends` and carried scenarios for two, so a "
    "binding knowing only {shm, arrow} rejected `in_process` — naming the token, "
    "conformingly — and passed all eight scenarios while contradicting the enum "
    "this clause declares. Reading the discriminator and knowing the vocabulary are "
    "different facts and now have different controls. "
    "TWO CODECS ARE NOT TWO IMPLEMENTATIONS: several bindings bridge MessagePack "
    "into the same DOM the JSON decoder produces, or share one serde impl, so the "
    "msgpack half of a scenario pair can yield ONE discriminator verdict rather "
    "than an independent second one. It still covers the bridge and the encoder; a "
    "fully green run must not be read as two implementations agreeing. A binding "
    "whose two codecs share a decode path should record that in its own ledger "
    "rather than infer independence from the scenario count."
)

BACKEND_FORMS_NOTE = (
    "The seven wire shapes `backend` can arrive in, each carried in both codecs. "
    "Four are TOKENS (`shm`, `arrow`, `in_process`, `rdma`) and three are not: "
    "`omitted` writes no map entry at all, `null` writes an explicit nil, and "
    "`non_string` writes an integer in the slot a token belongs in. A runner MUST "
    "check that every backend in `assertions.backends` appears as the "
    "`decoded_backend` of some accept scenario — that is the assertion which would "
    "have caught v1's missing `in_process`, and it cannot be derived from a "
    "scenario count."
)

NULL_NOTE = (
    "An explicit `backend: null` is the ABSENT form, not a present-unknown one, and "
    "decodes as `shm` (protocol.md § the `backend` discriminator, following § NodeKey "
    "and `#lzkeynullstrict`). A serde-style peer that did not apply "
    "`skip_serializing_if` to an optional field emits `null` where a conforming "
    "encoder omits, so refusing it is stricter than the reference implementation on a "
    "frame the reference implementation produces. The null frames are therefore "
    "accept scenarios that are deliberately schema-INVALID: `schemas/defs.json` "
    "types `backend` as a string, which binds the ENCODER, and the decoder's "
    "leniency is a separate fact. Four bindings raised this edge independently while "
    "implementing v1 and had already split three ways on it — accept-as-`shm`, an "
    "ExpectedString error naming nothing, and a refusal naming the empty token — "
    "which is why it is a scenario rather than a sentence."
)

NON_STRING_NOTE = (
    "A `backend` that is present and not a string MUST be rejected, and the refusal "
    "MUST arrive through the codec's documented decode-error family — the same "
    "family the unknown-token refusal uses, so one catch handles both. That second "
    "half is the whole point of the scenario: a refusal raised as a type outside the "
    "family every caller already guards a decode with is invisible, because the "
    "frame still fails but it fails past the handler. `error_names_token` is NOT "
    "asserted here; there is no token to name, and requiring the field name would "
    "pin a message format no codec's native type error carries. `rejection_kind` "
    "tells the runner which of the two refusals it is looking at."
)

EPOCH_NOTE = (
    "`expect.frame_epoch` and `expect.blob_epoch` are DIFFERENT numbers, and "
    "`expect.epoch` no longer exists. v1 carried 9 in both the Delta frame and the "
    "ShmBlobRef descriptor, so a runner reading the frame's epoch and a runner "
    "reading the descriptor's both satisfied one `expect.epoch` — the assertion "
    "could not tell them apart, and two bindings reported it independently. They "
    "are separate facts (the frame epoch orders deltas; the descriptor epoch is the "
    "arena incarnation the blob was written into). The old key was REMOVED rather "
    "than redefined so a runner still reading it fails loudly instead of silently "
    "reading the other one."
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
            _OMITTED,
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
        (
            "in_process",
            "in_process",
            "in_process",
            True,
            "The THIRD declared backend, and the one v1 declared without carrying. A "
            "binding that knows only {shm, arrow} rejects this token — naming it, "
            "conformingly, by the letter of the clause — and passed every v1 "
            "scenario while implementing a smaller enum than the clause declares. "
            "Three bindings reported the hole independently while replaying v1. "
            "`arrow` proves the discriminator is READ; this proves the vocabulary "
            "is COMPLETE, and no count of scenarios substitutes for it.",
        ),
        (
            "null",
            _NULL,
            "shm",
            False,
            "An explicit null is the ABSENT form, not a present-unknown one, and "
            "decodes as `shm` — the § NodeKey rule (`#lzkeynullstrict`), not the "
            "unknown-token rule, because a serde-style peer that skipped "
            "`skip_serializing_if` emits null where a conforming encoder omits. "
            "Refusing it would be stricter than the reference implementation on a "
            "frame the reference implementation produces. The encoder half still "
            "holds: the re-encoded frame carries no `backend` entry, so the null "
            "does not survive a round trip. This frame is deliberately "
            "schema-INVALID (see `assertions.null_form`) — the enum binds the "
            "encoder, and the decoder's leniency is the separate fact under test.",
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
                wire_input = _delta_json(form).encode("utf-8")
                scenario["wire_json"] = wire_input.decode("utf-8")
            else:
                wire_input = _delta_msgpack(form)
                scenario["wire_msgpack_hex"] = wire_input.hex()
            scenario["expect"] = {
                "wire_input_fnv1a64": _fnv1a64_hex(wire_input),
                "decoded_backend": expected,
                "reencoded_backend_field_present": reencoded,
                "node": NODE,
                "offset": OFFSET,
                "len": LEN,
                "generation": GENERATION,
                "frame_epoch": FRAME_EPOCH,
                "blob_epoch": BLOB_EPOCH,
                "checksum": CHECKSUM,
            }
            scenarios.append(scenario)

    unknown_description = (
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
    non_string_description = (
        "The same refusal, reached through a door the clause does not describe. The "
        "clause is written entirely about TOKENS, so a runtime whose reader coerces "
        "rather than throws on a number in a string position normalizes silently "
        "here while passing every token scenario. One binding's only real defect "
        "under v1 was exactly this. The refusal MUST also arrive through the codec's "
        "documented decode-error family — `rejection_is_decode_error`, asserted on "
        "both reject forms — because a refusal raised outside the family every "
        "caller already guards a decode with fails PAST the handler: the frame is "
        "still refused and the peer still never sees the error. No token is named, "
        "because there is no token."
    )

    reject_forms = [
        ("unknown", UNKNOWN_BACKEND, "unknown_token", unknown_description),
        ("non_string", _NON_STRING, "non_string", non_string_description),
    ]

    for suffix, form, rejection_kind, description in reject_forms:
        for codec in ("json", "msgpack"):
            scenario = {
                "id": f"backend_{suffix}_{codec}",
                "name": f"backend_{suffix}_{codec}",
                "codec": codec,
                "backend_form": form,
                "outcome": "reject",
                "variant": "Delta",
                "description": description,
            }
            if codec == "json":
                wire_input = _delta_json(form).encode("utf-8")
                scenario["wire_json"] = wire_input.decode("utf-8")
            else:
                wire_input = _delta_msgpack(form)
                scenario["wire_msgpack_hex"] = wire_input.hex()
            expect = {
                "wire_input_fnv1a64": _fnv1a64_hex(wire_input),
                "rejected": True,
                "rejection_kind": rejection_kind,
                "rejection_is_decode_error": True,
            }
            if rejection_kind == "unknown_token":
                expect["error_names_token"] = form
            scenario["expect"] = expect
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
            "deliberate ones pointing in opposite directions. FIXTURE v2 adds the "
            "four shapes v1 declared or implied without carrying — `in_process`, an "
            "explicit null, a non-string value, and a Delta epoch distinct from the "
            "descriptor epoch — every one of which was found by a binding REPLAYING "
            "v1 rather than by reviewing it."
        ),
        "protocol_version": 1,
        "kind": "BlobBackendDiscriminator",
        "generator": "scripts/gen_blob_backend_discriminator_fixture.py",
        "assertions": {
            # Which of the keys below are PROSE (#lzprosekeyconvention). A prose
            # key states an obligation in English and carries no value a runner
            # can compare against observed behaviour, so it is DISCHARGED by
            # naming the executable keys that do — never asserted (that pins
            # wording) and never excused with a free-text reason (that is
            # unfalsifiable). The corpus declares the set so nine runners cannot
            # each decide it differently. See docs/conformance.md.
            "prose": [
                "clause",
                "wire_encoding",
                "backend_form_vocabulary",
                "reject_obligation",
                "null_form",
                "non_string_form",
                "epoch_disambiguation",
                "anti_vacuity",
                "theorem",
            ],
            "clause": (
                "an OMITTED or NULL `backend` MUST decode as `shm`; a PRESENT `backend` "
                "that is not one of {shm, arrow, in_process} MUST be rejected through "
                "the codec's documented decode-error family — naming the token when "
                "there is one — and MUST NOT be normalized to `shm` or to any other "
                "backend"
            ),
            "required_of_binding": "MUST",
            "codecs": ["json", "msgpack"],
            "backends": ["shm", "arrow", "in_process"],
            "backend_forms": [
                _OMITTED,
                "shm",
                "arrow",
                "in_process",
                _NULL,
                _NON_STRING,
                UNKNOWN_BACKEND,
            ],
            "outcomes": ["accept", "reject"],
            "rejection_kinds": ["unknown_token", "non_string"],
            "scenario_count": len(scenarios),
            "wire_encoding": WIRE_ENCODING_NOTE,
            "backend_form_vocabulary": BACKEND_FORMS_NOTE,
            "reject_obligation": REJECT_NOTE,
            "null_form": NULL_NOTE,
            "non_string_form": NON_STRING_NOTE,
            "epoch_disambiguation": EPOCH_NOTE,
            "anti_vacuity": ANTI_VACUITY_NOTE,
            "theorem": THEOREM_NOTE,
        },
        "scenarios": scenarios,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
