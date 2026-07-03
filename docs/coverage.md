# Cross-Language Feature Coverage

This is the **canonical** feature-coverage matrix for the lazily family. Each
binding's README reproduces it; this page is the source of truth. It is a
*status* view (what each port ships today), distinct from the normative
[Binding Conformance Matrix](protocol.md#binding-conformance-matrix), which fixes
what every binding *must* eventually provide.

Legend: ✅ shipped · `~` partial · `—` absent or not applicable (see notes).

| Feature | Rust | Python | Kotlin | JS | Dart | Zig |
|---------|:----:|:------:|:------:|:--:|:----:|:---:|
| Reactive graph — Cell / Slot / Signal / Effect / memo / batch | ✅ | ~ᵃ | ✅ | ✅ | ~ᵇ | ~ᶜ |
| Thread-safe context (lock-backed) | ✅ | ✅ | ✅ | —ᵈ | —ᵈ | ✅ |
| Async reactive context | ✅ | ✅ | ✅ | ✅ | ✅ | —ᵉ |
| Flat state machine | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Harel state charts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Keyed cell collections (`CellMap` / `CellTree`) + reconcile | ✅ | ✅ | ✅ | ✅ | ✅ | ~ᶠ |
| Memoized semantic tree (`SemTree`) | ✅ | — | ✅ | ✅ | — | — |
| Stable-id alignment (manufactured identity) | ✅ | — | ✅ | ✅ | — | — |
| Free-text character CRDT (`TextCrdt`) | ✅ | — | ✅ | ✅ | — | — |
| `TextCrdt` delta sync (`version_vector` / `delta_since` / `apply_delta`) | ✅ | — | ✅ | ✅ | — | — |
| Move-aware sequence CRDT (`SeqCrdt`) | ✅ | — | ✅ | ✅ | — | — |
| Registers (LWW / MV) + `PnCounter` + `CellCrdt` | ✅ | — | ✅ | ✅ | — | — |
| IPC wire — `Snapshot` + `Delta` + `CrdtSync` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Shared-memory blob path (`ShmBlobArena`) | ✅ | ✅ | ✅ | ~ᵍ | ~ᵍ | ✅ |
| Distributed CRDT plane (`CrdtPlaneRuntime` / anti-entropy) | ✅ | — | ✅ | ✅ | ~ʰ | — |
| Distributed plane — WebRTC transport + signaling | ✅ | — | ✅ | ✅ | — | — |
| State projection / mirror | ✅ | — | ✅ | ✅ | — | — |
| C-ABI FFI boundary | ✅ | ✅ | ✅ | —ⁱ | ✅ | ✅ |
| Permission boundary (`PeerPermissions` / `RemoteOp`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Capability negotiation (`SessionHandshake`) | ✅ | — | ✅ | ✅ | ✅ | ✅ |
| Instrumentation / benchmarks | ✅ | — | — | — | — | — |

Convergence and the wire protocol are pinned by the shared conformance fixtures
and JSON Schemas in this repo and the Lean models in
[lazily-formal](formal-model.md).

## Notes

- **ᵃ Python reactive graph:** `Cell` / `Slot` / `Signal` and the memo guard ship;
  `Effect` is async-only and `batch` is provided through the thread-safe context.
- **ᵇ Dart reactive graph:** `Context` / `Slot` / `Cell` / `Signal` ship; there is
  no standalone `Effect` type (observers subscribe on cells) and `batch` is
  scoped to the async context.
- **ᶜ Zig reactive graph:** `Cell` / `Slot` / `Signal` / `Effect` ship; there is
  no public `batch` boundary yet.
- **ᵈ Thread-safe context (JS / Dart):** not applicable — both run on a
  single-threaded runtime (one event loop / one isolate), so a lock-backed
  context has no meaning. This is the concurrency-layer platform carve-out
  (see [protocol.md § Concurrency layers are required](protocol.md#concurrency-layers-are-required)).
- **ᵉ Zig async context:** the async reactor is planned but not yet implemented.
- **ᶠ Zig collections:** `CellMap` / `CellFamily` with atomic move ship; the
  LIS reconciliation op-set and `CellTree` are not yet ported.
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
- **Distributed plane — WebRTC transport + signaling (Rust / Kotlin / JS):** the
  portable stack (signaling protocol + client, the `DataChannel` seam, permission-
  filtering sink/source, in-memory loopback, and the CRDT plane runtime) ships and
  is conformance-tested; the concrete native WebRTC backend is a platform adapter
  (str0m in Rust; the browser `RTCPeerConnection` in JS; a consumer-provided seam
  in Kotlin), matching the reference design where the heavy transport is optional
  behind the seam.
