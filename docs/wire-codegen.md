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
 (normative)        (golden, committed)        (rust, go)             (committed in the binding)
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

| Kind | Schema shape | Rust | Go |
|---|---|---|---|
| `string` | `"type": "string"` | `String` | `string` |
| `u64` | `"type": "integer", "minimum": 0` | `u64` | `uint64` |
| `bool` | `"type": "boolean"` | `bool` | `bool` |
| `list` | `"type": "array"` + `items` | `Vec<T>` | `[]T` (marshals `[]`, never `null`) |
| `nullable` | `oneOf: [null, T]` (inline or a `$defs` alias) | `Option<T>` | `*T` |
| `ref` | local `#/$defs/X` record or enum | `X` | `X` |
| `enum` | string `enum` + `x-lazily-enum-docs` | `enum`, `rename_all = "snake_case"` when every value round-trips | string type, constants, `…FromWire`, rejecting `UnmarshalJSON` |
| `record` | closed object (`additionalProperties: false`) | `struct` with optional serde derives | `struct` + `…FromWire` |
| `envelope` | root `x-lazily-envelope`, externally tagged | single-variant `enum` | not lowered (callers decode the tagged body) |

A field's *presence* is modelled separately from its type: a `required` +
`nullable` field is always on the wire and is `null` when absent, while an
`optional` field may be missing. Open enums and optional fields are already
modelled, but no backend lowers them yet, so the backends refuse them.

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
| `receipts` | `schemas/receipts.json` | lazily-rs `src/generated/receipts.rs`, lazily-go `receipts_wire_gen.go` |

Lowering the receipts surface found one real wire mismatch. Go had
`generation` as `int64`, which accepts negative values that the schema
forbids. Go now decodes it as `uint64`. The command plane keeps its `int64`
generations and compares the two without wrapping either side.
