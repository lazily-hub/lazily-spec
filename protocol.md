# lazily Wire Protocol Specification

Normative source of truth for all lazily language bindings.

## Shared Types

### NodeId / PeerId

```
NodeId = u64
PeerId = u64
```

Wire-stable identifiers decoupled from internal `SlotId`. Serialized as bare JSON numbers. JavaScript/TypeScript peers must keep values at or below `Number.MAX_SAFE_INTEGER` (2^53).

### NodeKey

```
NodeKey = string   // a "/"-joined path, e.g. "scores/alice", "outer/k1/inner/k2"
```

An **optional, wire-stable keyed address** for a collection entry (a `CellMap` / `CellFamily` entry). Unlike `NodeId` — the volatile internal handle a producer may re-mint after a resync or remove-then-readd — a `NodeKey` is producer-defined and **stable across NodeId churn**, so a peer can subscribe to "entry `scores/alice`" without an out-of-band key→NodeId map. A multi-segment path addresses nested collections (an entry of a `CellMap` inside a `CellMap` entry) with no extra machinery.

`NodeKey` is **additive** — it never changes `NodeId` semantics. It appears only as the optional `key` field on `NodeSnapshot` and the `NodeAdd` delta op.

Bounds (reject on construction and on the wire): path ≤ 1024 bytes; ≤ 32 `/`-separated segments; empty path and empty segments (leading/trailing/double `/`) are rejected.

**Serialization is format-aware.** Self-describing codecs (JSON, MessagePack) **omit** the `key` field when absent, so pre-`key` encoders/decoders and existing conformance fixtures round-trip unchanged; positional Postcard always carries the optional discriminant for binary schema stability. A decoder that sees no `key` field treats it as absent (`null`). Cross-language implementations (lazily-py, lazily-zig, lazily-js, lazily-kt, lazily-go) add the optional nullable `key` field; they need not emit it when no key is set. Multi-producer key uniqueness (last-writer rule) is owned by the distributed CRDT plane, not this protocol.

### IpcValue (payload)

A `DeltaOp` cell payload is carried as an externally-tagged `IpcValue`:

```
IpcValue = { "Inline": [u8] }           // inline byte array (JSON array of 0..255)
          | { "SharedBlob": ShmBlobRef } // descriptor into a shared-memory arena
```

### NodeState

A `NodeSnapshot` / `NodeAdd` node body is carried as an externally-tagged `NodeState`:

```
NodeState = { "Payload": [u8] }          // concrete serialized value bytes
           | { "SharedBlob": ShmBlobRef } // concrete value in shared memory
           | "Opaque"                      // visible node whose value cannot be serialized
```

Opaque serialized value bytes are owned by the producing language; type-aware decoding is fixed by the stable `type_tag` carried on the node. Over the JSON codec, bytes are transmitted as JSON arrays of integers in `0..255` (not base64).

### type_tag

Each serializable node carries a `type_tag: &'static str` — a stable cross-process key that maps to a language-local deserialization constructor. The type-tag registry is per-implementation; tags must not collide across nodes.

## IPC: Snapshot + Incremental Update Protocol

lazily-IPC transmits a reactive graph's state to a remote observer and keeps it in sync as the graph mutates.

### Two message kinds

- **Snapshot** — full graph state. Sent on connect and on resync.
- **Delta** — incremental change set. Sent **once per outermost batch-flush invalidation pass**.

### Epoch / versioning

A context-level monotonic `ipc_epoch: u64` advances **once per outermost batch flush**, not per write.

- `Snapshot` carries `epoch`.
- Each `Delta` carries `{ base_epoch, epoch }` with `epoch == base_epoch + 1`.
- Deltas are strictly sequential. A receiver detects gaps, reorders, or sender restarts by checking `base_epoch == last_epoch`.

### Snapshot

```json
{
  "Snapshot": {
    "epoch": 1,
    "nodes": [
      { "node": 1, "type_tag": "i32", "state": { "Payload": [1, 2, 3, 4] } }
    ],
    "edges": [
      { "dependent": 2, "dependency": 1 }
    ],
    "roots": [1]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `epoch` | `u64` | Current IPC epoch |
| `nodes` | `NodeSnapshot[]` | All serialized nodes |
| `edges` | `EdgeSnapshot[]` | Dependency edges (dependent → dependency) |
| `roots` | `NodeId[]` | Cell and source slot ids |

#### NodeSnapshot

```json
{ "node": 1, "type_tag": "i32", "state": { "Payload": [1, 2, 3, 4] } }
```

| Field | Type | Description |
|-------|------|-------------|
| `node` | `NodeId (u64)` | Wire-stable node identifier |
| `type_tag` | `string` | Stable cross-process type key for decoding `state` |
| `state` | `NodeState` | `{"Payload":[u8]}` \| `{"SharedBlob":ShmBlobRef}` \| `"Opaque"` |
| `key` | `NodeKey?` | Optional wire-stable keyed address; omitted in JSON/MessagePack when absent |

#### EdgeSnapshot

```json
{ "dependent": 1, "dependency": 0 }
```

### Delta

```json
{
  "Delta": {
    "base_epoch": 40,
    "epoch": 41,
    "ops": [
      { "CellSet":    { "node": 1, "payload": { "Inline": [10] } } },
      { "SlotValue":  { "node": 2, "payload": { "Inline": [20] } } },
      { "Invalidate": { "node": 3 } },
      { "NodeAdd":    { "node": 4, "type_tag": "u64", "state": { "Payload": [64] } } },
      { "NodeRemove": { "node": 5 } },
      { "EdgeAdd":    { "dependent": 2, "dependency": 1 } },
      { "EdgeRemove": { "dependent": 3, "dependency": 1 } }
    ]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `base_epoch` | `u64` | Epoch this delta applies to |
| `epoch` | `u64` | New epoch (`base_epoch + 1`) |
| `ops` | `DeltaOp[]` | Ordered operations |

#### DeltaOp variants

All `DeltaOp`, `IpcValue`, `NodeState`, and `IpcMessage` variants are **externally tagged**: a single-key JSON object whose key is the PascalCase variant name and whose value is the body (or a bare `"Opaque"` / unit string).

| Op | Body fields | Description |
|----|-------------|-------------|
| `CellSet` | `node`, `payload: IpcValue` | Changed-value cell write (PartialEq-guarded) |
| `SlotValue` | `node`, `payload: IpcValue` | A recompute published a new value |
| `Invalidate` | `node` | Dirtied, not yet recomputed (lazy) |
| `NodeAdd` | `node`, `type_tag`, `state: NodeState`, `key: NodeKey?` | New node (optional wire-stable `key`, omitted in JSON/MessagePack when absent) |
| `NodeRemove` | `node` | Removed node (free-list reuse: Remove then Add) |
| `EdgeAdd` | `dependent`, `dependency` | New dependency edge |
| `EdgeRemove` | `dependent`, `dependency` | Removed dependency edge |

### Consistency invariants

- **PartialEq cell guard**: An equal `set_cell` emits no `CellSet` and no downstream ops.
- **Memo equality suppression**: A dirty `memo()` that recomputes to an equal value emits no `SlotValue` and no downstream `Invalidate`.
- **Coalesced frontier**: A dependent reached through many changed cells in one batch appears at most once per delta.
- **Eager Signal values are concrete**: A changed eager Signal emits a concrete
  `SlotValue` for its backing slot, not a bare `Invalidate`.

The companion Lean model in `formal/lean` encodes these IPC transition rules and
checks them with `lake build`.

### Eager Signal nodes

A `Signal` is the eager derived value in the `Slot -> Cell -> Signal` family. It
is not a separate wire type. A Signal is represented by the ordinary backing
slot node that stores its materialized value:

- **Snapshot**: the backing slot appears as a `NodeSnapshot` with a concrete
  `payload`/shared-blob payload like any other readable slot.
- **Delta**: a value change appears as `SlotValue` for the backing slot's
  `NodeId`. Because the value is recomputed during the invalidation flush, eager
  Signals do not emit bare `Invalidate` ops for their own changed value.
- **Memo guard**: an eager recompute that yields an equal value suppresses
  `SlotValue` and downstream invalidation exactly like a lazy memoized slot.
- **Local puller**: the producer-side effect that keeps the Signal eager is local
  execution state and is not serialized as a graph node.

Consumers therefore need no protocol extension to read eager Signals from a
producer. They observe the same permission-filtered `Snapshot`/`Delta` state
plane and see Signals as slots whose changed values are reliably materialized.

### Lazy reconciliation

- **Value-mirror (default)**: At flush, the sender resolves each invalidated allowlisted slot so the delta carries concrete `SlotValue`s. The receiver holds no compute closures.
- **Mirror-lazy**: The sender emits bare `Invalidate`; the receiver keeps a stale marker. Requires compute closure replication. Deferred to `lazily-distributed`.

> **Wire shape.** The value-mirror default means an allowlisted dirty slot
> appears in a flush `Delta` as a concrete `SlotValue`, never a bare
> `Invalidate` (the latter is the mirror-lazy form). This invariant — and the
> eager-Signal rule that a changed Signal publishes a `SlotValue` for its backing
> slot, not an `Invalidate` — is pinned by the IPC fixtures
> [`delta_sequential.json`](conformance/delta_sequential.json) and
> [`delta_shared_blob.json`](conformance/delta_shared_blob.json), both of which
> carry `SlotValue` ops for resolved slots.

### Resync / gap handling

On a `Delta` whose `base_epoch != last_epoch`:
1. Receiver discards the delta.
2. Receiver requests a fresh `Snapshot`.
3. Sender replies with `Snapshot { epoch }`.
4. Deltas resume from the new epoch.

Messages are length-prefixed and tagged `Snapshot` / `Delta`. The protocol is transport-agnostic (unix socket, pipe, WebSocket, shared memory).

### Shared-memory IPC

`ShmBlobArena` provides the shared-memory payload path (a **required** layer wherever the
platform supports it — see [§ Shared-memory payload path is required](#shared-memory-payload-path-is-required)):
- Arena writes a fixed header before each payload: `{ generation, epoch, length, checksum }`.
- Readers validate the header before accepting a descriptor.
- `IpcMessage` control frames carry `ShmBlobRef` descriptors instead of embedding large bytes inline.

Shared memory carries large blob payloads; ordinary control transport carries framed `IpcMessage`s. Each process keeps its own local `Context` / `ThreadSafeContext` and reconciles via snapshots and deltas. A binding whose platform cannot host a shared-memory arena carries every large payload `Inline` over the control transport (IPC / WebSocket / WebRTC) — the I/O channel accesses the memory directly, so the peer still receives the bytes without a shared-memory descriptor.

## Capability Negotiation

Each non-local session starts with a compatibility handshake:

```json
{
  "protocol_id": "lazily-ipc",
  "protocol_major_version": 1,
  "codec": "json",
  "max_frame_size": 1048576,
  "fragmentation_supported": false,
  "ordered_reliable": true,
  "peer_id": 1,
  "session_id": "abc-123",
  "features": ["shared-blob", "signaling-relay"]
}
```

| Field | Description |
|-------|-------------|
| `protocol_id` | Must be `"lazily-ipc"` |
| `protocol_major_version` | Breaking change indicator |
| `codec` | `"json"` (default); future: `"bincode"`, `"postcard"` |
| `max_frame_size` | Maximum frame size in bytes |
| `fragmentation_supported` | Whether frame fragmentation is supported |
| `ordered_reliable` | Delivery guarantee requirement |
| `peer_id` | `PeerId` for this session |
| `session_id` | Session/graph identifier |
| `features` | Supported feature flags |

If peers disagree on `protocol_major_version`, `codec`, `ordered_reliable`, or required features, they fail closed before applying any `Snapshot` or `Delta`.

## Causal Receipts

Some integrations send a command or publish an effectful request and need a durable, queryable outcome for that causation id. lazily supplies a generic **causal receipt** primitive for that use case; it is not a transport ACK and does not make delivery success authoritative.

```json
{
  "CausalReceipts": {
    "receipts": [
      {
        "receipt_id": "receipt-1",
        "causation_id": "patch-123",
        "observer": "editor",
        "generation": 7,
        "outcome": "applied",
        "reason": null,
        "payload_hash": "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
      }
    ]
  }
}
```

| Field | Description |
|-------|-------------|
| `receipt_id` | Idempotency key for this receipt event. Duplicate `receipt_id`s are no-ops. |
| `causation_id` | Stable id of the command, event, or effect request the receipt observes. |
| `observer` | Peer, process, or subsystem that produced the receipt. |
| `generation` | Monotonic producer/editor generation. Consumers discard receipts whose generation does not match the current authority generation for the causation id. |
| `outcome` | `"observed"`, `"accepted"`, `"applied"`, or `"rejected"`. |
| `reason` | Optional human/debug rejection reason; `null` when absent. |
| `payload_hash` | Optional hash of the state/payload the receipt observed; `null` when absent. |

Receipt projection rules:

- `observed` and `accepted` are **non-terminal**. They may model ACK-like transport or queue admission observations, but a domain MUST NOT treat them as proof that an effect happened.
- `applied` and `rejected` are **terminal**. They are the generic outcome vocabulary that domain-specific facts refine (for example an editor may publish `EditorPatchApplied` / `EditorPatchRejected` facts keyed by the same `causation_id`).
- A stale-generation receipt is ignored by the current projection and may be retained only as audit/debug data.
- A second terminal receipt for the same `causation_id` and generation with a different terminal outcome is a terminal conflict; consumers fail closed instead of selecting a winner.
- The primitive is state/projection data. Transports may still provide their own delivery acknowledgements internally, but lazily does not expose delivery ACKs as authority.

## Cross-language Channel Compatibility

All channels carry the same `IpcMessage` state plane:

| Channel | Strategy |
|---------|----------|
| FFI | C ABI: opaque context/session handles + owned byte buffers |
| IPC | Unix sockets, pipes, local TCP: length-prefixed serialized `IpcMessage` |
| WebSocket | One WebSocket frame = one serialized `IpcMessage` |
| WebRTC data | Reliable ordered data channels carry serialized `IpcMessage` |

### Cross-language rules

- Compute closures are language-local. Cross-language sync shares the cell state plane.
- Permission filtering happens before serialization on every channel.
- Back-pressure: if frames gap, reorder, or truncate, the receiver requests a fresh `Snapshot`.

## Binding Conformance Matrix

A lazily **binding** is a language port that intends to interoperate with the wider lazily
ecosystem (lazily-rs, lazily-py, lazily-zig, lazily-js, lazily-kt, lazily-dart, lazily-go, …). The
layers below are **required of every binding**; none is an optional lazily-rs extension.
A binding that omits a `MUST` row is non-conforming and MUST advertise its missing surface
via [Capability Negotiation](#capability-negotiation) rather than failing silently.

| Layer | Required | Spec | Conformance |
|-------|----------|------|-------------|
| Reactive core (Cell / Slot / Effect / Signal) | MUST | [Reactive Graph](reactive-graph.md), [Cell Model](cell-model.md) | — |
| **Keyed cell collections** (`CellMap`, `CellTree`, keyed reconciliation) | MUST | [Cell Model § Keyed cell collections](cell-model.md#keyed-cell-collections) | [`conformance/collections/`](conformance/collections/) |
| Flat state machine | MUST | [State Machine](state-machine.md) | — |
| Harel state charts | MUST | [State Charts](state-charts.md) | [`conformance/statechart/`](conformance/statechart/) |
| Thread-safe reactive context | MUST² | [Reactive Graph § Context layers](reactive-graph.md#context-layers) | — |
| Async reactive context | MUST² | [Async Reactive Context](async.md) | — |
| IPC (`Snapshot` + `Delta`) | MUST | [§ IPC](#ipc-snapshot--incremental-update-protocol) | [`conformance/`](conformance/) IPC fixtures |
| **Shared-memory payload path** (`ShmBlobArena` / `ShmBlobRef`) | MUST³ | [§ Shared-memory IPC](#shared-memory-ipc) | [`conformance/`](conformance/) shared-blob fixtures (`snapshot_shared_blob`, `delta_shared_blob`) |
| **C-ABI FFI boundary** (`LazilyFfiBytes`, `LazilyFfiStatus`, `LazilyFfiMessageKind`) | MUST¹ | [§ FFI Boundary](#ffi-boundary), [`ffi.json`](schemas.md#ffijson) | every binding decodes the FFI frame to `IpcMessage` and re-encodes canonical JSON bytes |
| **Distributed CRDT plane** (`CrdtSync` / `WireStamp`) | MUST | [§ Distributed: CRDT Cell Plane](#distributed-crdt-cell-plane), [`distributed.json`](schemas.md#distributedjson) | [`conformance/`](conformance/) `CrdtSync` round-trip |
| **Causal receipts** (`CausalReceipt`, terminal outcome projection) | MUST | [§ Causal Receipts](#causal-receipts), [`receipts.json`](schemas.md#receiptsjson) | [`conformance/receipts/causal_receipts.json`](conformance/receipts/causal_receipts.json) |
| Permission boundary (`RemoteOp` / `PeerPermissions`) | MUST | [§ Permission Boundary](#permission-boundary-remoteop) | — |
| Capability negotiation | MUST | [§ Capability Negotiation](#capability-negotiation) | — |
| Signaling (WebSocket) | MAY | [§ Signaling](#signaling-protocol-websocket) | only for bindings that bridge browser/runtime peers |
| WebRTC data transport | MAY | [§ Cross-language channels](#cross-language-channel-compatibility) | only for bindings that peer over WebRTC |

> ¹ C-ABI FFI has a **platform carve-out** — see [§ C-ABI FFI is required](#c-abi-ffi-is-required).
> ² The thread-safe and async context layers have a **platform carve-out** — see [§ Concurrency layers are required](#concurrency-layers-are-required).
> ³ The shared-memory payload path has a **platform carve-out** (I/O-channel fallback) — see [§ Shared-memory payload path is required](#shared-memory-payload-path-is-required).
> CRDT and the keyed cell collections have **no carve-out**: they are wire/logic
> properties implementable on any runtime that speaks the wire.

### C-ABI FFI is required

Every binding whose platform can host a native in-process boundary MUST expose and consume
the [C-ABI FFI boundary](#ffi-boundary): the `LazilyFfiBytes` / `LazilyFfiStatus` /
`LazilyFfiMessageKind` contract with explicit allocation ownership, panics caught before
crossing the C ABI, and a channel that decodes each accepted frame as `IpcMessage` and
re-encodes canonical JSON bytes. The FFI message kind discriminant MUST include
`CrdtSync = 3`. This is the lingua franca that lets any binding embed any other without a
language-specific bridge.

**Platform carve-out.** A binding whose runtime structurally cannot host a native C ABI
declares the `ffi` capability as `none`; otherwise it declares `host`. `none` is reserved
for platforms with no shared in-process address space (for example browser/Worker JS, or a
fully-sandboxed runtime) — a binding MAY NOT declare `none` merely because FFI is
inconvenient or unimplemented. This is a binding-level conformance declaration (advertised
in the binding's conformance statement and discoverable at build/link time), not a
per-session wire flag, since in-process embedding is not a runtime session.

A `ffi = none` binding:
- conforms to the **interop** contract but not the **in-process embedding** contract, and
  MUST NOT advertise itself as embeddable;
- MUST still expose the full state plane — including `CrdtSync` — over
  IPC/WebSocket/WebRTC, so it interoperate without in-process embedding; and
- MUST be treated by peers/host tooling as unable to be loaded in-process (fail closed on
  any attempt to do so, rather than silently degrading).

This reuses the existing fail-closed principle: the limitation is explicit and advertised,
never silent. There is no equivalent carve-out for CRDT or the cell/collections model —
those are implementable on any Turing-complete runtime that speaks the wire.

### CRDT is required

Every binding MUST implement the [`CrdtSync`](#distributed-crdt-cell-plane) plane — the
`merge: crdt` mechanism, the `WireStamp` version-vector frontier, and the
causal-stability watermark / GC contract — and MUST round-trip a `CrdtSync` `IpcMessage`
byte-identically. Multi-write convergence is a property of the cell model, not an
optional distributed extra; a binding that ships only the single-producer
`Snapshot`/`Delta` mirror conforms only to the single-writer subset and MUST downgrade its
advertised capability accordingly.

### Concurrency layers are required

The reactive core ships as three context layers — single-threaded (base), thread-safe
(lock-backed), and async (future-returning) — defined in
[Reactive Graph § Context layers](reactive-graph.md#context-layers) and
[Async Reactive Context](async.md). The single-threaded base context is unconditionally
required of every binding (it is the reactive-core row above). The **thread-safe** and
**async** layers are required **conditionally**: a binding whose platform structurally
supports a layer MUST implement that layer.

**Thread-safe context.** A binding whose platform exposes preemptive multi-threading or
shared-memory concurrency (native threads, OS goroutines, JVM threads, Kotlin
coroutines over a shared heap, etc.) MUST ship the lock-backed context whose handles are
clonable and whose transition function and state are `Send + Sync`, so observers fire
synchronously within the invalidating `send`/`batch` preserving glitch-free pull-based
ordering. A platform with no shared-memory threading model — a strictly single-threaded
runtime, or a process/actor-isolation model (e.g. a Dart isolate, a browser Worker) where
peers do not share an address space — declares the `thread_safe` capability as `none`.

**Async context.** A binding whose platform exposes an async/future runtime (async/await,
promises, coroutines, an executor that suspends and resumes across `.await` points) MUST
ship the [async context](async.md) with its full slot state machine (`Empty` /
`Computing` / `Resolved` / `Error`), revision tracking, five-point cancellation contract,
and `get_async` re-resolve loop. A platform with no notion of suspendable async
computation declares the `async` capability as `none`.

A `none` declaration, for either layer:

- is a **binding-level conformance declaration** (advertised in the binding's conformance
  statement and discoverable at build time), not a per-session wire flag, because
  in-process concurrency structure is not a runtime session;
- MUST be reserved for platforms that **structurally lack** the primitive — a binding MAY
  NOT declare `none` merely because the layer is inconvenient or unimplemented; and
- MUST be advertised rather than fail silently, reusing the existing fail-closed
  principle.

There is no carve-out for the keyed cell collections, the state machine, the state charts,
the reactive core, or CRDT — those are implementable on any Turing-complete runtime that
speaks the wire, single-threaded or not.

### Shared-memory payload path is required

The [shared-memory payload path](#shared-memory-ipc) (`ShmBlobArena` + `ShmBlobRef`
descriptors) is the zero-copy large-payload transport for `IpcValue` and `NodeState`. A
binding whose platform exposes a shared-memory primitive (POSIX `shm` / memory-mapped
files / OS shared memory / a peer-reachable arena) MUST implement it: payloads above the
inline threshold are written into the arena, the control frame carries the `ShmBlobRef`
descriptor, and readers validate the `{ generation, epoch, length, checksum }` header
before accepting it.

**Platform carve-out — I/O-channel fallback.** A binding whose runtime structurally cannot
host a shared-memory arena (browser/Worker JS, a sandboxed runtime, WASM without shared
memory) declares the `shared_memory` capability as `none`. Such a binding MUST fall back
to **I/O channels accessing the memory**: every payload that would have been a
`SharedBlob` descriptor is instead carried `Inline` over the ordinary IPC / WebSocket /
WebRTC transport, so the same `IpcMessage` state plane reaches the peer without a
shared-memory descriptor. The wire format already supports both paths (`IpcValue` and
`NodeState` are externally-tagged `Inline | SharedBlob`); the fallback simply never emits
the `SharedBlob` variant on that binding and treats an absent descriptor as `Inline` on
read.

Shared memory is negotiated **per session** via the `shared-blob` entry in the
[Capability Negotiation](#capability-negotiation) `features` array: two peers that both
advertise `shared-blob` MAY exchange `ShmBlobRef` descriptors; if either peer omits it,
both sides carry payloads `Inline` over the control transport for that session. (The
`thread_safe`, `async`, and `ffi` capabilities, by contrast, are binding-level
declarations — in-process properties — and are not per-session wire flags.)

This reuses the existing fail-closed principle: the limitation is explicit and
advertised, never silent. The shared-blob conformance fixtures
([`snapshot_shared_blob.json`](conformance/) / [`delta_shared_blob.json`](conformance/))
fix the descriptor shape for bindings that ship the arena; an `Inline`-only binding
round-trips the same fixtures with the blob bytes inlined.

## FFI Boundary

### Types

```c
typedef struct {
    uint8_t* ptr;
    size_t   len;
} LazilyFfiBytes;

typedef enum {
    LazilyFfiStatus_Ok            = 0,
    LazilyFfiStatus_Empty         = 1,
    LazilyFfiStatus_NullPointer   = 2,
    LazilyFfiStatus_InvalidMessage = 3,
    LazilyFfiStatus_EncodeFailed  = 4,
    LazilyFfiStatus_Panic         = 5,
} LazilyFfiStatus;

typedef enum {
    LazilyFfiMessageKind_Unknown  = 0,
    LazilyFfiMessageKind_Snapshot = 1,
    LazilyFfiMessageKind_Delta    = 2,
} LazilyFfiMessageKind;
```

### Contract

- All allocation ownership is explicit: caller owns input bytes; Rust owns output buffers until the paired free function is called.
- Errors return `LazilyFfiStatus`; panics are caught before crossing the C ABI.
- The channel decodes each accepted frame as `IpcMessage`, then re-encodes canonical JSON bytes.

## Signaling Protocol (WebSocket)

### Client → Server

| Type | Fields | Description |
|------|--------|-------------|
| `join` | `peer`, `capabilities?` | Register with session |
| `offer` | `to`, `sdp` | WebRTC SDP offer |
| `answer` | `to`, `sdp` | WebRTC SDP answer |
| `ice` | `to`, `candidate` | ICE candidate |
| `relay` | `to`, `payload` | Relay opaque payload |
| `leave` | — | Disconnect |

### Server → Client

| Type | Fields | Description |
|------|--------|-------------|
| `welcome` | `peer`, `peers` | Roster on join |
| `peer-joined` | `peer` | New peer in session |
| `peer-left` | `peer` | Peer disconnected |
| `offer` | `from`, `sdp` | Forwarded offer |
| `answer` | `from`, `sdp` | Forwarded answer |
| `ice` | `from`, `candidate` | Forwarded ICE |
| `relay` | `from`, `payload` | Forwarded payload |
| `error` | `code`, `message` | Error response |

### Anti-spoofing

The `from` field on every forwarded frame is the sender connection's registered peer id, never client-supplied.

### Example frames

```json
{ "type": "join", "peer": 1 }
{ "type": "welcome", "peer": 1, "peers": [] }
{ "type": "offer", "to": 2, "sdp": "v=0\r\n..." }
{ "type": "answer", "from": 2, "sdp": "v=0\r\n..." }
{ "type": "ice", "from": 2, "candidate": "candidate:..." }
{ "type": "relay", "to": 2, "payload": { "any": "json" } }
{ "type": "peer-joined", "peer": 2 }
{ "type": "leave" }
```

### Permission modes

| Mode | Description |
|------|-------------|
| `open` | Any peer may join and signal any other joined peer |
| `allowlist` | Default-deny: peers require explicit grants; directed frames only to allowed targets |

## Distributed: CRDT Cell Plane

This plane specifies **`merge: crdt`** — the *first* multi-write merge mechanism of the
[Cell Model](cell-model.md#merge-mechanisms). CRDT is one mechanism among several the
cell model reserves (`lww`, `ot`, `lease`, `custom`); it is the first defined because it
converges without coordination. Everything here applies to a multi-write cell that
declares `merge: crdt`; the cell-kind classification, ingress-on-roots-only boundary,
and cell-as-merge-unit granularity are defined once, mechanism-independently, in the
[Cell Model](cell-model.md).

### Cell register types

These are the CRDT-mechanism register types (the value shapes available *within*
`merge: crdt`); they are distinct from the cell-model's `MergeMechanism` axis.



| Type | Merge | Description |
|------|-------|-------------|
| LWW-register | Last-write-wins (HLC timestamp) | Default; "current value" semantics |
| MV-register | Multi-value | Surfaces concurrent writes as a set |
| PN-counter | Additive | Positive-negative counter |

### CRDT properties

- Each replicated cell is keyed by a **hybrid logical clock (HLC)**: wall-clock for human-meaningful ordering, logical counter for causal tiebreak.
- Local **PartialEq invalidation guard** applies *after* merge: equal values invalidate nothing.
- **Memo equality suppression** holds post-merge.
- `lazily-ipc`'s `Delta` generalizes to **per-peer causal stamps**: each peer keeps its own sequence; cross-peer order comes from HLC/dot metadata.

### Anti-entropy wire format (`CrdtSync`)

The plane rides the same `lazily-ipc` transport as `Snapshot`/`Delta`. Alongside the
single-producer mirror, a third `IpcMessage` variant carries multi-writer plane traffic:

```
IpcMessage = Snapshot(Snapshot) | Delta(Delta) | CrdtSync(CrdtSync)

WireStamp = { wall_time: u64, logical: u64, peer: u64 }   # total order (wall, logical, peer)

CrdtOp = {
  node:  NodeId,           # volatile target id
  key:   NodeKey?,         # optional wire-stable address (survives NodeId churn, #lzwirekey)
  stamp: WireStamp,        # the HLC stamp that produced this state
  state: IpcValue,         # the converged CRDT state to merge (state-based / CvRDT)
}

CrdtSync = {
  frontier: [(peer: u64, WireStamp)],   # the sender's per-peer stamp frontier
  ops:      [CrdtOp],                    # the op batch this frame ships
}
```

`WireStamp` is the wire mirror of the runtime HLC stamp (all plain integers), so the wire
format is codec-stable whether or not a peer compiles the CRDT runtime in. It round-trips
across all three codecs (JSON, MessagePack, postcard) and is classified by the FFI message
kind (`CrdtSync = 3`).

**State-based, idempotent.** Each `CrdtOp` ships the *converged* register/sequence/text
state for a node. The receiver merges `state` into its local replica; because every cell
CRDT merge is commutative, associative, and idempotent (proven in
`formal/lean/LazilyFormal/CRDT.lean`, `stampJoin_{comm,assoc,idem}`), out-of-order,
duplicated, or batched delivery all converge. Re-sending a frame the receiver already has
is a no-op.

**Stamp-frontier exchange.** `CrdtSync.frontier` advertises the highest `WireStamp` the
sender has observed from each peer. The receiver merges it into its own frontier (per-peer
`max`); the **causal-stability watermark** is the `min` over membership of that frontier —
the causal point every replica has provably passed.

**Watermark / GC contract.** A tombstone whose delete stamp is `≤` the stability watermark
is collectable on *every* replica, so dropping it cannot lose an edit. This safety property
is formally proven (`LazilyFormal.CRDT.collectable_implies_observed_everywhere`: a
collectable stamp is `≤` every member's observation) and drives the runtime
`SeqCrdt::gc` / `TextCrdt::gc_with`. A single replica's local clock is explicitly **not** a
sound watermark; only the version-vector minimum is.

**Permission filtering.** `CrdtSync.filter_readable(peer)` drops ops for non-readable nodes
entirely (omission, not redaction — like `Delta`). The `frontier` advertisement is retained
in full: it names peers and stamps, not node content, and the receiver needs the whole
frontier to compute a sound watermark.

> **Status.** The wire format, codec round-trips, permission filtering, and point-to-point
> `IpcSink`/`IpcSource` delivery are implemented (`#lzcrdtplane5a`). Wiring the plane to live
> `merge: crdt` root cells (local edits → `CrdtOp`s; remote `CrdtOp`s → `ReplicatedCell`
> ingress merge) and `BridgeHub` fan-out of `CrdtSync` is the runtime-integration slice
> (`#lzcrdtplane5b`).

### Single-writer effect authority

CRDT convergence covers *state*. For **irreversible external actions** (send email, charge card, fire webhook), gate the effect behind a single-writer authority — a designated peer (or small Raft group) decides when the effect fires, at-most-once.

## Permission Boundary (RemoteOp)

Only nodes on the per-peer allowlist are serialized into a snapshot or delta. Non-allowlisted nodes are **omitted entirely** (not even as `Opaque`).

### RemoteOp

```
RemoteOp = { kind: OpKind, node: NodeId }
OpKind = "read" | "write" | "trigger_effect"
```

- Three kinds are gated **independently**: a read grant never implies write or effect-trigger.
- `PeerPermissions` is default-deny per-peer allowlist.
- `filter_readable(peer, nodes)` drops non-readable nodes from results before serialization.
