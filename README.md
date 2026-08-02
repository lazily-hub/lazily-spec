# lazily-spec

Language-agnostic wire protocol specification for the **lazily** reactive signals family.

**lazily** is one reactive model — sources, computeds, effects, keyed collections,
CRDTs, and a distributed sync plane — implemented natively in nine languages. This repo
is the hub: it defines the canonical message schemas, the cross-language feature matrix,
and the conformance corpus every implementation replays, so a graph built in one language
converges with a graph built in any other.

Start here: the [wire protocol](protocol.md), the [cell model](cell-model.md), the
**Feature Set** matrix below, and the **Conformance Fixtures** every binding must pass.

## Implementations

Nine native language bindings plus a React adapter. Each one implements the same cell
model and the same wire protocol, and each replays the conformance corpus in this repo —
per-binding parity is tracked in the **Feature Set** matrix below and in
**Binding Conformance**.

| Repo | Language |
|------|----------|
| [lazily-rs](https://github.com/lazily-hub/lazily-rs) | Rust — the reference implementation |
| [lazily-py](https://github.com/lazily-hub/lazily-py) | Python |
| [lazily-go](https://github.com/lazily-hub/lazily-go) | Go |
| [lazily-kt](https://github.com/lazily-hub/lazily-kt) | Kotlin / JVM |
| [lazily-js](https://github.com/lazily-hub/lazily-js) | JavaScript / TypeScript |
| [lazily-cs](https://github.com/lazily-hub/lazily-cs) | C# / .NET |
| [lazily-cpp](https://github.com/lazily-hub/lazily-cpp) | C++ |
| [lazily-zig](https://github.com/lazily-hub/lazily-zig) | Zig |
| [lazily-dart](https://github.com/lazily-hub/lazily-dart) | Dart / Flutter |
| [lazily-react](https://github.com/lazily-hub/lazily-react) | React / Preact bindings layered over `lazily-js` — an adapter, not a separate language binding |

**Formal model:** [lazily-formal](https://github.com/lazily-hub/lazily-formal) — the
Lean 4 model of the shared primitive types, the flat FSM kernel, and the full Harel/SCXML
state chart. It is the neutral formal home every binding depends on equally, and the
executable reference behind the state-chart conformance fixtures (see **Formal Model**).

## Feature Set

The full `lazily` capability set and its cross-language coverage across every
binding (`lazily-rs`, `lazily-py`, `lazily-kt`, `lazily-js`, `lazily-dart`,
`lazily-zig`, `lazily-go`, `lazily-cpp`, `lazily-cs`). Legend: ✅ shipped · `~` partial · `—` absent or not applicable.
This table is generated from [`coverage.json`](coverage.json) — the canonical
matrix with per-cell notes and platform carve-outs lives in
[Cross-Language Coverage](docs/coverage.md). Edit `coverage.json` and run
`make coverage-sync` to update it in one shot; `make coverage-check` guards drift.

<!-- coverage-table:start -->
| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: |
| Reactive graph — two cell kinds (nodes `SourceCell` / `ComputedCell`; handles `Source<T, M>` / `Computed<T>`) + `Effect` sink + eager `Computed` (`computed().eager()`) / all cells guarded / batch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed-map materialization (`ComputedMap`) — mint-on-access derived slots: transparency + deferral (`#lzmatmode`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe keyed map (`ThreadSafeComputedMap`) — `Send + Sync` + materialization confluence (`#lzmatmode`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Async keyed map (`AsyncComputedMap`) — eventual transparency (`#lzmatmode`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed-map sync — membership propagation + materialize-on-ingest + derived-aggregate transparency (`#lzfamilysync`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe context (lock-backed) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Async reactive context | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Flat state machine | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Harel state charts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed reactive maps (`ReactiveMap`: `SourceMap` / `ComputedMap`) + `SourceTree` + reconcile | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ReactiveMap` **Core surface** — single-threaded flavor (cell-model.md § Core surface vs. binding extensions) | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ |
| `ReactiveMap` **Core surface** — thread-safe flavor (ordering + membership reactivity) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `ReactiveMap` **Core surface** — async flavor (ordering + membership reactivity) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Atomic ordered move replayed against **all three flavors** (`cellmap_atomic_move` + `cellmap_independence`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Memoized semantic tree (`SemTree`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stable-id alignment (manufactured identity) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — single-threaded flavor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — async flavor (reader kinds + eventual transparency) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Broadcast topic (`TopicCell`) **Core surface** — single-threaded flavor — independent cursors + durable replay + safe GC (`#lztopiccell`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Broadcast topic (`TopicCell`) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Broadcast topic (`TopicCell`) **Core surface** — async flavor (reader kinds + eventual transparency) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Competing-consumer work queue (`WorkQueueCell`) **Core surface** — single-threaded flavor — exclusive leases + ack/nack + redelivery + DLQ (`#lzworkqueue`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Competing-consumer work queue (`WorkQueueCell`) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Competing-consumer work queue (`WorkQueueCell`) **Core surface** — async flavor (reader kinds + eventual transparency) | ✅ | ✅ | ✅ | — | ✅ | — | ✅ | ✅ | — |
| Merge algebra + `Source<T, M>` — associative `MergePolicy` (`KeepLatest`/`Sum`/`Max`/`SetUnion`/`RawFifo`), `Cell ≡ Source<KeepLatest>`, read-any-cell/write-`Source` split (`#relaycell`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| RelayCell — conflating relay + `BackpressurePolicy` + `SpillStore` + `Transport` + Inbox/Outbox + Rate/Window/Expiry/Priority/keyed policies (`#relaycell`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Free-text character CRDT (`TextCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TextCrdt` delta sync (`version_vector` / `delta_since` / `apply_delta`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `CrdtTree` lossless document contract (`#lzcrdttree`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Move-aware sequence CRDT (`SeqCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree CRDT core (`LosslessTreeCrdt`, M1) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — dotted-frontier anti-entropy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — concurrent merge convergence | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Registers (LWW / MV) + `PnCounter` + `CellCrdt` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| IPC wire — `Snapshot` + `Delta` + `CrdtSync` | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | ✅ |
| Frame codec — `json` **reference codec**: dependency-free interop floor, FFI baseline form, byte-canonical (**MUST**) — executable round-trip obligation (`conformance/codec/frame_roundtrip_json.json`, `#lzmsgpackparity`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Frame codec — `msgpack` **cross-language binary default**: externally-tagged frame over named-field maps, semantic (not byte-identical) round-trip (**MUST**) — executable round-trip obligation (`conformance/codec/frame_roundtrip_msgpack.json`, `#lzmsgpackparity`). Shipping *a* MessagePack codec does not earn this mark: lazily-cpp read `~` here while its private internally-tagged framing wore the token, and only flipped once it shipped the spec wire (`#lzcppmsgpackwire`) | ✅ | — | — | — | — | — | — | ✅ | — |
| Frame codec — `postcard` positional same-schema fast path: smallest + byte-canonical, not cross-language (**MAY**) | ✅ | — | — | — | — | — | — | — | — |
| Shared-memory blob path (`ShmBlobArena`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Cross-process zero-copy transport (`BlobBackend` / shm / arrow) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed CRDT plane (`CrdtPlaneRuntime` / anti-entropy) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reliable sync — resync coordinator + at-least-once durable outbox + OR-set/LWW liveness (`#lzsync`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Storage-independent durable outbox (`OutboxStore` + shared outbox protocol; SQLite/Room/IndexedDB/file adapters) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reliable-sync transport seam + full-duplex `SyncDriver` loop (`IpcSink`/`IpcSource`, `#sync-driver`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed plane — WebRTC transport + signaling | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| State projection / mirror | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Causal receipts (`CausalReceipts` outcome projection) | ~ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Message-passing + RPC command plane (`command-plane-v1`) | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ |
| C-ABI FFI boundary | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Permission boundary (`PeerPermissions` / `RemoteOp`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Capability negotiation (`SessionHandshake`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Instrumentation / benchmarks | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Temporal sources — `TimerCell` / `IntervalCell` / `CronCell` / `DeadlineCell` over a logical clock (`#lztime`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Rate-shaping operators — `DebounceCell` / `ThrottleCell` / `SampleCell` / `ProbabilisticSampleCell` (`#lzrateshape`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Membership + failure detection — `MembershipCell` (SWIM + Phi-accrual) / `PeerSet` / `PeerChangeEvent` (`#lzmemb`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed coordination — `LeaseCell` / `LeaderCell` / `LockCell` / `SemaphoreCell` / `BarrierCell`+`QuorumCell` (`#lzcoord`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Presence + ephemeral plane — `PresenceCell` / `AwarenessCell` / `EphemeralCell` + `Ephemeral`/`Durable` markers (`#lzpresence`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stream windowing — `TumblingWindow` / `SlidingWindow` / `SessionWindow` over the merge algebra (`#lzwindow`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fault tolerance — `CircuitBreakerCell` / `RetryPolicyCell` / `BulkheadCell` / `TimeoutCell` (`#lzresilience`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib `Timer` (`stdlib_timer_v1`) — canonical fixture + mutation-gate verified | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib caller-driven `Timeout<T>` (`stdlib_timeout_v1`) — distinct from reactive `TimeoutCell` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib `RevisionBarrier` (`stdlib_revision_barrier_v1`) — register/recheck lost-wakeup guard | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Embedded-service plane — `HealthCell` / `ReadinessCell` / `DiscoveryCell` / `ServiceRegistry` (`#lzservice`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Transport-agnostic reactive ingress (`IngressCell`) — keyed lifecycle scopes, generation/sequence/freshness envelopes, reorder buffer, accepted/dropped/error receipt readers (`#designimplementtransport`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ingress family — `Send + Sync` flavor (`ThreadSafeIngressCell`): one frontier walk per admission (`#designimplementtransport`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ingress family — async flavor (`AsyncIngressCell`): admission is not async-coloured (`#designimplementtransport`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
<!-- coverage-table:end -->

CRDT convergence and the wire protocol are pinned by the shared conformance fixtures
and JSON Schemas in `lazily-spec` and the Lean models in `lazily-formal`.

## Binding Conformance

The bindings the columns above refer to are listed, with links, under
**Implementations** near the top of this file.

Every binding MUST implement the layers in the [Binding Conformance Matrix](protocol.md#binding-conformance-matrix).
The **distributed CRDT plane (`CrdtSync`)** and the full keyed cell collections layer
(`SourceMap`, `SourceTree`, keyed reconciliation) are unconditional — implementable on any
runtime that speaks the wire. The **C-ABI FFI boundary** is required by default, with a
narrow platform carve-out: a binding whose runtime structurally cannot host a native
in-process C ABI (browser/Worker JS, sandboxed runtimes) declares `ffi = none`, still
exposes the full state plane over IPC/WebSocket/WebRTC, and must not advertise itself as
embeddable. The **thread-safe** and **async** reactive contexts are required where the
platform supports them — a platform that structurally lacks threading or suspendable
async declares `thread_safe = none` / `async = none` (see
[Concurrency layers are required](protocol.md#concurrency-layers-are-required)). The
**shared-memory payload path** (`ShmBlobArena`) is required where the platform supports
it; a binding that cannot host a shared-memory arena declares `shared_memory = none` and
MUST fall back to **I/O channels accessing the memory** — large payloads are carried
`Inline` over IPC/WebSocket/WebRTC instead of as `ShmBlobRef` descriptors (see
[Shared-memory payload path is required](protocol.md#shared-memory-payload-path-is-required)).
Any omitted `MUST` row MUST be advertised rather than fail silently.

Python, Dart, Rust, and Go vendor selected fixture subsets so their suites can
run without a sibling checkout. From this canonical repository,
`make fixture-copies-check-all` verifies every tracked copy byte-for-byte and
`make fixture-copies-sync` refreshes the present mirrors. The ordinary
`make check` verifies every sibling mirror that is currently checked out.

## Protocol Layers

| Layer | Spec | Schema |
|-------|------|--------|
| IPC (Snapshot + Delta) | [protocol.md](protocol.md) § IPC | [schemas/snapshot.json](schemas/snapshot.json), [schemas/delta.json](schemas/delta.json) |
| Shared wire primitives | [protocol.md](protocol.md) § Shared Types | [schemas/defs.json](schemas/defs.json) |
| Cross-language FFI | [protocol.md](protocol.md) § FFI | [schemas/ffi.json](schemas/ffi.json) |
| Signaling (WebSocket) | [protocol.md](protocol.md) § Signaling | [schemas/signaling.json](schemas/signaling.json) |
| Distributed (CRDT) | [protocol.md](protocol.md) § Distributed | [schemas/distributed.json](schemas/distributed.json) |
| Causal receipts | [protocol.md](protocol.md) § Causal Receipts | [schemas/receipts.json](schemas/receipts.json) |
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

The language-agnostic formal model — shared primitive types, the flat FSM
kernel, and the full Harel/SCXML state chart — lives in its own repo,
[`lazily-formal`](https://github.com/lazily-hub/lazily-formal), as the neutral
formal home every binding depends on equally. It is the executable reference
behind the state-chart conformance fixtures (see below).

Verify it with the local check target:

```bash
make check
```

## Relationship to lazily-rs SPEC.md

This repo extracts the wire-protocol and cross-language compatibility sections from `lazily-rs/SPEC.md` into a standalone reference. Rust-specific internals (the concrete `Context`/`ThreadSafeContext` lock strategy, benchmarks) remain in the Rust crate; the *existence* of the thread-safe and async context surfaces is cross-language and required where the platform supports it.

## Conformance Fixtures

The `conformance/` directory contains canonical test fixtures that all IPC-capable bindings must validate against. Each binding's CI should deserialize the `wire` field, run the assertions, and re-serialize to confirm round-trip fidelity.

**Fixture schema:**

```json
{
  "description": "Human-readable summary",
  "protocol_version": 1,
  "kind": "Snapshot" | "Delta" | "Receipt",
  "assertions": { "…language-agnostic field checks…" },
  "wire": { "…canonical protocol JSON…" }
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
| `receipts/causal_receipts.json` | Receipt | Generic causal receipt projection with terminal `applied` / `rejected` outcomes |

**Adding a new binding:** Copy the fixture-loading pattern from `lazily-rs/tests/conformance.rs`. Each test should (1) load the fixture, (2) parse the `wire` field into the binding's native `IpcMessage` type, (3) assert the `assertions` fields, (4) re-serialize and compare.

## Keyed Cell Collections Conformance

The `conformance/collections/` directory contains canonical fixtures for the [keyed cell collections](cell-model.md#keyed-cell-collections) layer, which is **required of every binding**. Unlike IPC fixtures these are **compute** — a binding loads the `initial` state, replays each `step`'s `op`, and asserts the `expected` observable effects (resulting `order`, `values`, `membership`, and which reader classes — `value` / `membership` / `order` — invalidate). The reconciliation fixture is declarative: diff `prior` → `target` and assert the emitted minimal op set.

| Fixture | Covers |
|---------|--------|
| `collections/cellmap_independence.json` | value / set-membership / order reactivity independence (write, insert, remove, pure reorder) |
| `collections/cellmap_atomic_move.json` | atomic ordered move keeps handle/dependents, bumps order once, leaves value readers untouched |
| `collections/keyed_reconciliation_lis.json` | LIS move-minimized reconciliation; stable entries not invalidated by sibling reorder |
| `collections/semtree_incremental.json` | memoized semantic tree: ancestor-chain-only recompute, sibling isolation, memo equality guard |
| `collections/seqcrdt_convergence.json` | move-aware sequence CRDT: single-LWW move, concurrent-move/value-edit independence, tombstone convergence |
| `collections/textcrdt_convergence.json` | Fugue/RGA character CRDT: concurrent same-point inserts, sticky tombstone, commutative/idempotent merge, GC |
| `collections/textcrdt_delta_sync.json` | `TextCrdt` delta sync (`#lztextsync`): `version_vector` / `delta_since` / `apply_delta`; bidirectional exchange convergence, whole-snapshot fork identity preservation, idempotent apply |
| `collections/stableid_alignment.json` | manufactured text identity: anchors / content hashes / word-LCS similarity alignment |
| `collections/workqueue_competing_delivery.json` | exclusive FIFO claims, delivery ownership, ack/nack, identity-preserving redelivery |
| `collections/workqueue_lease_deadletter.json` | visibility timeout, at-least-once requeue, max-delivery poison routing to DLQ |

## State Chart Conformance

The `conformance/statechart/` directory contains canonical Harel/SCXML state-chart fixtures (see [State Charts](docs/state-charts.md)). The declarative chart form is normatively defined by [`schemas/statechart.json`](schemas/statechart.json). Unlike IPC fixtures, these are **compute** — a chart is never serialized as a distinct wire kind; only its converged active-state value crosses IPC as an ordinary cell `Payload`. The fixtures fix cross-language *behavior*: each binding loads the declarative `chart`, replays `steps`, and asserts `accepted`, `active`, `matches`, and (when present) `actions` identically.

| Fixture | Covers |
|---------|--------|
| `statechart/flat_cycle.json` | flat transitions, rejection, cycle |
| `statechart/hierarchical_player.json` | nesting, walk-up transition resolution, LCA across levels, `matches()` |
| `statechart/guarded_door.json` | named guards, fail-closed rejection, guard pass |
| `statechart/parallel_regions.json` | orthogonal (AND) regions, per-region transitions, multi-leaf configuration |
| `statechart/history_shallow.json` | shallow history: resume last direct child; first-entry default |
| `statechart/history_deep.json` | deep history: resume full nested leaf configuration |
| `statechart/entry_exit_actions.json` | entry/exit/transition action ordering across LCA boundaries |

## Reliable Sync Conformance

The `conformance/reliable-sync/` directory contains canonical fixtures for the
[Reliable Sync protocol](protocol.md#reliable-sync-lzsync) (`#lzsync`) — the delivery-reliability
layer over the `Snapshot`/`Delta`/`CrdtSync` planes. These are **compute** fixtures: a binding
replays each scenario against its `ResyncCoordinator` / `DurableOutbox` / liveness implementation and
asserts the `expect` fields identically. Fixtures that carry a top-level `wire` frame also pin the
serde round-trip of the two new control frames (`ResyncRequest`, `OutboxAck`, schema
[`schemas/reliable-sync.json`](schemas/reliable-sync.json)) and the multi-epoch `Delta`. The two
control frames MUST round-trip through both `json` and `msgpack`, the same discipline the three
`IpcMessage` variants hold.

| Fixture | Model | Covers |
|---------|-------|--------|
| `reliable-sync/multi_epoch_delta.json` | MultiEpochDelta | a `Delta` with `epoch > base_epoch + 1` applies equal to the unit-delta fold; atomic `last_epoch` advance; gap rule unchanged under span |
| `reliable-sync/resync_gap_converge.json` | ResyncCoordinator | drop a delta suffix → `RequestSnapshot` → apply `Snapshot` → same graph as the no-drop receiver; single request per gap |
| `reliable-sync/idempotent_redelivery.json` | ResyncCoordinator | a re-delivered (`base_epoch < last_epoch`) delta is `Ignore`d; net state unchanged (at-least-once ⇒ exactly-once effect, receiver half) |
| `reliable-sync/outbox_replay_after_crash.json` | DurableOutbox | append-before-send, replay-from-cursor after a simulated crash, `ack_through` retention, send-failure retain; exactly-once effect under replay |
| `reliable-sync/liveness_orset_lww.json` | LivenessCells | OR-set open-set membership + LWW `alive`/lease; whole-editor-death cascade; derived live-doc aggregate converges under retry/re-delivery; per-doc isolation |

The correctness backstop is `lazily-formal` `ReliableSync.lean`; the fixtures are the cross-language
(rs/js/kt) drift catch pinned to that model.

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges `{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version bump is a breaking change; minor additions are additive.

The **Reliable Sync** layer (`#lzsync`) is an **additive, non-breaking** extension: it introduces two
new externally-tagged control frames (`ResyncRequest`, `OutboxAck`) and relaxes the `Delta` epoch
invariant to `epoch >= base_epoch + 1` (the prior `== base_epoch + 1` is the span-1 special case, so
every existing `Delta` frame stays valid). No `protocol_major_version` bump; a peer that does not
advertise a reliable-sync feature flag simply never receives the new control frames.
