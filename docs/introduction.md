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

Every layer in this matrix is **required of every binding**. The **Distributed CRDT**
row and the required [keyed cell collections](cell-model.md#keyed-cell-collections) layer
are unconditional. The **C-ABI FFI** row is required by default with a narrow platform
carve-out (a binding whose runtime cannot host a native in-process C ABI — e.g.
browser/Worker JS — declares `ffi = none` and interops over the wire instead). See the
[Binding Conformance Matrix](protocol.md#binding-conformance-matrix) for the full
MUST/MAY breakdown and the carve-out terms.

## Wire Format

All messages use **JSON** with `serde`-compatible tagging (`"type"` discriminant). Future
binary codecs (bincode, postcard, protobuf) encode the same schemas — the JSON representation
is normative.

## Schema Format

Schemas are provided as **JSON Schema (Draft 2020-12)**. Each implementation must validate
against these schemas. See [JSON Schemas](schemas.md).

## Scope & non-goals

This repo extracts the cross-language, wire-protocol, and behavioral sections
from `lazily-rs/SPEC.md` into a standalone reference. Every lazily-rs feature
area is accounted for here exactly once: either normatively specified (with a
link below) or explicitly marked Rust-specific. Rust-specific internals remain
in the Rust crate and are intentionally out of scope.

### Covered (normative, cross-language)

| lazily-rs area | Spec |
|----------------|------|
| Cell / Slot / Effect / Signal (reactive core) | [Reactive Graph](reactive-graph.md), [Cell Model](cell-model.md), [Wire Protocol § Eager Signals](protocol.md#eager-signal-nodes) |
| `CellFamily` / `CellMap` (keyed collections) | [Cell Model § Keyed cell collections](cell-model.md#keyed-cell-collections) |
| `CellTree` (ordered keyed tree) | [Cell Model § Ordered keyed tree](cell-model.md#ordered-keyed-tree) |
| `reconcile` (LIS keyed reconciliation) | [Cell Model § Keyed reconciliation](cell-model.md#keyed-reconciliation) |
| `SemTree` (memoized semantic tree) | [Cell Model § Memoized semantic tree](cell-model.md#memoized-semantic-tree) |
| `stable_id` (manufactured text identity) | [Cell Model § Manufactured identity](cell-model.md#manufactured-identity-for-text) |
| `TextCrdt` (free-text CRDT + re-parse) | [Cell Model § Free-text CRDT](cell-model.md#free-text-crdt--re-parse) |
| `SeqCrdt` (move-aware sequence order) | [Cell Model § Move-aware sequence order](cell-model.md#move-aware-sequence-order) |
| Tombstone GC | [Cell Model § Tombstone garbage collection](cell-model.md#tombstone-garbage-collection) |
| `StateMachine` (flat FSM) | [State Machine](state-machine.md) |
| `StateChart` (Harel/SCXML) | [State Charts](state-charts.md) |
| `AsyncContext` (async reactive graph) | [Async Reactive Context](async.md) |
| IPC Snapshot/Delta + `ShmBlobArena` | [Wire Protocol § IPC](protocol.md#ipc-snapshot--incremental-update-protocol), [Conformance Fixtures](conformance.md) |
| FFI boundary | [Wire Protocol § FFI](protocol.md#ffi-boundary), [`ffi.json`](schemas.md#ffijson) |
| Signaling (WebSocket) | [Wire Protocol § Signaling](protocol.md#signaling-protocol-websocket), [`signaling.json`](schemas.md#signalingjson) |
| Distributed CRDT plane (`CrdtSync`/`WireStamp`) | [Wire Protocol § Distributed](protocol.md#distributed-crdt-cell-plane), [`distributed.json`](schemas.md#distributedjson) |
| Permission boundary (`RemoteOp`/`PeerPermissions`) | [Wire Protocol § Permission Boundary](protocol.md#permission-boundary-remoteop) |
| Capability negotiation | [Wire Protocol § Capability Negotiation](protocol.md#capability-negotiation) |
| Transport abstraction (`IpcSink`/`IpcSource`/`DataChannel`) | [Wire Protocol § Cross-language channels](protocol.md#cross-language-channel-compatibility) |

### Out of scope (Rust-specific implementation)

These lazily-rs features are implementation choices, not cross-language
contracts. Other bindings pick their own; they MUST meet the normative contracts
above but need not mirror Rust's approach.

| lazily-rs area | Why out of scope |
|----------------|------------------|
| `Context` / `ThreadSafeContext` lock strategy (`ReadStrategy`, inline seqlock, typed cache fast-path) | Internal scheduling/locking; each binding picks its own concurrency strategy |
| `SlotId` internal representation | Volatile internal handle; the wire-stable identity is [`NodeId`](protocol.md#nodeid--peerid) / [`NodeKey`](protocol.md#nodekey) |
| `instrumentation` (lock-site tracking) | Rust diagnostics |
| `str0m_backend` / `str0m_net` | Concrete Rust WebRTC backend (`str0m` crate); only the transport [abstraction](protocol.md#cross-language-channel-compatibility) is cross-language |
| Performance benchmarks | Rust-specific measurement |
| `lazily-serde` type-erasure internals | Rust serialization approach; the [wire shape](schemas.md), not the codec implementation, is normative |

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges
`{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version
bump is a breaking change; minor additions are additive.
