# lazily Wire Protocol Specification

Normative source of truth for all lazily language bindings.

## Shared Types

### NodeId / PeerId

```
NodeId = u64
PeerId = u64
```

Wire-stable identifiers decoupled from internal `SlotId`. Serialized as bare JSON numbers. JavaScript/TypeScript peers must keep values at or below `Number.MAX_SAFE_INTEGER` (2^53).

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
| `NodeAdd` | `node`, `type_tag`, `state: NodeState` | New node |
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

### Resync / gap handling

On a `Delta` whose `base_epoch != last_epoch`:
1. Receiver discards the delta.
2. Receiver requests a fresh `Snapshot`.
3. Sender replies with `Snapshot { epoch }`.
4. Deltas resume from the new epoch.

Messages are length-prefixed and tagged `Snapshot` / `Delta`. The protocol is transport-agnostic (unix socket, pipe, WebSocket, shared memory).

### Shared-memory IPC

`ShmBlobArena` provides the shared-memory payload path:
- Arena writes a fixed header before each payload: `{ generation, epoch, length, checksum }`.
- Readers validate the header before accepting a descriptor.
- `IpcMessage` control frames carry `ShmBlobRef` descriptors instead of embedding large bytes inline.

Shared memory carries large blob payloads; ordinary control transport carries framed `IpcMessage`s. Each process keeps its own local `Context` / `ThreadSafeContext` and reconciles via snapshots and deltas.

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
