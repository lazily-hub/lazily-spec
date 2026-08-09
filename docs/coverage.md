# Cross-Language Feature Coverage

This is the **canonical** feature-coverage matrix for the lazily family. Each
binding's README reproduces it; this page is the source of truth. It is a
*status* view (what each port ships today), distinct from the normative
[Binding Conformance Matrix](protocol.md#binding-conformance-matrix), which fixes
what every binding *must* eventually provide.

Legend: ✅ shipped · `~` partial · `—` absent · `⊘` not applicable (see notes).

> The table below is **generated** from [`coverage.json`](../coverage.json) by
> [`scripts/sync-coverage.mjs`](../scripts/sync-coverage.mjs). Edit `coverage.json`
> and run `make coverage-sync` (or `node scripts/sync-coverage.mjs`) to update this
> table and every binding README in one shot; `make coverage-check` guards drift in CI.

<!-- coverage-table:start -->
#### Summary — family × language

| Family | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive graph | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ~ |
| Materialization | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Family sync | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Statecharts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Keyed collections | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Reactive queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Broadcast topic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Work queue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| CRDT data types | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Lossless tree | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Egress | ✅ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | — |
| Ingress | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Wire codec | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | ✅ | — |
| Transport & FFI | ✅ | ✅ | ✅ | ~ | ~ | ✅ | ✅ | ~ | ✅ | — |
| Message passing | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Reliable sync | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | — |
| Distributed plane | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Causal receipts | ~ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Security boundary | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Membership | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Coordination | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Presence | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Temporal | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Rate shaping | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Windowing | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Resilience | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Portable stdlib | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Service plane | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Instrumentation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

**Roll-up rule:** a family cell is `✅` only when *every required* row in that family is `✅`; `~` when the family is mixed (some shipped or partial); `—` when no required row is shipped or partial; `⊘` only when every required row in the family is not applicable. Rows the spec marks **MAY** (`optional`, shown as *opt* below) are excluded from the roll-up — declining an optional feature is not a gap.

#### Reactive graph

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive graph [^reactive-graph] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ~ |
| Thread-safe context [^thread-safe-context] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Async reactive context [^async-reactive-context] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Merge algebra [^merge-algebra] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Materialization

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Keyed-map materialization [^keyed-map-materialization] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Thread-safe keyed map [^thread-safe-keyed-map] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Async keyed map [^async-keyed-map] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Family sync

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Keyed-map sync [^keyed-map-sync] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Statecharts

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Flat state machine [^flat-state-machine] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Harel state charts [^harel-state-charts] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Keyed collections

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Keyed reactive maps [^keyed-reactive-maps] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| ReactiveMap core — single-threaded [^reactivemap-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| ReactiveMap core — thread-safe [^reactivemap-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| ReactiveMap core — async [^reactivemap-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Exact-key dependency availability [^exact-key-dependency-availability] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Atomic ordered move [^atomic-ordered-move] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Memoized semantic tree [^memoized-semantic-tree] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Stable-id alignment [^stable-id-alignment] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Reactive queue

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive queue core — single-threaded [^reactive-queue-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Reactive queue core — thread-safe [^reactive-queue-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Reactive queue core — async [^reactive-queue-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Broadcast topic

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Broadcast topic core — single-threaded [^broadcast-topic-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Broadcast topic core — thread-safe [^broadcast-topic-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Broadcast topic core — async [^broadcast-topic-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Work queue

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Work queue core — single-threaded [^work-queue-core-single-threaded] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Work queue core — thread-safe [^work-queue-core-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Work queue core — async [^work-queue-core-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### CRDT data types

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Free-text character CRDT [^free-text-character-crdt] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| TextCrdt delta sync [^textcrdt-delta-sync] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| CrdtTree lossless document [^crdttree-lossless-document] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Move-aware sequence CRDT [^move-aware-sequence-crdt] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |
| Registers (LWW/MV) + PnCounter [^registers] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Lossless tree

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Lossless tree CRDT core [^lossless-tree-crdt-core] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Lossless tree — anti-entropy [^lossless-tree-anti-entropy] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Lossless tree — merge convergence [^lossless-tree-merge-convergence] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Egress

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive egress [^reactive-egress] | ✅ | — | — | — | — | — | — | — | — | — |
| Egress — thread-safe [^egress-thread-safe] | ✅ | — | — | — | — | — | — | — | — | — |
| Egress — async [^egress-async] | ✅ | — | — | — | — | — | — | — | — | — |
| RelayCell [^relaycell] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Ingress

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reactive ingress [^reactive-ingress] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Ingress — thread-safe [^ingress-thread-safe] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Ingress — async [^ingress-async] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Wire codec

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| IPC wire — Snapshot/Delta/CrdtSync [^ipc-wire] | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | ✅ | — |
| Frame codec — json [^frame-codec-json] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Frame codec — msgpack [^frame-codec-msgpack] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Frame codec — postcard *(opt)* [^frame-codec-postcard] | ✅ | — | — | — | — | — | — | — | — | — |
| NodeId/PeerId exact-representation [^nodeid-peerid-exact-representation] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| NodeKey null-leniency [^nodekey-null-leniency] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Capability negotiation [^capability-negotiation] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Transport & FFI

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Shared-memory blob path [^shared-memory-blob-path] | ✅ | ✅ | ✅ | ~ | ~ | ✅ | ✅ | ~ | ✅ | — |
| Cross-process zero-copy transport [^cross-process-zero-copy-transport] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| C-ABI FFI boundary [^c-abi-ffi-boundary] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Message passing

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Message-passing + RPC command plane [^message-passing-rpc-command-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ | — |

#### Reliable sync

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Reliable sync [^reliable-sync] | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | ~ | — |
| Storage-independent durable outbox [^storage-independent-durable-outbox] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Reliable-sync transport seam [^reliable-sync-transport-seam] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Distributed plane

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Distributed CRDT plane [^distributed-crdt-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Distributed plane — WebRTC [^distributed-plane-webrtc] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| State projection / mirror [^state-projection-mirror] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Causal receipts

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Causal receipts [^causal-receipts] | ~ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Security boundary

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Permission boundary [^permission-boundary] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Membership

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Membership + failure detection [^membership-failure-detection] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Coordination

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Distributed coordination [^distributed-coordination] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Presence

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Presence + ephemeral plane [^presence-ephemeral-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Temporal

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Temporal sources [^temporal-sources] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Rate shaping

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Rate-shaping operators [^rate-shaping-operators] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Windowing

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Stream windowing [^stream-windowing] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Resilience

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Fault tolerance [^fault-tolerance] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Portable stdlib

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Portable stdlib Timer [^portable-stdlib-timer] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Portable stdlib Timeout [^portable-stdlib-timeout] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| Portable stdlib RevisionBarrier [^portable-stdlib-revision-barrier] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Service plane

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Embedded-service plane [^embedded-service-plane] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

#### Instrumentation

| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ | C# | GDScript |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: | :--: | :--------: |
| Instrumentation / benchmarks [^instrumentation-benchmarks] | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |

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
[^reactive-egress]: Transport-agnostic reactive egress (`EgressCore`) — monotone sequence assignment, bounded unacknowledged window, cumulative ACK watermark, bounded retry/backoff/exhaustion, producer-generation fence (`#lzegress`)
[^egress-thread-safe]: Egress family — `Send + Sync` flavor (`ThreadSafeEgressCell`): delivery authority stays in the shared core, one attached transport Effect per incarnation (`#lzegress`)
[^egress-async]: Egress family — async flavor (`AsyncEgressCell`): the delivery-state readers stay synchronous Computeds; only the transport attachment is async-coloured (`#lzegress`)
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

Convergence and the wire protocol are pinned by the shared conformance fixtures
and JSON Schemas in this repo and the Lean models in
[lazily-formal](formal-model.md).

## Notes

- **ᵃ Python reactive graph:** `Cell` / `Slot` / `Signal` / `Effect` (sync) and
  the top-level `batch(run)` boundary ship; the `!=` PartialEq memo guard applies
  to cells, slots, and signals. The async counterpart (`AsyncEffect`) queues
  reruns at the batch boundary for `asyncio` reactors.
- **ᵇ Dart reactive graph:** `Context` / `Slot` / `Cell` / `Signal` ship; there is
  no standalone `Effect` type (observers subscribe on cells) and `batch` is
  scoped to the async context.
- **ᶜ Zig reactive graph:** `Cell` / `Slot` / `Signal` / `Effect` and the public
  `batch(run)` boundary ship (`context.zig` coalesces the eager-recompute drain
  at the outermost batch exit).
- **ᵈ Serialized context (JS / Dart) — decision:** both are meaningful as
`serialized`, realm-local execution flavors, not as `shared-graph` contexts.
They are scored when their own surfaces replay the portable Core fixtures, and
are excluded from cross-thread shared-graph stress/model-check tests. A duplicate
wrapper is not sufficient by itself: unsupported Core features remain staged,
and runner-local locks/dictionaries cannot stand in for them. Either binding may
remove the flavor and declare it absent; while it advertises the flavor, it must
join every feature peer group it actually supports. See
[protocol.md § Concurrency layers are required](protocol.md#concurrency-layers-are-required)
for the conditional layer requirement and
[reactive-graph.md § Declared context capabilities](reactive-graph.md#declared-context-capabilities)
for the `serialized` / `shared-graph` distinction.
- **ᵉ Zig async context:** Zig removed language `async` and has no suspendable
  executor, so the layer is a task-queue + `settle()` drain surface — the
  synchronous graph's `pending_recompute`/`drainPendingRecompute` generalized
  with revision tracking and the 4-state slot machine (`async_context.zig`).
- **ᶠ Zig collections:** `SourceMap` / `ComputedMap` with atomic move, `SourceTree`
  (per-level membership/order reactivity, atomic child move), and the
  LIS-move-minimized reconcile op-set all ship (`collection.zig`,
  `cell_tree.zig`, `reconcile.zig`).
- **ᵍ Shared-memory blob path (JS / Dart):** carry `ShmBlobRef` wire references
  but no host-side `ShmBlobArena` — the I/O-channel fallback of the
  shared-memory carve-out
  (see [protocol.md § Shared-memory payload path is required](protocol.md#shared-memory-payload-path-is-required)).
- **ʰ Dart distributed CRDT plane:** the `CrdtPlane` engine (HLC / stamp
  frontier / stability watermark) ships, but is not yet wired to live
  `merge: crdt` root cells.
- **ⁱ C-ABI FFI (JS):** platform carve-out `ffi = none` — browser/Worker JS has
  no shared in-process C ABI. The full state plane (including `CrdtSync`) still
  flows over IPC / WebSocket / WebRTC
  (see [protocol.md § C-ABI FFI is required](protocol.md#c-abi-ffi-is-required)).
- **Distributed plane — WebRTC transport + signaling (Rust / Kotlin / JS / Zig):** the
  portable stack (signaling protocol + client, the `DataChannel` seam, permission-
  filtering sink/source, in-memory loopback, and the CRDT plane runtime) ships and
  is conformance-tested; the concrete native WebRTC backend is a platform adapter
  (str0m in Rust; the browser `RTCPeerConnection` in JS; a consumer-provided seam
  in Kotlin and Zig), matching the reference design where the heavy transport is optional
  behind the seam.
