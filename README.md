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
| Reactive graph [^reactive-graph] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed-map materialization [^keyed-map-materialization] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe keyed map [^thread-safe-keyed-map] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Async keyed map [^async-keyed-map] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed-map sync [^keyed-map-sync] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe context [^thread-safe-context] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Async reactive context [^async-reactive-context] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Flat state machine [^flat-state-machine] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Harel state charts [^harel-state-charts] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed reactive maps [^keyed-reactive-maps] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ReactiveMap core — single-threaded [^reactivemap-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ |
| ReactiveMap core — thread-safe [^reactivemap-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ReactiveMap core — async [^reactivemap-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Exact-key dependency availability [^exact-key-dependency-availability] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Atomic ordered move [^atomic-ordered-move] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Memoized semantic tree [^memoized-semantic-tree] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stable-id alignment [^stable-id-alignment] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue core — single-threaded [^reactive-queue-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue core — thread-safe [^reactive-queue-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue core — async [^reactive-queue-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Broadcast topic core — single-threaded [^broadcast-topic-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Broadcast topic core — thread-safe [^broadcast-topic-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Broadcast topic core — async [^broadcast-topic-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Work queue core — single-threaded [^work-queue-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Work queue core — thread-safe [^work-queue-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Work queue core — async [^work-queue-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Merge algebra [^merge-algebra] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| RelayCell [^relaycell] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Free-text character CRDT [^free-text-character-crdt] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TextCrdt delta sync [^textcrdt-delta-sync] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CrdtTree lossless document [^crdttree-lossless-document] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Move-aware sequence CRDT [^move-aware-sequence-crdt] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree CRDT core [^lossless-tree-crdt-core] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — anti-entropy [^lossless-tree-anti-entropy] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — merge convergence [^lossless-tree-merge-convergence] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Registers (LWW/MV) + PnCounter [^registers] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| IPC wire — Snapshot/Delta/CrdtSync [^ipc-wire] | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | ✅ |
| Frame codec — json [^frame-codec-json] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Frame codec — msgpack [^frame-codec-msgpack] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Frame codec — postcard [^frame-codec-postcard] | ✅ | — | — | — | — | — | — | — | — |
| NodeId/PeerId exact-representation [^nodeid-peerid-exact-representation] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| NodeKey null-leniency [^nodekey-null-leniency] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shared-memory blob path [^shared-memory-blob-path] | ✅ | ✅ | ✅ | ~ | ~ | ✅ | ✅ | ~ | ✅ |
| Cross-process zero-copy transport [^cross-process-zero-copy-transport] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed CRDT plane [^distributed-crdt-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reliable sync [^reliable-sync] | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ |
| Storage-independent durable outbox [^storage-independent-durable-outbox] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reliable-sync transport seam [^reliable-sync-transport-seam] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed plane — WebRTC [^distributed-plane-webrtc] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| State projection / mirror [^state-projection-mirror] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Causal receipts [^causal-receipts] | ~ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Message-passing + RPC command plane [^message-passing-rpc-command-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ |
| C-ABI FFI boundary [^c-abi-ffi-boundary] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Permission boundary [^permission-boundary] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Capability negotiation [^capability-negotiation] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Instrumentation / benchmarks [^instrumentation-benchmarks] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Temporal sources [^temporal-sources] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Rate-shaping operators [^rate-shaping-operators] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Membership + failure detection [^membership-failure-detection] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed coordination [^distributed-coordination] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Presence + ephemeral plane [^presence-ephemeral-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stream windowing [^stream-windowing] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fault tolerance [^fault-tolerance] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib Timer [^portable-stdlib-timer] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib Timeout [^portable-stdlib-timeout] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Portable stdlib RevisionBarrier [^portable-stdlib-revision-barrier] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Embedded-service plane [^embedded-service-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive ingress [^reactive-ingress] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ingress — thread-safe [^ingress-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Ingress — async [^ingress-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

[^reactive-graph]: Reactive graph — two cell kinds (nodes `SourceCell` / `ComputedCell`; handles `Source<T, M>` / `Computed<T>`) + `Effect` sink + eager `Computed` (`computed().eager()`) / all cells guarded / batch
[^keyed-map-materialization]: Keyed-map materialization (`ComputedMap`) — mint-on-access derived slots: transparency + deferral (`#lzmatmode`)
[^thread-safe-keyed-map]: Thread-safe keyed map (`ThreadSafeComputedMap`) — `Send + Sync` + materialization confluence (`#lzmatmode`)
[^async-keyed-map]: Async keyed map (`AsyncComputedMap`) — eventual transparency (`#lzmatmode`)
[^keyed-map-sync]: Keyed-map sync — membership propagation + materialize-on-ingest + derived-aggregate transparency (`#lzfamilysync`)
[^thread-safe-context]: Thread-safe context (lock-backed)
[^async-reactive-context]: Async reactive context
[^flat-state-machine]: Flat state machine
[^harel-state-charts]: Harel state charts
[^keyed-reactive-maps]: Keyed reactive maps (`ReactiveMap`: `SourceMap` / `ComputedMap`) + `SourceTree` + reconcile
[^reactivemap-core-single-threaded]: `ReactiveMap` **Core surface** — single-threaded flavor (cell-model.md § Core surface vs. binding extensions)
[^reactivemap-core-thread-safe]: `ReactiveMap` **Core surface** — thread-safe flavor (ordering + membership reactivity)
[^reactivemap-core-async]: `ReactiveMap` **Core surface** — async flavor (ordering + membership reactivity)
[^exact-key-dependency-availability]: Exact-key dependency availability (`DependencyMap`: observe before publish, unrelated-key isolation, stable identity; `#lzdependencyavailability`)
[^atomic-ordered-move]: Atomic ordered move replayed against **all three flavors** (`cellmap_atomic_move` + `cellmap_independence`)
[^memoized-semantic-tree]: Memoized semantic tree (`SemTree`)
[^stable-id-alignment]: Stable-id alignment (manufactured identity)
[^reactive-queue-core-single-threaded]: Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — single-threaded flavor
[^reactive-queue-core-thread-safe]: Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle)
[^reactive-queue-core-async]: Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) **Core surface** — async flavor (reader kinds + eventual transparency)
[^broadcast-topic-core-single-threaded]: Broadcast topic (`TopicCell`) **Core surface** — single-threaded flavor — independent cursors + durable replay + safe GC (`#lztopiccell`)
[^broadcast-topic-core-thread-safe]: Broadcast topic (`TopicCell`) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle)
[^broadcast-topic-core-async]: Broadcast topic (`TopicCell`) **Core surface** — async flavor (reader kinds + eventual transparency)
[^work-queue-core-single-threaded]: Competing-consumer work queue (`WorkQueueCell`) **Core surface** — single-threaded flavor — exclusive leases + ack/nack + redelivery + DLQ (`#lzworkqueue`)
[^work-queue-core-thread-safe]: Competing-consumer work queue (`WorkQueueCell`) **Core surface** — thread-safe flavor (reader kinds + closure lifecycle)
[^work-queue-core-async]: Competing-consumer work queue (`WorkQueueCell`) **Core surface** — async flavor (reader kinds + eventual transparency)
[^merge-algebra]: Merge algebra + `Source<T, M>` — associative `MergePolicy` (`KeepLatest`/`Sum`/`Max`/`SetUnion`/`RawFifo`), `Cell ≡ Source<KeepLatest>`, read-any-cell/write-`Source` split (`#relaycell`)
[^relaycell]: RelayCell — conflating relay + `BackpressurePolicy` + `SpillStore` + `Transport` + Inbox/Outbox + Rate/Window/Expiry/Priority/keyed policies (`#relaycell`)
[^free-text-character-crdt]: Free-text character CRDT (`TextCrdt`)
[^textcrdt-delta-sync]: `TextCrdt` delta sync (`version_vector` / `delta_since` / `apply_delta`)
[^crdttree-lossless-document]: `CrdtTree` lossless document contract (`#lzcrdttree`)
[^move-aware-sequence-crdt]: Move-aware sequence CRDT (`SeqCrdt`)
[^lossless-tree-crdt-core]: Lossless tree CRDT core (`LosslessTreeCrdt`, M1)
[^lossless-tree-anti-entropy]: Lossless tree — dotted-frontier anti-entropy
[^lossless-tree-merge-convergence]: Lossless tree — concurrent merge convergence
[^registers]: Registers (LWW / MV) + `PnCounter` + `CellCrdt`
[^ipc-wire]: IPC wire — `Snapshot` + `Delta` + `CrdtSync`
[^frame-codec-json]: Frame codec — `json` **reference codec**: dependency-free interop floor, FFI baseline form, byte-canonical (**MUST**) — executable round-trip obligation (`conformance/codec/frame_roundtrip_json.json`, `#lzmsgpackparity`)
[^frame-codec-msgpack]: Frame codec — `msgpack` **cross-language binary default**: externally-tagged frame over named-field maps, semantic (not byte-identical) round-trip (**MUST**) — executable round-trip obligation (`conformance/codec/frame_roundtrip_msgpack.json`, `#lzmsgpackparity`). Shipping *a* MessagePack codec does not earn this mark: lazily-cpp read `~` here while its private internally-tagged framing wore the token, and only flipped once it shipped the spec wire (`#lzcppmsgpackwire`)
[^frame-codec-postcard]: Frame codec — `postcard` positional same-schema fast path: smallest + byte-canonical, not cross-language (**MAY**)
[^nodeid-peerid-exact-representation]: `NodeId` / `PeerId` exact-representation bound (**MUST**) — a decoder that cannot represent a received identifier exactly rejects the frame rather than rounding it (`conformance/codec/nodeid_exact_range.json`, `#lzspecdecoderbound`). A binding's exact range MAY be narrower than the `u64` wire type; ✅ means it refuses outside that range instead of substituting a neighbouring id, not that it carries the full `u64`. Exact ranges: full `u64` in Rust / Zig / C#, unbounded in Python, `[0, 2^63)` in Kotlin / Go / C++, `[0, 2^53)` in JS, and platform-split in Dart (63-bit on the VM, 53-bit on web). protocol.md stated only the PRODUCER half until this audit, and two C++ decoders were substituting rather than refusing.
[^nodekey-null-leniency]: `NodeKey` null-leniency on decode (**MUST**) — omit-when-absent binds the ENCODER; a decoder reads both an omitted `key` and an explicit `key: null` as absent, refusing neither and constructing a key from neither (`conformance/codec/nodekey_null_leniency.json`, `#lzkeynullstrict`). Replayed on BOTH optional-key sites (`NodeSnapshot`, the `NodeAdd` delta op) in both codecs, and the fixture pins the RE-ENCODED field set as well: reading null as absent and writing it back out is a correct decode with a non-conforming encoder. Before the audit lazily-py and lazily-zig refused the null form, and lazily-kt decoded it into a real key named `null` — all three had the same field right on `CrdtOp`, in the same file.
[^shared-memory-blob-path]: Shared-memory blob path (`ShmBlobArena`)
[^cross-process-zero-copy-transport]: Cross-process zero-copy transport (`BlobBackend` / shm / arrow)
[^distributed-crdt-plane]: Distributed CRDT plane (`CrdtPlaneRuntime` / anti-entropy)
[^reliable-sync]: Reliable sync — resync coordinator + at-least-once durable outbox + OR-set/LWW liveness (`#lzsync`)
[^storage-independent-durable-outbox]: Storage-independent durable outbox (`OutboxStore` + shared outbox protocol; SQLite/Room/IndexedDB/file adapters)
[^reliable-sync-transport-seam]: Reliable-sync transport seam + full-duplex `SyncDriver` loop (`IpcSink`/`IpcSource`, `#sync-driver`)
[^distributed-plane-webrtc]: Distributed plane — WebRTC transport + signaling
[^state-projection-mirror]: State projection / mirror
[^causal-receipts]: Causal receipts (`CausalReceipts` outcome projection)
[^message-passing-rpc-command-plane]: Message-passing + RPC command plane (`command-plane-v1`)
[^c-abi-ffi-boundary]: C-ABI FFI boundary
[^permission-boundary]: Permission boundary (`PeerPermissions` / `RemoteOp`)
[^capability-negotiation]: Capability negotiation (`SessionHandshake`)
[^instrumentation-benchmarks]: Instrumentation / benchmarks
[^temporal-sources]: Temporal sources — `TimerCell` / `IntervalCell` / `CronCell` / `DeadlineCell` over a logical clock (`#lztime`)
[^rate-shaping-operators]: Rate-shaping operators — `DebounceCell` / `ThrottleCell` / `SampleCell` / `ProbabilisticSampleCell` (`#lzrateshape`)
[^membership-failure-detection]: Membership + failure detection — `MembershipCell` (SWIM + Phi-accrual) / `PeerSet` / `PeerChangeEvent` (`#lzmemb`)
[^distributed-coordination]: Distributed coordination — `LeaseCell` / `LeaderCell` / `LockCell` / `SemaphoreCell` / `BarrierCell`+`QuorumCell` (`#lzcoord`)
[^presence-ephemeral-plane]: Presence + ephemeral plane — `PresenceCell` / `AwarenessCell` / `EphemeralCell` + `Ephemeral`/`Durable` markers (`#lzpresence`)
[^stream-windowing]: Stream windowing — `TumblingWindow` / `SlidingWindow` / `SessionWindow` over the merge algebra (`#lzwindow`)
[^fault-tolerance]: Fault tolerance — `CircuitBreakerCell` / `RetryPolicyCell` / `BulkheadCell` / `TimeoutCell` (`#lzresilience`)
[^portable-stdlib-timer]: Portable stdlib `Timer` (`stdlib_timer_v1`) — canonical fixture + mutation-gate verified
[^portable-stdlib-timeout]: Portable stdlib caller-driven `Timeout<T>` (`stdlib_timeout_v1`) — distinct from reactive `TimeoutCell`
[^portable-stdlib-revision-barrier]: Portable stdlib `RevisionBarrier` (`stdlib_revision_barrier_v1`) — register/recheck lost-wakeup guard
[^embedded-service-plane]: Embedded-service plane — `HealthCell` / `ReadinessCell` / `DiscoveryCell` / `ServiceRegistry` (`#lzservice`)
[^reactive-ingress]: Transport-agnostic reactive ingress (`IngressCell`) — keyed lifecycle scopes, generation/sequence/freshness envelopes, reorder buffer, accepted/dropped/error receipt readers (`#designimplementtransport`)
[^ingress-thread-safe]: Ingress family — `Send + Sync` flavor (`ThreadSafeIngressCell`): one frontier walk per admission (`#designimplementtransport`)
[^ingress-async]: Ingress family — async flavor (`AsyncIngressCell`): admission is not async-coloured (`#designimplementtransport`)
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
| `statechart/malformed_rejected.json` | authoritative `kind`, strict field types, and declared-state reference closure |

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
| `reliable-sync/outbox_journal_decode.json` | FileOutboxStore | a complete unknown interior opcode is rejected; one torn trailing record is forgiven without losing earlier complete records |
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
