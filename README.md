# lazily-spec

Language-agnostic wire protocol specification for the **lazily** reactive signals family.

This repo defines the canonical message schemas shared across all lazily implementations:

- **lazily-rs** (Rust)
- **lazily-py** (Python)
- **lazily-zig** (Zig)
- **lazily-js** (TypeScript / Cloudflare Worker)
- **lazily-kt** (Kotlin/JVM)
- **lazily-dart** (Dart)
- **lazily-go** (Go)
- **lazily-cpp** (C++)

## Feature Set

The full `lazily` capability set and its cross-language coverage across every
binding (`lazily-rs`, `lazily-py`, `lazily-kt`, `lazily-js`, `lazily-dart`,
`lazily-zig`, `lazily-go`, `lazily-cpp`). Legend: ✅ shipped · `~` partial · `—` absent or not applicable.
This table is generated from [`coverage.json`](coverage.json) — the canonical
matrix with per-cell notes and platform carve-outs lives in
[Cross-Language Coverage](docs/coverage.md). Edit `coverage.json` and run
`make coverage-sync` to update it in one shot; `make coverage-check` guards drift.

<!-- coverage-table:start -->
| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: |
| Reactive graph — `Cell` / `Slot` / `Signal` / `Effect` / memo / batch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive family (`ReactiveFamily`) — keyed cell/slot family + materialization mode (`#lzmatmode`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe reactive family (`ThreadSafeReactiveFamily`) — `Send + Sync` keyed family + materialization confluence (`#lzmatmode`) | ✅ | — | — | — | — | — | — | — |
| Async reactive family (`AsyncReactiveFamily`) — keyed family + eventual transparency (`#lzmatmode`) | ✅ | — | — | — | — | — | — | — |
| Thread-safe context (lock-backed) | ✅ | ✅ | ✅ | — | — | ✅ | ✅ | ✅ |
| Async reactive context | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Flat state machine | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Harel state charts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed cell collections (`CellMap` / `CellTree`) + reconcile | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Memoized semantic tree (`SemTree`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stable-id alignment (manufactured identity) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Free-text character CRDT (`TextCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TextCrdt` delta sync (`version_vector` / `delta_since` / `apply_delta`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Move-aware sequence CRDT (`SeqCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree CRDT core (`LosslessTreeCrdt`, M1) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — dotted-frontier anti-entropy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree — concurrent merge convergence | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Registers (LWW / MV) + `PnCounter` + `CellCrdt` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| IPC wire — `Snapshot` + `Delta` + `CrdtSync` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shared-memory blob path (`ShmBlobArena`) | ✅ | ✅ | ✅ | ✅ | ~ | ✅ | ✅ | ✅ |
| Cross-process zero-copy transport (`BlobBackend` / shm / arrow) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed CRDT plane (`CrdtPlaneRuntime` / anti-entropy) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed plane — WebRTC transport + signaling | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| State projection / mirror | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Causal receipts (`CausalReceipts` outcome projection) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Message-passing + RPC command plane (`command-plane-v1`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| C-ABI FFI boundary | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Permission boundary (`PeerPermissions` / `RemoteOp`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Capability negotiation (`SessionHandshake`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Instrumentation / benchmarks | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
<!-- coverage-table:end -->

CRDT convergence and the wire protocol are pinned by the shared conformance fixtures
and JSON Schemas in `lazily-spec` and the Lean models in `lazily-formal`.
## Binding Conformance

Every binding MUST implement the layers in the [Binding Conformance Matrix](protocol.md#binding-conformance-matrix).
The **distributed CRDT plane (`CrdtSync`)** and the full keyed cell collections layer
(`CellMap`, `CellTree`, keyed reconciliation) are unconditional — implementable on any
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

## Versioning

Protocol versioning follows the IPC capability negotiation: each session exchanges `{ protocol_id, protocol_major_version, codec }` before any graph state flows. A major version bump is a breaking change; minor additions are additive.
