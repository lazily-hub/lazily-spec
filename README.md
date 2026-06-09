# lazily-spec

Language-agnostic wire protocol specification for the **lazily** reactive signals family.

This repo defines the canonical message schemas shared across all lazily implementations:

- **lazily-rs** (Rust)
- **lazily-py** (Python)
- **lazily-zig** (Zig)
- **@lazily/signaling** (TypeScript / Cloudflare Worker)

## Protocol Layers

| Layer | Spec | Schema |
|-------|------|--------|
| IPC (Snapshot + Delta) | [protocol.md](protocol.md) § IPC | [schemas/snapshot.json](schemas/snapshot.json), [schemas/delta-op.json](schemas/delta-op.json) |
| Cross-language FFI | [protocol.md](protocol.md) § FFI | [schemas/ffi.json](schemas/ffi.json) |
| Signaling (WebSocket) | [protocol.md](protocol.md) § Signaling | [schemas/signaling.json](schemas/signaling.json) |
| Distributed (CRDT) | [protocol.md](protocol.md) § Distributed | [schemas/distributed.json](schemas/distributed.json) |
| Capability negotiation | [protocol.md](protocol.md) § Capability Negotiation | inline |

## Wire Format

All messages use **JSON** with `serde`-compatible tagging (`"type"` discriminant). Future binary codecs (bincode, postcard, protobuf) encode the same schemas — the JSON representation is normative.

## Schema Format

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate against these schemas.

## Relationship to lazily-rs SPEC.md

This repo extracts the wire-protocol and cross-language compatibility sections from `lazily-rs/SPEC.md` into a standalone reference. Rust-specific internals (Context, ThreadSafeContext, lock strategy, benchmarks) remain in the Rust crate.

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges `{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version bump is a breaking change; minor additions are additive.
