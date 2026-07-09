# Cross-Process Zero-Copy Transport

> `#lzzcpy` — large payloads cross the IPC plane as **descriptors**, not copies.

A `Snapshot` / `Delta` / `CrdtSync` message may carry large cell/slot payloads
(an Arrow record-batch, an image, a serialized sub-document). Copying those bytes
through the wire codec on every hop is the dominant cost of a distributed lazily
deployment. The zero-copy transport instead **spills** a large payload to a **blob
backend** and ships a small `Descriptor`; the receiver **resolves** the descriptor
against the same backend and reads the bytes in place — no copy, no checksum
recompute.

This chapter defines the transport model, the **pluggable backend (adapter)
contract**, and the wire `Descriptor`. The invariants are proven in
[`lazily-formal/LazilyFormal/ZeroCopyTransport.lean`](../formal-model.md)
(spill-then-resolve identity, backend isolation, ABA/generation safety, checksum
integrity) and pinned by
[`conformance/delta_zero_copy_arrow.json`](../conformance.md).

## Model

```
 producer                                            receiver
 ────────                                            ────────
 bytes ──spill──▶ backend.write ──▶ Descriptor        Descriptor ──resolve──▶ backend.read_view ──▶ bytes (view)
                     (mint id+gen+csum)    │                              (kind routes to the right backend)
                                           └──────── wire (msgpack) ──────▶
```

1. **Spill (producer).** For an `IpcValue` / `NodeState` payload above a
   session-defined threshold, the producer calls `backend.write(bytes)` and gets
   a `Descriptor` (`{kind, offset, len, generation, epoch, checksum}`). It puts
   the descriptor in the message as `SharedBlob` instead of `Inline` bytes.
2. **Wire.** Only the descriptor crosses the codec — the message stays small.
3. **Resolve (receiver).** The receiver reads `descriptor.kind`, routes to the
   matching backend, and calls `backend.read_view(descriptor)` → a `const` view
   of the **backend's own** bytes. No copy, no checksum recompute (the checksum
   was computed once at write and is validated against the cached value).

Threshold policy: payloads below the threshold stay `Inline` (copied through the
codec — cheaper than a backend round-trip for tiny values). The threshold is a
session/deployment knob, not a protocol constant.

## The wire `Descriptor`

The descriptor is `ShmBlobRef` ([`schemas/defs.json`](../schemas.md)) extended
with an optional **`backend`** discriminator:

| field | type | meaning |
|---|---|---|
| `offset`, `len` | u64 | byte range within the backend's resolved buffer |
| `generation` | u64 | ABA guard — a slot reused at a later generation is not misread |
| `epoch` | u64 | validity epoch (advanced on backend compaction/restart) |
| `checksum` | u64 | FNV-1a-64 over the bytes (computed once at write, validated at read) |
| `backend` | enum `shm` \| `arrow` \| `in_process` (optional, **default `shm`**) | which pluggable backend resolves this descriptor |

`backend` is **optional and defaults to `shm`**, so every legacy descriptor
validates unchanged — the transport is a strict superset of the pre-existing
shared-memory blob path. A receiver routes resolution by `kind`: a `shm`
descriptor never resolves in an Arrow table and vice versa (the
`resolve_wrong_backend` theorem).

## Pluggable backends (adapters)

A backend is anything that satisfies the **blob-backend contract**:

| operation | contract |
|---|---|
| `write(bytes) → Descriptor` | mint a fresh id at the current generation/epoch, store the bytes immutably, return a descriptor whose checksum is the bytes' FNV-1a-64 |
| `read_view(Descriptor) → const bytes*` | return the stored bytes iff `kind + id + generation + epoch + checksum` all match; `nullptr` otherwise. **No copy, no recompute** |
| lifecycle | advance `epoch` on compaction/restart; never mutate a stored buffer in place (entries are immutable + stable-addressed for the lifetime a descriptor may reference them) |

Because the contract is stated only over a backend's issued-blob table + the
`read_view` lookup, the transport theorems hold **uniformly for every backend**
that maintains the contract — this is the universal guarantee no single-adapter
fixture can establish. Three backends ship / are anticipated:

| `backend` | what holds the bytes | cross-process? | typical use |
|---|---|---|---|
| `shm` | POSIX shared-memory region (`shm_open` + `mmap`) | yes (same host) | the default — host ↔ binding / peer ↔ peer on one host |
| `arrow` | Apache Arrow IPC stream / Flight-resolved buffer | yes (Arrow's zero-copy columnar IPC) | analytics / columnar payloads — the bytes are an Arrow IPC stream the receiver imports as an `Array`/`RecordBatch` with no copy |
| `in_process` | an in-process arena (single address space) | no | the FFI host ↔ a binding loaded in the same process (editor plugin) |

An **Apache Arrow adapter** implements the contract by holding spilled payloads
as Arrow buffers and resolving a descriptor to the buffer's raw bytes (or, for
columnar consumers, directly to the Arrow `Array` — the descriptor's bytes *are*
an Arrow IPC stream). Because Arrow's IPC format is itself zero-copy across a
shared buffer, `shm` and `arrow` compose: an Arrow batch can live in a `shm`
region and be resolved by either backend. New backends (e.g. a RDMA/verbs
adapter, a Cuda IPC adapter) plug in by implementing the contract and adding a
`backend` enum value — no transport or codec change.

## Backend-agnostic invariants (proven)

The formal model parameterises over an abstract backend and proves, for **any**
backend satisfying the contract ([`ZeroCopyTransport.lean`](../formal-model.md)):

- **`resolve_write` / `transport_roundtrip`** — resolving the descriptor a
  backend minted via `write` returns exactly the bytes written. The consumer
  reads the backend's own bytes, not a copy: the end-to-end zero-copy guarantee.
- **`resolve_wrong_backend`** — a descriptor of one `kind` never resolves against
  a different backend's table → receivers route by `kind`.
- **`resolve_stale_generation`** — a slot reused at a later generation (or a
  stale ref to a freed slot) does not resolve against the new occupant (ABA
  safety via `generation`).
- **`resolve_corrupt_checksum`** — a descriptor corrupted in transit is rejected
  rather than resolving to the wrong bytes.

## Conformance

- [`conformance/delta_zero_copy_arrow.json`](../conformance.md) — a `Delta` whose
  `SlotValue` payload is a `SharedBlob` with `backend: "arrow"`, validating the
  optional discriminator against `schemas/delta.json`.
- [`conformance/delta_shared_blob.json`](../conformance.md) — the legacy
  `backend`-absent (= `shm`) form, unchanged → backward compatibility.

## Relationship to the wire codec

The transport is codec-agnostic but pairs with the msgpack codec: spill replaces
`Inline` bytes (which the codec would copy) with a small `SharedBlob` descriptor
(which the codec serializes as a handful of integers). The codec already
distinguishes `Inline` vs `SharedBlob`; the transport adds the **policy** (when
to spill) and the **backend contract** (how `SharedBlob` is resolved without a
copy). See [Wire Protocol](protocol.md).
