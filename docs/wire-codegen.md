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
| `ref` | `#/$defs/X` in the same schema, or `defs.json#/$defs/X` (pulled into the surface transitively) | `X` | `X` | `X` | `X` |
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
`optional` field may be missing. Open enums are modelled but no backend lowers
them yet. Optional fields are lowered by the Python backend (omitted on encode
when `None`; absent or `null` on decode), by Go (a pointer, omitted when nil),
and by Rust inside union variant bodies (codec-aware, below); Kotlin refuses
them.

### Kinds added for `delta` (`#lzwiremodel4`, lowered for Python by `#lzwiremodel5`)

These kinds exist so the `delta` surface can be modelled. The Python, Go and
Rust backends lower `union` and `bytes`; Python lowers a scalar `alias`, Go maps
one onto a hand-written signed type, and Rust requires it `external`. Kotlin
refuses all three with "modelled but not yet lowered".

| Kind | Schema shape | Model |
|---|---|---|
| `union` | `$defs` entry whose `oneOf` branches are closed single-key objects keyed by a PascalCase tag (`{"CellSet": {...}}`), or bare string `const` unit variants (`"Opaque"`) | `variants: [{tag, doc, payload}]`, `payload: null` for a unit variant |
| `alias` | a named scalar `$defs` entry (`NodeId` = u64, `NodeKey` = constrained string) | `target` type expression |
| `bytes` | `array` of `integer` `0..=255` | serialized bytes as a JSON array of u8, never base64 |
| `u64` with `maximum` | `maximum: 18446744073709551615` | same as `u64`; any other maximum is refused |
| string constraints | `maxLength`, `pattern` | `max_length`, `pattern` beside `min_length` |
| inline enum | a field's `"type": "string", "enum"` with `x-lazily-name` + `x-lazily-enum-docs` | a named `enum` declaration (`BlobBackendKind`) |
| field `default` | `default` on an optional field | `default` on the field; refused on a required one |

A variant's doc comes from its `oneOf` branch `description`, else from its
payload's. A union needs two or more distinct tags, and a branch `title`, when
present, must equal its tag.

### Python union lowering

A union lowers to a base class plus one frozen, slotted dataclass per variant,
named `<Union>_<Tag>` (`DeltaOp_CellSet`, `NodeState_Opaque`), which is the
shape lazily-py's hand-written IPC types already had.

- **Record payloads are flattened.** `CellSet` carries `CellSetBody`; the
  variant class takes the body's fields directly (`DeltaOp_CellSet(node,
  payload)`), and the body record is not emitted.
- **Any other payload is one named field**, which the target names in
  `variant_fields` (`"IpcValue.Inline": "data"`, `"IpcValue.SharedBlob":
  "blob"`). A non-record payload without a name is refused.
- **Unit variants** (`"Opaque"`) are fieldless classes encoding to the bare tag.
- **`from_wire` on the base** accepts exactly one known tag; each variant
  decodes its body strictly through `_from_body`.

Three target options shape what is emitted:

| Option | Effect |
|---|---|
| `external` | `{"NodeKey": "._wire_scalars"}`: the type is hand-written in that module and keeps its own codec. The generator imports it, never resolves it as an alias, and does not emit declarations reachable only through it (`BlobBackendKind`). |
| `variant_fields` | field name for each non-record union payload |
| `envelope: false` | do not emit the envelope; the binding's own message type carries the tag (lazily-py's `IpcMessage`) |

### Go union lowering (`#lzwiremodel6`)

A surface with a union takes a separate Go path; receipts keep the struct-tag
lowering byte for byte. The plan (flattened record payloads, `variant_fields`,
`external`, reachability) is the Python backend's.

- **A union is an interface** (`json.Marshaler` plus an `is<Union>()` marker)
  and one struct per variant, named `<Union><Tag>` (`DeltaOpCellSet`,
  `IpcValueInline{Bytes}`, `NodeStateOpaque{}`), which is the shape lazily-go's
  hand-written IPC types already had. `unmarshal<Union>(raw)` decodes strictly.
- **`interface_methods`** adds hand-written methods to the interface
  (`DeltaOp.TargetReadable`); each variant's implementation stays in the
  binding beside the generated file, as a Go method on a generated type.
- **`int64`** maps a u64 slot to a hand-written signed type: an alias
  (`"NodeId": "NodeId"`) or a field (`"Delta.base_epoch": "Epoch"`). lazily-go
  holds node ids and epochs in `int64`; the decoder refuses a value past 2^63-1
  rather than wrap it (protocol.md § NodeId / PeerId lets a narrower binding
  refuse at decode), and the encoder refuses a negative one. This is the
  alternative to a binding-wide `uint64` migration.
- **JSON is built by hand** (keys in declaration order, no struct tags), so
  the output needs no tag alignment and stays `gofmt`-clean as generated.
- An optional field is a pointer (`Key *NodeKey`), omitted when nil and read as
  absent from either an omitted key or `null`.

`external` is how decoder rules beyond the schema stay hand-written:
`NodeKey`'s byte and segment bounds, and `ShmBlobRef`'s `backend: null`
leniency (`#lzblobbackendstrict`), which the schema rejects.

### Rust union lowering (`#lzwiremodel7`)

A surface with a union takes a separate Rust path; receipts keep theirs byte
for byte. The plan (flattened record payloads, `external`, reachability) is the
Python backend's.

- **A union is an `enum`** in schema order, which is also the Postcard variant
  index. A record payload flattens into a struct variant
  (`DeltaOp::CellSet { node, payload }`), any other payload is a tuple variant
  (`IpcValue::Inline(Vec<u8>)`), and a unit variant stays a unit
  (`NodeState::Opaque`). That is the shape lazily-rs's hand-written IPC types
  already had, so constructors, `filter_readable`, `is_queue_op` and
  `Delta::next` / `Delta::new` stay hand-written `impl` blocks in `ipc.rs`.
  Rust needs no `variant_fields`, and the target refuses one.
- **`external`** maps a type to the Rust path it is imported from
  (`"NodeId": "crate::distributed::NodeId"`, `"NodeKey": "super::NodeKey"`).
  Every alias must be external: lazily-rs's `NodeId` is a newtype and
  `NodeKey` validates its bounds on decode.
- **Codec-aware optional fields** (`"codec_aware_optional": true`). lazily-rs
  omits an absent `NodeAdd.key` in self-describing codecs (JSON, and msgpack,
  whose encoder sets `with_human_readable`) and always writes its option tag in
  positional Postcard, whose schema has no field names to omit. serde's derive
  cannot make a field's presence depend on the codec, so a union with an
  optional field derives only `Deserialize` and gets a generated `Serialize`.
  Each arm is what the derive emits for `skip_serializing_if`
  (`serialize_struct_variant` with the field count, then `skip_field`), except
  that the skip is taken only when `serializer.is_human_readable()`:

  ```rust
  let emit_key = key.is_some() || !self_describing;
  let len = 3 + usize::from(emit_key);
  ```

  The decoder is derived: `serde(default)` on the `Option` reads an omitted key
  and an explicit `null` as `None` in the self-describing codecs, and Postcard
  reads the option tag positionally. Without the option the backend refuses an
  optional field, because the derive's `skip_serializing_if` would drop the
  field from Postcard and misalign every field after it.
- **Strict keys.** Struct variants and records carry `deny_unknown_fields`.

Encoding is unchanged byte for byte: twelve frames covering every `DeltaOp`
variant, every `IpcValue` and `NodeState` form, and a keyed and an unkeyed
`NodeAdd` encode identically through JSON, json-intern, msgpack and Postcard
before and after the lowering. Decoding is unchanged except for unknown keys,
measured against lazily-rs `main` before the change:

| Frame | Before (JSON and msgpack) | After |
|---|---|---|
| unknown key in an op body (`{"Invalidate": {"node": 1, "extra": 2}}`) | accepted, key ignored | refused, `unknown field` |
| unknown key in a `NodeAdd` body | accepted, key ignored | refused |
| unknown key in `Delta` | accepted, key ignored | refused |
| `key: null`, `key` omitted | `None` | `None` |
| missing `node`, missing or `null` `ops`, unknown tag | refused | refused |
| an op body or `Delta` as a positional array (`{"Invalidate": [1]}`) | accepted | accepted |

The last row is serde's derive, which reads a struct from a sequence in any
codec; Python and Go refuse it. It is not schema-valid, and the generated
decoder keeps it because Postcard needs the sequence path.

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

- a `$ref` outside the same schema and `defs.json`, or a name declared in both;
- a root that declares a wire shape (`properties`, `oneOf`, ...) without
  `x-lazily-envelope`, and a schema that yields no declarations at all (before
  `#lzwiremodel4` such a root was skipped silently, so `signaling.json`
  "modelled" as zero types);
- an integer without `minimum: 0`, or with a `maximum` other than u64's;
- in Python, a union payload that is neither a flattenable record nor named in
  `variant_fields`, a flattened body also used as a field type, or an optional
  field before a required one;
- an open object;
- a declaration without a `description`;
- an enum value without an `x-lazily-enum-docs` entry;
- a wire name that does not lower to an identifier.

## Checks

| Command | What it proves |
|---|---|
| `test_delta_model_agrees_with_schema_on_every_corpus_frame` | A strict reading of the model and the JSON Schema validator give the same verdict on every `{"Delta": ...}` frame in the conformance corpus (21) and on single-edit perturbations of each (338 candidates, 35 schema-valid). Mutation-checked: dropping `pattern` from the model, or widening `bytes` to a u64 list, each produces a disagreement. |
| `make wire-codegen-check` | The golden model matches the schemas, and every present sibling's generated file matches backend output byte for byte. Absent siblings are reported as `staged`. |
| `make wire-codegen` | Regenerates the golden model and every present sibling's file. Commit each repository's result alongside the schema edit. |
| CI (`coverage` job) | Same check with `--require-all` against the published `main` of every participating binding. |

Push binding changes before the lazily-spec change. lazily-spec CI checks the
bindings' published `main`.

## Surfaces

| Surface | Schema | Bindings |
|---|---|---|
| `receipts` | `schemas/receipts.json` | lazily-rs `src/generated/receipts.rs`, lazily-go `receipts_wire_gen.go`, lazily-py `src/lazily/_receipts_wire_gen.py`, lazily-kt `src/main/kotlin/io/github/lazily/ReceiptsWireGen.kt` |
| `delta` | `schemas/delta.json` | lazily-rs `src/generated/delta.rs` (`DeltaOp` with its codec-aware `Serialize`, `IpcValue`, `NodeState`, `Delta`; `NodeId`, `NodeKey` and `ShmBlobRef` stay hand-written in `distributed.rs` / `ipc.rs`), lazily-py `src/lazily/_delta_wire_gen.py` (`DeltaOp`, `IpcValue`, `NodeState`, `Delta`, `NodeId`; `NodeKey` and `ShmBlobRef` stay hand-written in `_wire_scalars.py`), lazily-go `delta_wire_gen.go` (`DeltaOp`, `IpcValue`, `NodeState`, `Delta`; `NodeId`/`Epoch` stay `int64` in `types.go`, `NodeKey` and `ShmBlobRef` stay hand-written in `ipc.go`) |

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

`delta` is the second surface, lowered into lazily-py. Modelling it
needed more than multi-variant unions: shared `defs.json` references, scalar
aliases, byte arrays, a named inline enum with a default, and unit variants.
It also found a family-wide gap. `protocol.md` makes `QueuePush` / `QueuePop`
/ `QueueClose` ordinary `DeltaOp` variants, but only lazily-cs decoded them,
and the round-trip fixtures carried only the seven graph ops. `#lzdeltaqueueops`
added the three ops to the `Delta` scenario of both `codec/frame_roundtrip_*`
fixtures and to every binding with an IPC codec (lazily-gd has none).

lazily-py's delta lowering (`#lzwiremodel5`) is the first surface where the
generator removes more hand-written code than its backend adds:

- **Removed:** about 440 hand-written lines of `DeltaOp` / `IpcValue` /
  `NodeState` / `Delta` declarations and codecs from `ipc.py`; 171 lines of
  constructors, read filtering and the epoch decision moved to
  `_delta_semantics.py`.
- **Added:** about 360 lines of Python backend (unions, aliases, bytes,
  optional fields, `external`), against 579 generated lines.
- **Stricter, in the `ValueError` family every decode already raises:**
  unknown keys, a missing `ops` list, a non-integer or out-of-range node id or
  epoch, a byte outside 0..=255, a base64 string where bytes belong, and the
  dict form `{"Opaque": ...}` of a unit variant are now refused. A missing
  required field used to raise `KeyError`.

`test_generated_python_delta_decoder_agrees_with_schema_on_every_corpus_frame`
executes the generated module (with schema-faithful stand-ins for the two
externals) on every corpus `Delta` frame and 338 single-edit perturbations,
and requires the schema's verdict on each, plus a byte-for-byte re-encode of
every accepted frame (an explicit `key: null` re-encodes omitted).

lazily-go's lowering (`#lzwiremodel6`) removed 408 hand-written lines from
`ipc.go` for 888 generated ones and about 540 lines of Go backend, so in Go the
generator does not yet pay for itself in lines. What lazily-go gained is the
strictness it lacked: its decoder accepted unknown keys, a missing `node`
(decoded as zero), a missing or `null` `ops` list, and negative ids and epochs.
All of those are now refused, and encoding a negative id is an error.

lazily-rs's lowering (`#lzwiremodel7`) removed 339 hand-written lines from
`ipc.rs` (the `DeltaOp` declaration, its two borrowed `Serialize` shadows and
`Deserialize` shadow, `Delta`, `IpcValue`, `NodeState`) and added 9 lines to
include the generated module, for 219 generated lines and about 200 lines of
Rust backend. Unlike Go, lazily-rs's decoder was already range-exact
(`u64`-wide ids, `0..=255` bytes), so its only new strictness is unknown keys.

The remaining bindings are harder, for reasons the model records but their
backends do not handle yet:

- **Decoder leniency beyond the schema.** `backend: null` is schema-invalid,
  but `protocol.md` requires decoders to read it as `shm`
  (`#lzblobbackendstrict`). Python, Go and Rust keep `ShmBlobRef` `external`
  for that.
- **Unions in Kotlin.** Kotlin needs a union lowering (a sealed hierarchy).
  Kotlin types `NodeId` as `Long`, which the Go `int64` option now covers: a
  Kotlin equivalent would avoid the `ULong` migration receipts' `generation`
  needed.

The other candidates still do not model:

| Schema | First blocker |
|---|---|
| `reliable-sync.json` | a single-key PascalCase wrapper declared as a record (`ResyncRequest`), not as a `oneOf` union |
| `message-passing.json` | enum values without `x-lazily-enum-docs` (`DedupePolicy`) |
| `snapshot.json` | declarations without a `description` |
| `distributed.json` | a `$defs` entry that is only a `$ref` (`NodeId` re-exported from `defs.json`) |

lazily-js is the remaining large binding on receipts. Its codec lives in the
`index.js` monolith beside a hand-written `index.d.ts`, so a js backend must
generate both and split the module, which costs more than the Kotlin backend
did.
