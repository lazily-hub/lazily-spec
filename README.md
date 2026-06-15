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

## Formal Model

`formal/lean` contains a small Lean 4 Lake package for the IPC Snapshot/Delta
state machine. It proves the epoch sequencing, fail-closed resync,
PartialEq/memo suppression, batch coalescing, and eager Signal `slot_value`
invariants that all bindings share.

Verify it with the local check target:

```bash
make check
```

## Relationship to lazily-rs SPEC.md

This repo extracts the wire-protocol and cross-language compatibility sections from `lazily-rs/SPEC.md` into a standalone reference. Rust-specific internals (Context, ThreadSafeContext, lock strategy, benchmarks) remain in the Rust crate.

## Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and re-serialize to confirm round-trip fidelity.

**Fixture schema:**

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta",
  "assertions": { "…language-agnostic field checks…" },
  "wire": { "…IpcMessage as serde_json…" }
}
```

**Current fixtures:**

| Fixture | Kind | Description |
|---------|------|-------------|
| `snapshot_minimal.json` | Snapshot | One payload node, no edges |
| `snapshot_multi_node.json` | Snapshot | Multiple nodes and edges |
| `snapshot_shared_blob.json` | Snapshot | SharedBlob node state |
| `delta_sequential.json` | Delta | All 7 DeltaOp variants, sequential |
| `delta_non_sequential.json` | Delta | Non-sequential delta with gap |
| `delta_shared_blob.json` | Delta | CellSet/SlotValue with SharedBlob |

**Adding a new binding:** Copy the fixture-loading pattern from `lazily-rs/tests/conformance.rs`. Each test should (1) load the fixture, (2) parse the `wire` field into the binding's native `IpcMessage` type, (3) assert the `assertions` fields, (4) re-serialize and compare.

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges `{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version bump is a breaking change; minor additions are additive.
