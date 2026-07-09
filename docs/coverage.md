# Cross-Language Feature Coverage

This is the **canonical** feature-coverage matrix for the lazily family. Each
binding's README reproduces it; this page is the source of truth. It is a
*status* view (what each port ships today), distinct from the normative
[Binding Conformance Matrix](protocol.md#binding-conformance-matrix), which fixes
what every binding *must* eventually provide.

Legend: ✅ shipped · `~` partial · `—` absent or not applicable (see notes).

> The table below is **generated** from [`coverage.json`](../coverage.json) by
> [`scripts/sync-coverage.mjs`](../scripts/sync-coverage.mjs). Edit `coverage.json`
> and run `make coverage-sync` (or `node scripts/sync-coverage.mjs`) to update this
> table and every binding README in one shot; `make coverage-check` guards drift in CI.

<!-- coverage-table:start -->
| Feature | Rust | Python | Kotlin | JS | Dart | Zig | Go | C++ |
| --------- | :----: | :------: | :------: | :--: | :----: | :---: | :--: | :---: |
| Reactive graph — `Cell` / `Slot` / `Signal` / `Effect` / memo / batch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Thread-safe context (lock-backed) | ✅ | ✅ | ✅ | — | — | ✅ | ✅ | ✅ |
| Async reactive context | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Flat state machine | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Harel state charts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed cell collections (`CellMap` / `CellTree`) + reconcile | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Memoized semantic tree (`SemTree`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Stable-id alignment (manufactured identity) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reactive queue (`QueueCell` SPSC/MPSC + `QueueStorage` adapter) | — | — | — | — | — | — | — | — |
| Free-text character CRDT (`TextCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `TextCrdt` delta sync (`version_vector` / `delta_since` / `apply_delta`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Move-aware sequence CRDT (`SeqCrdt`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Lossless tree CRDT core (`LosslessTreeCrdt`, M1) | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| Lossless tree — dotted-frontier anti-entropy | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| Lossless tree — concurrent merge convergence | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| Registers (LWW / MV) + `PnCounter` + `CellCrdt` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| IPC wire — `Snapshot` + `Delta` + `CrdtSync` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shared-memory blob path (`ShmBlobArena`) | ✅ | ✅ | ✅ | ~ | ~ | ✅ | ✅ | ✅ |
| Distributed CRDT plane (`CrdtPlaneRuntime` / anti-entropy) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Distributed plane — WebRTC transport + signaling | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| State projection / mirror | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Causal receipts (`CausalReceipts` outcome projection) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Message-passing + RPC command plane (`command-plane-v1`) | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| C-ABI FFI boundary | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Permission boundary (`PeerPermissions` / `RemoteOp`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Capability negotiation (`SessionHandshake`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Instrumentation / benchmarks | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ |
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
- **ᵈ Thread-safe context (JS / Dart):** not applicable — both run on a
  single-threaded runtime (one event loop / one isolate), so a lock-backed
  context has no meaning. This is the concurrency-layer platform carve-out
  (see [protocol.md § Concurrency layers are required](protocol.md#concurrency-layers-are-required)).
- **ᵉ Zig async context:** Zig removed language `async` and has no suspendable
  executor, so the layer is a task-queue + `settle()` drain surface — the
  synchronous graph's `pending_recompute`/`drainPendingRecompute` generalized
  with revision tracking and the 4-state slot machine (`async_context.zig`).
- **ᶠ Zig collections:** `CellMap` / `CellFamily` with atomic move, `CellTree`
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
