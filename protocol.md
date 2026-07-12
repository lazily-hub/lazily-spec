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
- Each `Delta` carries `{ base_epoch, epoch }` with `epoch >= base_epoch + 1`. The common
  single-flush case is `epoch == base_epoch + 1`; a **multi-epoch-span** delta
  (`epoch > base_epoch + 1`) coalesces several accepted-event epochs into one op batch (see
  [§ Multi-epoch-span delta](#multi-epoch-span-delta)). The span `epoch - base_epoch` is the count
  of accepted (deduped) events this batch advances past — a re-emit that dedups to a no-op adds no
  span. `epoch < base_epoch + 1` (empty or backward) is never valid.
- Deltas are **contiguous by base**, not strictly unit-stepped. A receiver detects gaps, reorders,
  or sender restarts by checking `base_epoch == last_epoch`: a delta whose `base_epoch != last_epoch`
  is a gap and triggers resync ([§ Reliable Sync](#reliable-sync-lzsync)) regardless of its span.

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
| `base_epoch` | `u64` | Epoch this delta applies to (must equal the receiver's `last_epoch`) |
| `epoch` | `u64` | New epoch, `>= base_epoch + 1`; `epoch - base_epoch` is the accepted-event span (usually 1, `> 1` for a [multi-epoch-span delta](#multi-epoch-span-delta)) |
| `ops` | `DeltaOp[]` | Ordered operations; applied as an ordered fold, atomically advancing `last_epoch` from `base_epoch` to `epoch` |

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

This narrative is the informal shape; the normative decision function (inbound frame →
`Apply` / `RequestSnapshot` / `Ignore`) is the **`ResyncCoordinator`** state machine specified in
[§ Reliable Sync](#reliable-sync-lzsync), which also fixes the durable-outbox replay and
sync-driver loop that make gap recovery, reconnect backfill, and at-least-once delivery a
*protocol* rather than an each-consumer hand-roll.

Messages are length-prefixed and tagged `Snapshot` / `Delta`. The protocol is transport-agnostic (unix socket, pipe, WebSocket, shared memory).

### Multi-epoch-span delta

A `Delta` MAY advance more than one epoch in a single frame: `epoch > base_epoch + 1`. This models
a producer whose epoch is a **cumulative count of accepted (deduped) events** and who coalesces
several such events into one flush (agent-doc's `WireDelta` is exactly this: a delta "may span
multiple epochs", epoch = per-document accepted-event count). The op list is still the ordered
change set; `epoch - base_epoch` records how many accepted events the batch folds.

Normative apply semantics:

- **Batch = fold.** Applying one `Delta { base_epoch, epoch, ops }` MUST equal applying the same
  `ops` in order as a run of unit deltas that advances `last_epoch` from `base_epoch` to `epoch`.
  The receiver observes only the endpoints (`base_epoch`, `epoch`); intermediate epochs are not
  separately materialized. Proven equivalent in `lazily-formal`
  (`ReliableSync.multi_epoch_apply_eq_fold`).
- **Atomic advance.** The receiver advances `last_epoch` to `epoch` only after the whole op list
  applies; a partial application never leaves `last_epoch` at an intermediate value.
- **Gap rule unchanged.** Acceptance still requires `base_epoch == last_epoch`; the span does not
  relax gap detection. A delta with `base_epoch != last_epoch` is a gap at any span.
- **Idempotent re-emit adds no span.** A re-emitted delta that dedups to no accepted change carries
  `epoch == base_epoch` worth of *new* effect and is either omitted or applied as a no-op; it never
  advances `last_epoch`.

Wire-compat: the unit-step case (`epoch == base_epoch + 1`) is the span-1 special case, so every
existing `Delta` fixture remains valid. Conformance:
[`conformance/reliable-sync/multi_epoch_delta.json`](conformance/reliable-sync/multi_epoch_delta.json).

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
| `codec` | `"json"`, `"msgpack"` (cross-language binary default), or `"postcard"` (Rust/same-schema fast path) — see [§ Frame codecs](#frame-codecs) |
| `max_frame_size` | Maximum frame size in bytes |
| `fragmentation_supported` | Whether frame fragmentation is supported |
| `ordered_reliable` | Delivery guarantee requirement |
| `peer_id` | `PeerId` for this session |
| `session_id` | Session/graph identifier |
| `features` | Supported feature flags |

If peers disagree on `protocol_major_version`, `codec`, `ordered_reliable`, or required features, they fail closed before applying any `Snapshot` or `Delta`.

### Frame codecs

Every serialized `IpcMessage` frame (`Snapshot`, `Delta`, `CrdtSync`) carries the **same
logical wire schema**; the `codec` handshake field selects only how those fields are bytes-encoded.
Three codecs are defined; a binding advertises the set it can encode/decode and the peers
negotiate one.

> **Two senses of "canonical" — read this first.** This spec keeps two terms distinct:
> - **Reference codec** = a *role*: the required, dependency-free, human-inspectable encoding that
>   every binding MUST speak, that the FFI baseline re-encodes to, and that conformance
>   fixtures / logs / receipts are written in. **`json` is the reference codec.** It is chosen for
>   this role because it is universal (a parser in every stdlib), inspectable, and deterministic —
>   *not* because it is efficient (it is the least efficient codec).
> - **Canonical bytes** = a *property of one codec+message*: the single deterministic byte string a
>   given codec produces for a given `IpcMessage`. `json` and positional `postcard` are
>   **byte-canonical** (one byte form per message per codec). `msgpack` named-field maps are **not**
>   byte-canonical across encoders (map key order is encoder-defined), so msgpack is the
>   reference-compatible *efficient transport*, never the reference codec.
>
> These are orthogonal: "reference codec" answers *which encoding is the required interop floor*;
> "canonical bytes" answers *does this codec produce one deterministic byte form*.

| Codec token | Self-describing | Role | Required of a binding |
|-------------|-----------------|------|-----------------------|
| `json` | yes | The **reference codec**: the required, dependency-free, human-inspectable interop floor — what the FFI baseline re-encodes to (§ FFI Boundary) and what fixtures/logs/receipts are written in. Byte-canonical. Least efficient (blob bytes travel as arrays of integers `0..255`). | **MUST** |
| `msgpack` | yes | The **negotiated cross-language binary default** on any binary boundary (IPC / WebSocket / WebRTC) between differing languages. Compact binary, self-describing, evolution-safe — the portable efficient transport every binding can host. Reference-JSON-compatible field names, but **not** byte-canonical across encoders. | **MUST** |
| `postcard` | no | A compact, positional Rust/same-schema fast path for two peers that share the exact Rust struct layout. Smallest and fastest on the wire, byte-canonical, but not cross-language. | **MAY** |

**Default selection.** A local, same-process, same-language pairing MAY default to `postcard`.
A boundary that crosses languages (the plugin⇄controller boundary, browser peers) negotiates
`msgpack`; `json` is the interoperable fallback and the required **reference codec** (also the FFI
baseline form). Peers never apply a frame under a codec they did not negotiate.

**MessagePack encoding is named-field.** `msgpack` frames encode each struct as a MessagePack
**map keyed by the JSON field name** (Rust: `rmp_serde::to_vec_named`), not as a positional array.
This keeps the field names identical to the `json` schema, so the *omit-when-absent* rule for
optional fields (the nullable `key` on `NodeSnapshot`/`NodeAdd`/`CrdtOp`, § NodeKey) holds
uniformly across `json` and `msgpack`, and a decoder that predates a later optional field ignores
it. Positional `postcard` instead always carries the optional discriminant for binary schema
stability.

**Conformance is semantic round-trip, not byte-identical, for the map codecs.** Because a
MessagePack map's key order is encoder-defined, two conforming bindings MAY emit byte-different
`msgpack` frames for the same `IpcMessage`; conformance requires only that
`decode(encode(m)) == m` and that decoding a peer's frame yields the equal `IpcMessage`. Only
`postcard` (positional) is byte-canonical across encoders. Cross-language `msgpack` fixtures
therefore pin the *decoded value*, never a golden byte string.

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

## Command / RPC Message Plane

Editor and runtime integrations issue **commands** — `Run Agent Doc`, sync,
focus, save, session operations — and need one reusable admission, dedupe,
cancellation, generation-guard, progress, and reconnect story instead of a
per-caller ad hoc request/response contract. lazily supplies an evented command
message plane for that use case. It is an **additive sibling family** to
`Snapshot` / `Delta` / `CrdtSync`; it does not add new state-plane variants.

The plane is feature-gated. Peers advertise `command-plane-v1` in the
[Capability Negotiation](#capability-negotiation) `features` array. A peer that
lacks `command-plane-v1` fails closed before accepting command traffic; a
command that requires the plane is not silently downgraded.

Four externally-tagged frames make up the family:

### CommandSubmit

```json
{
  "CommandSubmit": {
    "command_id": "cmd-run-1",
    "causation_id": "cmd-run-1",
    "source": "vscode-plugin",
    "target": "project-controller",
    "namespace": "agent-doc",
    "name": "editor_route",
    "authority_generation": 42,
    "idempotency_key": "project-root:plan.md:run",
    "deadline_ms": 120000,
    "policy": { "dedupe": "same_idempotency_key", "supersede": false, "cancel_on_preempt": true },
    "payload_type": "agent-doc.editor_route.v1",
    "payload_hash": "sha256:…",
    "payload": { "Inline": [123, 34, 102, 34, 58, 34, 46, 34, 125] },
    "required_features": ["causal-receipts", "command-events"]
  }
}
```

lazily owns the envelope (`command_id`, correlation, idempotency, generation,
policy, payload framing). The **namespace owns the payload**: lazily never
interprets the `payload` body, which is a normal [`IpcValue`](#ipcvalue-payload)
(inline bytes or a shared-memory blob). `payload_type` and `payload_hash`
identify and pin the domain body.

### CommandCancel

`CommandCancel` preempts a still-non-terminal command by `command_id` at a given
`authority_generation`, with an optional `reason`. A stale-generation cancel is
ignored. A cancel after a terminal outcome never rewrites it.

### CommandEvents

`CommandEvents` batches progress/detail events keyed by `command_id`. Event
kinds are `observed`, `accepted`, `started`, `progress`, `cancelled`,
`superseded`, `timed_out`. Events are **UX and diagnostics only** — queue
position, retry advice, copied CLI output. They are never terminal proof. Even
`cancelled` / `superseded` / `timed_out` events are surfaced for UX; their
terminal authority is a matching `rejected` [causal receipt](#causal-receipts).

### CommandProjection

`CommandProjection` is the folded, queryable image of known command state:
per-command `status`, an explicit `terminal` flag, `generation`, terminal
`reason`, and the `terminal_receipt_id` / `last_event_id` that produced it. It is
also the reconnect resync frame: after a controller handoff/recycle a plugin
folds a fresh `CommandProjection` and recovers in-flight and terminal state
without replaying the underlying events.

### Projection rules

- **Terminal authority is the causal receipt, not the event or the transport.**
  A command becomes terminal (`applied` / `rejected` / `cancelled` /
  `superseded` / `timed_out`) only when a terminal `CausalReceipt` for its
  `command_id` folds in. `observed` / `accepted` / `started` / queued admission
  are non-terminal progress. A network ACK is never terminal.
- **Generation guards.** Events and receipts whose `generation` does not match
  the command's current authority generation are ignored by the projection and
  retained only as audit data.
- **Idempotency.** A replayed `CommandSubmit`, event, or receipt (same
  `command_id` / `event_id` / `receipt_id`) is a no-op; the projection is
  unchanged.
- **Cancel before terminal only.** A cancel terminally rejects a non-terminal
  command; a cancel after `applied` is ignored.
- **Terminal conflict fails closed.** Two terminal receipts at the same
  generation with different outcomes is a conflict; consumers fail closed rather
  than pick a winner (the same rule as [Causal Receipts](#causal-receipts)).
- **Reconnect equivalence.** Folding a `CommandProjection` image is equivalent
  to folding the events and receipts it summarizes.

### RPC facade

Bindings expose an RPC-style API (`call` / `submit` / `cancel` / `observe` /
`projection`) implemented entirely over these frames:

- `call` builds and sends a `CommandSubmit`, observes events and receipts, and
  resolves **only** when the command projection reaches a terminal causal
  receipt. A transport ACK, controller admission, or `accepted` / queued event
  never resolves a unary `call`.
- `submit` returns the `command_id` immediately for callers that manage events
  and projection themselves.
- `cancel` sends `CommandCancel` and returns the resulting projection.
- `observe` / `stream` exposes `CommandEvents` and projection updates for UI
  progress.
- Reconnect uses `CommandProjection`; callers replay a `call` only when the
  idempotency policy says replay is safe.
- The terminal-result error shape exposes the terminal command projection
  (`status`, `reason`), not a collapsed boolean.

Unary RPC completion means command **effect** completion, proven by a terminal
causal receipt — not network delivery. The schema is
[`schemas/message-passing.json`](schemas.md#message-passingjson); fixtures live
in [`conformance/message-passing/`](conformance.md).

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
| **Frame codecs** (`json` reference + `msgpack` cross-language binary; `postcard` optional) | MUST | [§ Frame codecs](#frame-codecs) | [`conformance/`](conformance/) IPC fixtures round-trip through `json` **and** `msgpack` for all three `IpcMessage` variants (`Snapshot`/`Delta`/`CrdtSync`) |
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
`CrdtSync = 3` and the reliable-sync control frames `ResyncRequest = 4` / `OutboxAck = 5`
([§ Reliable Sync](#reliable-sync-lzsync)). This is the lingua franca that lets any binding embed
any other without a language-specific bridge.

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
    LazilyFfiMessageKind_Unknown       = 0,
    LazilyFfiMessageKind_Snapshot      = 1,
    LazilyFfiMessageKind_Delta         = 2,
    LazilyFfiMessageKind_CrdtSync      = 3,
    LazilyFfiMessageKind_ResyncRequest = 4,  /* #lzsync control frame */
    LazilyFfiMessageKind_OutboxAck     = 5,  /* #lzsync control frame */
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
# Snapshot/Delta/CrdtSync are the forward (state) plane; ResyncRequest/OutboxAck
# are the reverse-channel reliable-sync control frames (§ Reliable Sync, #lzsync).
IpcMessage = Snapshot(Snapshot) | Delta(Delta) | CrdtSync(CrdtSync)
           | ResyncRequest(ResyncRequest) | OutboxAck(OutboxAck)

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

### Reactive family sync (`#lzfamilysync`)

A `ReactiveFamily` (`cell-model.md` § "Materialization mode") is a *local* keyed reactive
collection. This section fixes its **distributed** contract: what a peer does with a keyed
`CrdtOp` (`NodeKey = namespace/suffix`) for a family entry it has **not** registered locally.

The base plane, given such an op, resolves the node by `NodeKey`; if no cell is registered
under that key the op is **dropped**. For a *family* that is wrong: a key added on one replica
would never appear on another, and any derived aggregate over the family (a count of entries)
would diverge.

Family-granularity sync closes the gap with **materialize-on-ingest**: a replica registers a
family under a `namespace`; an inbound keyed op whose first `NodeKey` segment matches a
registered family **materializes** a fresh entry (a new local `NodeId`, indexed by the wire
`NodeKey`) seeded from the op's converged register, then merges. Because the materialized
entry is seeded from the op state, materialize-on-ingest is *exactly* the pointwise CRDT
merge, so it inherits the full semilattice convergence.

Contract (proven in `lazily-formal` `FamilySync.lean`):

- **Materialize, never drop.** A keyed op for an absent family entry makes that key present
  and adopts the op's value (`applyOp_present`, `applyOp_absent_adopts`).
- **Membership propagation.** After sync a key is present iff it was present on *either*
  replica — the union (`present_merge`). The present set only grows (deferral-not-dealloc); a
  removed entry is a value-level tombstone, not a dropped key.
- **Convergence + idempotence.** Materialize-on-ingest equals merging the op's single-entry
  state (`applyOp_eq_merge`), so op delivery is order-independent (`applyOp_comm`) and
  re-delivery is a no-op (`applyOp_idem`).
- **Derived-aggregate transparency.** Once two replicas converge, any derived count over the
  family agrees regardless of sync direction/batching (`aggregate_converges`,
  `aggregate_batch_invariant`) — e.g. a live-editor / open-document count converges across
  editors. A `NodeId`-churn-stable membership signal drives the recompute so a
  remote-materialized key is picked up by the derived aggregate.

Conformance: `conformance/familysync/materialize_on_ingest.json`.

### Single-writer effect authority

CRDT convergence covers *state*. For **irreversible external actions** (send email, charge card, fire webhook), gate the effect behind a single-writer authority — a designated peer (or small Raft group) decides when the effect fires, at-most-once.

## Reliable Sync (`#lzsync`)

The `Snapshot`/`Delta` and `CrdtSync` planes above define *what* is on the wire and *how state
converges once delivered*. They do **not** define delivery reliability: what a receiver does with a
gap, what a sender does with a send that failed, or how a reconnected peer catches up. Today each
consumer hand-rolls that loop (and `Delta::apply_status → ResyncRequired` is a signal with no
production handler). This section fixes the reliable-sync protocol so gap recovery, reconnect
backfill, and at-least-once delivery are *specified* and cross-language-conformant, not
re-invented per integration.

**Layering — mechanism here, policy injected.** The three components below are pure protocol:
identical logic in every binding, no I/O, no clock, no storage engine. The environment-specific
choices — which byte transport, which persistence backend, retry cadence, threading — are supplied
by the host application behind the named seams (`SnapshotProvider`, `DurableOutbox` store,
`Clock`/scheduler, the `IpcSink`/`IpcSource` transport). A binding ships the protocol and a default
in-memory backend; the host plugs durable storage and a real transport.

**Control frames are `IpcMessage` variants, not a side channel.** `ResyncRequest` and `OutboxAck`
are two new externally-tagged **`IpcMessage` variants** (FFI message kinds `4` / `5`), riding the
same framed, codec-negotiated, **bidirectional** message plane as `Snapshot`/`Delta`/`CrdtSync` —
the reverse (receiver → sender) direction of that plane. This is deliberate over a separate control
type: they share one encode/decode path, one demux point, one FFI kind discriminant, and — because
they interleave in the *same ordered stream* as the deltas — a well-defined in-band position (an
`OutboxAck { through_epoch: N }` is meaningful relative to the deltas already sent on that channel).
The liveness ops are `CrdtOp`s on the existing `CrdtSync` variant. A binding MUST add both variants
to its `IpcMessage` enum and its FFI message-kind mapping.

**Codec.** Every reliable-sync frame (the two control variants and the liveness `CrdtOp`s) is an
ordinary framed message on the negotiated codec. Per [§ Frame codecs](#frame-codecs) the
cross-language boundary negotiates **`msgpack`** (self-describing, evolution-safe, named-field),
with `json` as the required reference codec; `postcard` stays the Rust-only fast path. Conformance
requires every new frame to round-trip through **both `json` and `msgpack`** (semantic round-trip,
not byte-identical, for the map codecs), the same discipline the three prior `IpcMessage` variants
already hold.

### ResyncCoordinator (`#resync-coord`)

A pure receiver-side decision function over the inbound frame stream. It holds one piece of state
per source — `last_epoch` (the highest epoch this receiver has fully applied) — and classifies each
inbound `Snapshot`/`Delta`:

```
enum ResyncAction { Apply, RequestSnapshot { from: u64 }, Ignore }

// pure; no I/O. `ingest` inspects a frame and returns the action; the caller performs it.
fn ingest(&mut self, msg: &IpcMessage) -> ResyncAction
```

Decision table (given receiver `last_epoch = L`):

| Inbound | Condition | Action | Effect on `L` |
|---|---|---|---|
| `Snapshot { epoch: e }` | always | `Apply` | `L := e` (adopt snapshot state) |
| `Delta { base_epoch: b, epoch: e }` | `b == L` and `e >= b + 1` | `Apply` | `L := e` after fold |
| `Delta { base_epoch: b }` | `b < L` | `Ignore` (already applied / re-delivery) | unchanged |
| `Delta { base_epoch: b }` | `b > L` | `RequestSnapshot { from: L }` | unchanged until snapshot |
| `Delta { epoch: e, base_epoch: b }` | `e < b + 1` | `Ignore` (malformed/empty) | unchanged |

- **`RequestSnapshot { from }`** is emitted at most once per detected gap; a coordinator that has
  already requested and not yet applied a covering `Snapshot` suppresses duplicate requests for the
  same gap (it stays in a `resyncing` sub-state, `Ignore`-ing further deltas until the snapshot
  lands). This bounds request storms under a burst of ahead-of-cursor deltas.
- **Convergence guarantee.** A receiver that drops an arbitrary suffix of deltas, then applies the
  resync `Snapshot`, reaches the *same* graph state as one that saw every delta — gap recovery is
  state-equivalent, not lossy (proven `ReliableSync.resync_convergence`). This holds because a
  `Snapshot` is a full-state frame, not an incremental one.
- **Idempotent re-delivery.** A `Delta` with `base_epoch < L` (a frame the receiver already folded,
  re-sent by the outbox) is `Ignore`d, so at-least-once delivery yields exactly-once effect.

The application supplies snapshots for the sender side of a resync via:

```
trait SnapshotProvider { fn snapshot(&self, from_epoch: u64) -> IpcMessage; }  // returns Snapshot { epoch >= from_epoch }
```

### DurableOutbox (`#durable-outbox`)

The sender-side contract that makes delivery **at-least-once across a crash/reconnect**. Today a
failed send leaves a permanent gap (the out-epoch is bumped before the send; a reconnect is a fresh
peer at epoch 0 with no backfill). The outbox closes that: every frame is durably recorded
*before* it is sent, retained until the peer proves receipt, and replayed from the peer's cursor on
reconnect.

```
trait DurableOutbox {
    fn append(&mut self, epoch: u64, msg: &IpcMessage);          // MUST persist before the send is attempted
    fn ack_through(&mut self, epoch: u64);                        // peer proved receipt through `epoch`; retained frames <= epoch may be pruned
    fn replay_from(&self, cursor: u64) -> impl Iterator<Item = (u64, IpcMessage)>;  // frames with epoch > cursor, in epoch order
}
```

Normative contract:

- **Append-before-send.** A frame MUST be durably appended before it is handed to the transport.
  If the process dies between append and a confirmed send, the frame is still in the outbox and is
  replayed on reconnect. (The pre-send epoch bump that caused the permanent-gap bug is replaced by:
  append at `epoch`, send, and only `ack_through` retires it.)
- **Replay-from-cursor.** On (re)connect the peer advertises the highest epoch it has applied
  (its `ResyncCoordinator.last_epoch`, carried in the reconnect handshake or an `OutboxAck`); the
  sender `replay_from(cursor)` re-sends every retained frame with `epoch > cursor` in order. A frame
  the peer already applied (`base_epoch < last_epoch`) is `Ignore`d by the coordinator — replay is
  safe.
- **At-least-once ⇒ exactly-once effect.** Replay delivers every op at least once; idempotent apply
  (the coordinator's re-delivery `Ignore` + the CRDT/PartialEq guards) makes the net effect
  exactly-once — no lost op, no doubled op (proven
  `ReliableSync.outbox_at_least_once_exactly_once_effect`).
- **Ack semantics.** `ack_through(e)` is a *retention* signal (safe to prune `<= e`), never a
  delivery-success authority for a domain effect (that is a [causal receipt](#causal-receipts)). An
  outbox MAY prune lazily; correctness does not depend on prompt pruning, only on not pruning
  *un-acked* frames.
- **`OutboxAck` frame.** The receiver periodically (or on request) sends
  `OutboxAck { through_epoch: u64 }` — a new framed `IpcMessage` — so the sender can advance
  retention and so a reconnect handshake can carry the resume cursor.

Bindings ship an `InMemoryOutbox` (default; correct within a process lifetime) and a **reference
file-backed impl for tests/conformance** (proves the crash-replay path deterministically). The host
plugs its own durable store (agent-doc: SQLite) behind the same trait; the cursor math is protocol,
the storage is not.

### SyncDriver (`#sync-driver`)

The loop **shape** that wires an outbound producer to a transport through the outbox, and drives
resync on reconnect. It owns no clock and no runtime: the host calls `tick()` from its own
scheduler, so the driver stays a pure state machine with injected seams.

```
struct SyncDriver<S: IpcSink, R: IpcSource, O: DurableOutbox, C: Clock> { /* transport, outbox, coordinator, clock */ }

impl SyncDriver {
    // One scheduler-driven step. Returns Progress (sent N, applied M, resynced) or a DriverError.
    fn tick(&mut self) -> Result<Progress, DriverError>;
}
```

`tick()` performs, in order:

1. **Drain inbound.** Pull available frames from `IpcSource`; feed each to `ResyncCoordinator.ingest`
   and perform the returned action (`Apply` into the local graph, emit a `ResyncRequest` /
   `OutboxAck`, or drop). Advance `last_epoch` on applied frames.
2. **Send outbound.** For each new local flush, `outbox.append(epoch, frame)` **then**
   `IpcSink.send(frame)`. A send error does **not** unwind the driver and does **not** lose the
   frame: the frame stays in the outbox, the driver records the transport as degraded, and the send
   is retried from the outbox on a later `tick` (cadence/backoff is the injected `Clock`'s policy).
3. **Resync on reconnect.** When the transport reports a fresh/reopened peer, exchange cursors
   (peer's `OutboxAck.through_epoch`) and `replay_from(cursor)`; if the local receiver is behind,
   emit its `ResyncRequest`.
4. **Retention.** On an inbound `OutboxAck`, `outbox.ack_through(through_epoch)`.

Contract:

- **No frame lost on send failure.** The append-before-send + retain-on-error rule means a frame is
  delivered on a subsequent tick once the transport recovers (the exact bug the current
  `?`-propagating `poll` has, where a failed send bumps the epoch and unwinds).
- **Bounded work per tick.** `tick()` does a bounded amount of drain/send work and returns; the host
  controls cadence. No internal blocking, no async runtime baked in.
- **Injected clock/transport.** Retry cadence, backoff, and "is the peer fresh" come from the
  injected `Clock` and transport signals — policy stays in the host, mechanism in the driver.
- **Backpressure is host policy, not driver mechanism.** The driver does **not** bound its outbound
  staging or block the producer: `enqueue` is unbounded and the `DurableOutbox` retains every unacked
  frame until the peer's `OutboxAck` (this is the at-least-once durability guarantee — a frame is not
  dropped to relieve pressure). Instead the driver exposes the signals a host uses to apply
  backpressure itself: the stall state (`is_stalled` / `stalled_for`) and the retained-outbox depth
  (`Progress.retained`). A host bounds memory by (a) rate-limiting or coalescing enqueues off those
  signals — a re-emit at an already-accepted epoch is an idempotent no-op delta, so coalescing is the
  natural limiter — and (b) choosing a `DurableOutbox` that spills to durable storage rather than RAM
  (e.g. a SQLite-backed outbox), so a long-stalled peer grows disk, not heap. Enforcing a bounded
  staging queue (e.g. via a `QueueCell`-style `is_full`) is a deliberate non-goal of the core loop;
  add it in the host if a hard cap is required.

`IpcSink`/`IpcSource` are the existing abstract transport traits (feature `ipc`); the byte carrier
is any `DataChannel`. **Un-gating:** the driver and the `BridgeHub` fan-out it can wrap depend only
on these abstract `ipc` traits, so they MUST be usable without the `webrtc` feature (a caller
supplying a Unix-domain-socket `DataChannel` gets reliable sync with no WebRTC dependency). The
per-document channel decision (one driver/transport per document vs one hub with
`document_hash`+`NodeKey` namespacing) is a host concern; the pull-only consumer path may not need
`BridgeHub` fan-out at all.

#### Transport seam (`IpcSink` / `IpcSource`, `#lzsync-transport-seam`)

The `SyncDriver` is generic over exactly two host-supplied seams. Every binding that ports the
driver MUST provide the same two-method contract so the loop above is **identical** across
languages; the seams are the injected boundary the design assigns to the host ("which socket" is a
deployment choice), so they carry **no wire form of their own** — what crosses the wire is the
codec-encoded `IpcMessage` frame (msgpack is the cross-language default; see § Frame codecs). A
binding names them idiomatically (Rust traits, Kotlin/TS interfaces); the semantics are normative:

```
// Outbound: deliver exactly one already-encoded protocol frame.
trait IpcSink   { fn send(&mut self, msg: &IpcMessage) -> Result<(), SinkError>; }
// Inbound: poll for the next frame without blocking.
trait IpcSource { fn recv(&mut self) -> Result<Option<IpcMessage>, SourceError>; }
```

- **`send` MAY fail and MAY be lossy.** A `send` error means the frame was *not* durably handed to
  the peer. At-least-once is a **driver** property, not a sink property: on a send error the driver
  keeps the frame in the `DurableOutbox` and replays it after the next reconnect. A sink is therefore
  free to be a plain best-effort write (one connect-send-receipt on a Unix socket, one `DataChannel`
  frame, …) — it never has to buffer or retry, because the outbox already does.
- **`recv` is poll, not block.** `Ok(None)` means the source is *currently exhausted or closed*; the
  driver treats it as "no inbound progress this tick" and returns — it never parks a thread on the
  source (cadence is the host's `Clock`/scheduler policy). `Ok(Some(frame))` yields one frame.
- **A `recv` `Err` is the reconnect signal.** A source read failure surfaces from `tick()` as
  `DriverError::Source`; the host re-establishes the byte carrier and calls `on_reconnect()`, after
  which the next `tick()` replays the unacked outbox suffix from the peer ack cursor and re-advertises
  the receiver cursor. (A *sink* failure, by contrast, is retain-and-stall, **not** a `DriverError` —
  it is reported through `Progress`/stall signals so the host can back off.)

Because the seam has no wire representation, it adds **no conformance fixture**: the reliable-sync
fixtures already pin the driver's observable behavior (gap→resync convergence, outbox replay,
idempotent redelivery) at the message-sequence level, which is the correct abstraction — the seam
sits deliberately *below* it. This is also why the seam is **not** formalized in `ReliableSync.lean`:
"send/receive a frame" has no algebraic content to prove; the invariants that matter
(`resync_convergence`, `outbox_at_least_once_exactly_once_effect`, the liveness lattice joins) are
proven over frame sequences, above the transport.

### Liveness cells: OR-set and LWW (`#lzsync-liveness`)

Cross-process **liveness** — "editor pid X has doc Y open", "pid X holds the owner lease" — is
carried as CRDT cells on the [CrdtSync plane](#distributed-crdt-cell-plane), not as a bespoke frame,
so it inherits that plane's idempotent, frontier-resumable, re-delivery-safe convergence. Two
register shapes cover the liveness needs:

- **OR-set membership** — the **open-set** of `(doc, pid)` presence. An observed-remove set: a
  `(doc, pid)` is *present* iff some add-tag for it is not shadowed by a remove-tag that observed
  that add. This gives the exact "add wins over a concurrent stale remove" bias liveness needs (a
  re-open concurrent with a lagging close keeps the doc open), and re-delivery of an add/remove is a
  lattice join → idempotent. Whole-editor death removes every `(doc, pid)` for that pid.
- **LWW liveness flag** — a per-pid `alive: bool` and the owner **lease** as HLC-stamped
  last-writer-wins registers (the CRDT plane's default register, § Cell register types). The OS
  process-exit event writes `alive[pid] = false`; the highest-stamp write wins, and a stale
  re-assert is dominated.

Normative semantics:

- **Frontier-resumable.** A liveness op that fails to send while the peer is down is re-sent on
  reconnect from the `CrdtSync.frontier` (the plane is already "safe to resend"); no liveness state
  is lost across a disconnect. This is what lets the open-set/lease survive a controller recycle
  without the editor re-announcing.
- **Derived authority is reactive.** "Is doc Y live" = *any present `(doc, pid)` in the OR-set whose
  `alive[pid]` is true* — a derived aggregate over the liveness family (the `#lzfamilysync`
  materialize-on-ingest + derived-count contract). One `alive[pid] = false` write fans out to every
  doc that pid held (whole-editor death cascade), reactively.
- **Idempotent + convergent.** OR-set join and LWW join are semilattice joins, so out-of-order,
  duplicated, or batched delivery all converge and re-delivery is a no-op (proven
  `ReliableSync.crdt_liveness_convergence_under_retry`, building on the existing CRDT lattice
  proofs).
- **Per-doc isolation.** Liveness keys are namespaced `(document_hash, …)` like every other keyed
  op, so a stale overlay for doc B cannot flip doc A's authority.

### Conformance

New fixtures under [`conformance/reliable-sync/`](conformance/reliable-sync/) pin the protocol
cross-language (rs/js/kt):

| Fixture | Pins |
|---|---|
| `resync_gap_converge.json` | drop a delta suffix → `RequestSnapshot` → apply `Snapshot` → same graph as the no-drop receiver (`ResyncCoordinator` decision table + convergence) |
| `outbox_replay_after_crash.json` | append-before-send, replay-from-cursor after a simulated crash, `ack_through` retention, exactly-once effect under replay |
| `idempotent_redelivery.json` | a re-delivered (`base_epoch < last_epoch`) delta is `Ignore`d; net state unchanged |
| `multi_epoch_delta.json` | a `Delta` with `epoch > base_epoch + 1` applies equal to the unit-delta fold; atomic `last_epoch` advance |
| `liveness_orset_lww.json` | OR-set open-set membership + LWW `alive`/lease; whole-editor-death cascade; derived live-doc aggregate converges under retry/re-delivery |

Every fixture's frames MUST round-trip through both `json` and `msgpack`. The `ResyncCoordinator`,
`DurableOutbox`, and liveness models are the shared cross-language pins; `lazily-formal`
`ReliableSync.lean` is the correctness backstop the implementations must match.

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
