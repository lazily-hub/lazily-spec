# lazily-spec

Language-agnostic wire protocol specification for the **lazily** reactive signals family.

This site is the rendered companion to the [lazily-spec](https://github.com/lazily-hub/lazily-spec)
repository. It defines the canonical message schemas shared across every lazily implementation:

- **lazily-rs** (Rust)
- **lazily-py** (Python)
- **lazily-zig** (Zig)
- **@lazily/signaling** (TypeScript / Cloudflare Worker)

## Cell Model

Upstream of every transport, the [Cell Model](cell-model.md) fixes how a cell's value
converges. A cell is either **single-writer** (`local`/`direct`, no merge) or
**multi-write**, and a multi-write cell carries a pluggable `merge: <mechanism>`
attribute. **CRDT is the first multi-write merge mechanism** (`merge: crdt`), not the
only one — `lww`, `ot`, `lease`, and `custom` are reserved alongside it. All transports
below carry cells classified by this model.

## Protocol Layers

| Layer | Spec | Schema |
|-------|------|--------|
| IPC (Snapshot + Delta) | [Wire Protocol § IPC](protocol.md) | [snapshot.json](schemas.md), [delta.json](schemas.md) |
| Cross-language FFI | [Wire Protocol § FFI](protocol.md) | [ffi.json](schemas.md) |
| Signaling (WebSocket) | [Wire Protocol § Signaling](protocol.md) | [signaling.json](schemas.md) |
| Distributed (CRDT) | [Wire Protocol § Distributed](protocol.md) | [distributed.json](schemas.md) |
| Capability negotiation | [Wire Protocol § Capability Negotiation](protocol.md) | inline |

## Wire Format

All messages use **JSON** with `serde`-compatible tagging (`"type"` discriminant). Future
binary codecs (bincode, postcard, protobuf) encode the same schemas — the JSON representation
is normative.

## Schema Format

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate
against these schemas. See [JSON Schemas](schemas.md).

## Relationship to lazily-rs SPEC.md

This repo extracts the wire-protocol and cross-language compatibility sections from
`lazily-rs/SPEC.md` into a standalone reference. Rust-specific internals (Context,
ThreadSafeContext, lock strategy, benchmarks) remain in the Rust crate.

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges
`{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version
bump is a breaking change; minor additions are additive.
