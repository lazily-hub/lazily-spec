# Shared Wire Model and Codec Generation

lazily has two halves that need different treatment across bindings:

- **The data plane** (wire records, enums, envelopes, codecs) is the same in
  every binding by definition. It is generated from one shared model.
- **The kernel** (`Source` / `Computed` / `Effect`, invalidation, scheduling,
  teardown scopes) is written by hand in each binding. Its hard problems are
  per-language lowering decisions: ownership, GC, locking, and async. A shared
  template would only move those decisions somewhere harder to read.

## Pipeline

```text
schemas/*.json ──► codegen/wire-model.json ──► per-binding backend ──► generated wire file
 (normative)        (golden, committed)        (rust, go, python,     (committed in the binding)
                                                kotlin)
```

1. `codegen/surfaces.json` names each generated surface: its source schema,
   plus the repository, path, and options for each participating binding.
2. `scripts/wire_codegen.py` builds a language-neutral model from those schemas
   and commits it as `codegen/wire-model.json`. A schema change shows up there
   as one readable diff before any binding is touched. Each surface carries a
   `model_sha256`, which is stamped into every generated file's header.
3. Thin backends lower the model into wire declarations. The binding keeps its
   semantics (constructors, terminality, projections) in hand-written code that
   uses the generated types.

## Model kinds

| Kind | Schema shape | Rust | Go | Python | Kotlin |
|---|---|---|---|---|---|
| `string` | `"type": "string"` | `String` | `string` | `str` | `String`, `min_length` checked in `init` |
| `u64` | `"type": "integer", "minimum": 0` | `u64` | `uint64` | `int`, range-checked to `0..=2^64-1` | `ULong`; the decoder accepts only a bare integer literal in `0..=2^64-1` |
| `bool` | `"type": "boolean"` | `bool` | `bool` | `bool` | `Boolean` |
| `list` | `"type": "array"` + `items` | `Vec<T>` | `[]T` (marshals `[]`, never `null`) | `list[T]` | `List<T>` (defaults to empty) |
| `nullable` | `oneOf: [null, T]` (inline or a `$defs` alias) | `Option<T>` | `*T` | `T \| None` | `T?` |
| `ref` | local `#/$defs/X` record or enum | `X` | `X` | `X` | `X` |
| `enum` | string `enum` + `x-lazily-enum-docs` | `enum`, `rename_all = "snake_case"` when every value round-trips | string type, constants, `…FromWire`, rejecting `UnmarshalJSON` | `Enum` with `from_wire` / `to_wire` | `enum class` with `wireName` and a rejecting `fromWire` |
| `record` | closed object (`additionalProperties: false`) | `struct` with optional serde derives | `struct` + `…FromWire` | frozen, slotted `dataclass` with `from_wire` / `to_wire` | `data class` with `toJson` and a strict companion `fromJson` |
| `envelope` | root `x-lazily-envelope`, externally tagged | single-variant `enum` | not lowered (callers decode the tagged body) | lowered onto the variant record, whose codec carries the tag | `sealed interface`, one `data class` per variant, with `encodeJson` / `decodeJson` |

Python cannot add methods to a generated class from another module the way a
Rust `impl` block or a Go method can. Its target therefore names
`mixins`: hand-written classes in `semantics_module` that the generated class
inherits from. For receipts, `ReceiptOutcomeSemantics` supplies `is_terminal`
and `CausalReceiptsSemantics` supplies `group_by_causation` and the JSON byte
helpers. Generated Python is marked `# fmt: off`, because the generator
cannot depend on a formatter.

Kotlin needs no mixins: extension members add behaviour to a generated class
from another file. Every generated record and envelope declares a `companion
object`, so hand-written factories such as `CausalReceipt.observed(...)` are
extensions on the companion and keep their call syntax. The Kotlin target names
`variant_fields`, the property each envelope variant wraps its record in
(`CausalReceiptsMessage.batch` for receipts; `value` by default). Generated
Kotlin goes through lazily-kt's `spotlessCheck` like any other source, so the
backend emits exactly the layout ktlint produces, and a formatter change shows
up as generated-file drift.

A field's *presence* is modelled separately from its type: a `required` +
`nullable` field is always on the wire and is `null` when absent, while an
`optional` field may be missing. Open enums and optional fields are already
modelled, but no backend lowers them yet, so the backends refuse them.

## Strict decoding

Every generated decoder enforces what the schema says about a record's keys:

- **Closed records reject unknown keys.** `additionalProperties: false` is
  normative, so an extra key is an error, never ignored.
- **Required fields must be present, including nullable ones.** `reason` and
  `payload_hash` are `required` and `null` when absent. A decoder that defaults
  a *missing* key to `null` accepts a frame the schema rejects.

| Backend | Unknown key | Missing required-nullable key |
|---|---|---|
| Rust | `serde(deny_unknown_fields)` | `deserialize_with = "required_nullable"` (a bare `Option` defaults a missing key to `None`) |
| Go | `UnmarshalJSON` compares the exact key set first; `encoding/json` alone ignores unknown keys and matches keys case-insensitively | same check |
| Python | `from_wire` compares the exact key set and type-checks each value | same check |
| Kotlin | `fromJson` compares the exact key set and type-checks each value; kotlinx.serialization's `jsonPrimitive.content` alone reads a number as a string and a string as a number | same check |

This was a decision, not a refactor. Before `#lzwiremodel2`, Rust and Go
accepted unknown keys and a missing `reason` / `payload_hash`, and Python also
accepted a missing `receipts` list. Until `#lzwiremodel3`, Kotlin accepted
unknown keys, a missing `reason` / `payload_hash`, and a number where a
string belongs. The case for strict:

- Every receipt in the conformance corpus carries all seven keys and no
  others, so no fixture changes.
- Every binding's encoder always emits `reason` and `payload_hash`, as `null`
  when absent.
- The spec already settled the same question for the blob `backend`
  discriminator (`#lzblobbackendstrict` in `protocol.md`): rejection is the
  conforming behaviour, and lenient decoding for "forward-compat" was the
  defect.

Hand-written bindings that do not consume a generated surface keep their own
decoders until they are lowered. They decode every conforming frame
identically and differ only on frames the schema rejects.

## Fail-closed rules

The model accepts only the shapes it can lower faithfully. Anything else stops
generation with an `UnsupportedSchema` error rather than drifting quietly out of
the generated surface. That includes:

- a non-local `$ref`;
- an integer without `minimum: 0`;
- an open object;
- a declaration without a `description`;
- an enum value without an `x-lazily-enum-docs` entry;
- a wire name that does not lower to an identifier.

## Checks

| Command | What it proves |
|---|---|
| `make wire-codegen-check` | The golden model matches the schemas, and every present sibling's generated file matches backend output byte for byte. Absent siblings are reported as `staged`. |
| `make wire-codegen` | Regenerates the golden model and every present sibling's file. Commit each repository's result alongside the schema edit. |
| CI (`coverage` job) | Same check with `--require-all` against the published `main` of every participating binding. |

Push binding changes before the lazily-spec change. lazily-spec CI checks the
bindings' published `main`.

## Surfaces

| Surface | Schema | Bindings |
|---|---|---|
| `receipts` | `schemas/receipts.json` | lazily-rs `src/generated/receipts.rs`, lazily-go `receipts_wire_gen.go`, lazily-py `src/lazily/_receipts_wire_gen.py`, lazily-kt `src/main/kotlin/io/github/lazily/ReceiptsWireGen.kt` |

Lowering the receipts surface found the same real wire mismatch twice. Go
had `generation` as `int64` and Kotlin had it as `Long`; both accept negative
values that the schema forbids, and neither can hold a generation past
`2^63-1`. Go now decodes it as `uint64` and Kotlin as `ULong`. Both command
planes keep their signed generations and compare the two without wrapping
either side (`receiptGenerationMatches`), reporting a receipt generation past
the signed maximum capped rather than wrapped.

## When to add a surface

Add a surface only when the generator removes more hand-written code than it
adds. After receipts in four bindings, the generator still does not pass that
test:

- **Removed:** about 170 hand-written lines across Rust and Go, plus 141 from
  lazily-py `ipc.py`, plus 177 from lazily-kt `Receipt.kt`. 81 of the Python
  lines and 58 of the Kotlin lines moved back as hand-written semantics,
  because they are behaviour, not wire format.
- **Added:** about 1,290 lines of generator, of which the Kotlin backend is
  about 330.

Each binding's backend costs roughly twice the hand-written codec it removes.
What a binding gains is strictness and one source of truth, not fewer lines:
Kotlin's hand-written decoder accepted unknown keys, missing nullable keys,
numbers in string fields, and negative generations.

Nor is any second surface a cheap addition. Each candidate needs a model kind
that does not exist yet, so the generator must grow before it can remove
anything:

| Schema | First blocker |
|---|---|
| `reliable-sync.json` | multi-variant externally-tagged unions with PascalCase tags |
| `delta.json` | `DeltaOp`, a multi-variant tagged union |
| `message-passing.json` | `CommandId`, a newtype alias |
| `snapshot.json` | declarations without a `description` |

lazily-js is the remaining large binding on receipts. Its codec lives in the
`index.js` monolith beside a hand-written `index.d.ts`, so a js backend must
generate both and split the module, which costs more than the Kotlin backend
did. Modelling multi-variant tagged unions is the step that unlocks a second
surface (`delta`, then `reliable-sync`) and is where the generator can start
removing more than it adds.
