# lazily Cell Model Specification

Normative source of truth for cell kinds and the multi-write merge mechanism.

This chapter defines the cell-kind model that the [Wire Protocol](protocol.md) serves.
It is upstream of every transport: IPC, FFI, signaling, and the distributed plane all
carry cells whose convergence semantics are fixed here. The
[Distributed: CRDT Cell Plane](protocol.md#distributed-crdt-cell-plane) section
specifies `merge: crdt` — the *first* multi-write merge mechanism defined below.

## The single axis: writer count

A lazily graph is a set of **cells**. The only axis that determines how a cell's value
converges is **how many writers can concurrently produce a value for it** — *not*
whether those writers are local or remote, in one process or many.

| Kind | Concurrent writers | Convergence | Merge |
|------|--------------------|-------------|-------|
| **Single-writer** (`local` / `direct`) | exactly one | direct reactive push/pull | none |
| **Multi-write** | potentially many | `merge: <mechanism>` ingress | mechanism-defined |

The kind is a **static property of what the cell represents**, chosen at definition
time. There is no dynamic per-write mode switching: a multi-write cell stays
multi-write even when only one writer is currently live, and a single-writer cell never
becomes multi-write because a value happens to arrive over a wire.

## Single-writer cells (`local` / `direct`)

A single-writer cell has **exactly one** writer:

- this runtime's own derivation graph (a derived cell is always single-writer — see
  [Derived cells](#derived-cells-are-never-multi-write)), or
- a single owning runtime that one-way **mirrors** the cell to other runtimes via a
  delta projection (today's `lazily-rs → lazily-kt` `#lazilystatesync` push is exactly
  this shape).

Propagation is **direct reactive push/pull** over the [IPC](protocol.md#ipc-snapshot--incremental-update-protocol)
or [FFI](protocol.md#ffi-boundary) channels. A mirror is still single-writer: the
receiving side observes, it does not write back. No merge step exists, and none is
permitted — a single-writer cell that receives a concurrent remote write is a
conformance error, not a merge.

> A cell mirrored one-way to N readers is single-writer. Locality does not make a cell
> multi-write; **a second concurrent writer does.**

## Multi-write cells

A multi-write cell admits **concurrent writes from multiple replicas**. New values
arrive as **remote ops merged through the cell's declared mechanism**; the merged
result is fed into the reactive graph as an ordinary cell update, after which
propagation is identical to a single-writer cell.

A multi-write cell carries a **`merge: <mechanism>`** attribute. The mechanism is a
parameter of the cell, **not** a separate cell kind:

```
Cell      = SingleWriter
          | MultiWrite { merge: MergeMechanism }
```

This framing is deliberate. An implementation MUST model multi-write as **one cell
category parameterized by a merge mechanism**, and MUST NOT hardcode a single `crdt`
cell kind. New mechanisms slot in without a new kind, and every mechanism shares the
ingress boundary, the merge-unit granularity, and the downstream propagation rules
below.

### Merge mechanisms

`crdt` is the **first** mechanism this spec defines and the only one with a normative
wire schema today ([`distributed.json`](schemas.md)). The mechanism slot is open by
construction so later mechanisms slot in alongside it. Every mechanism MUST be
**deterministic** — replicas applying the same op set MUST reach the same value
regardless of arrival order or lag.

| `merge` | Status | Convergence strategy |
|---------|--------|----------------------|
| `crdt` | **normative** (first) | Conflict-free replicated data type (yrs/Yjs-family registers); converges without coordination. See [Distributed: CRDT Cell Plane](protocol.md#distributed-crdt-cell-plane). |
| `lww` | reserved | Last-writer-wins by HLC/Lamport timestamp. |
| `ot` | reserved | Operational transform (server-ordered op rebase). |
| `lease` | reserved | Lease/lock-serialized single-*live*-writer; degenerate-concurrency convergence. |
| `custom` | reserved | Application-supplied deterministic merge function. |

`crdt` is chosen as the first mechanism because it converges **without coordination** —
no central ordering authority, no lock round-trip — which is the property the
editor-as-replica use case needs. Reserved mechanisms are named to fix the extension
shape; an implementation MAY reject any mechanism it does not implement, but MUST reject
it explicitly (capability negotiation) rather than silently treating it as `crdt`.

A multi-write cell with a single *live* writer **degenerates to a near-free merge** (no
concurrent ops to reconcile) under every mechanism. This is why the kind is chosen
statically by representation: a shared cell that is usually edited by one replica still
declares `merge:` so that the moment a second writer attaches, convergence is already
guaranteed.

## Merge is an ingress operation on root cells only

The merge mechanism is an **ingress** step at the boundary where remote ops enter a
replica. It applies **only to root (input) cells**.

### Derived cells are never multi-write

A derived cell is a deterministic function of its inputs. It has exactly one writer —
the derivation — and therefore is **always single-writer**. Replicas converge on a
derived cell *because* they converge on its roots, never by merging the derived value
itself. An implementation MUST NOT replicate or merge a derived cell directly.

### Effects stay single-writer

Effects (irreversible external actions — send email, charge card, fire webhook) are
**not** multi-write. State convergence does not authorize an effect to fire on every
replica. Effects MUST be gated behind a single-writer authority (a designated peer or
small consensus group) that decides when the effect fires, at-most-once. See
[Single-writer effect authority](protocol.md#single-writer-effect-authority).

```
                 remote ops
                     │
                     ▼
        ┌──────────────────────────┐
        │  merge: <mechanism>      │   ← ingress, ROOT cells only
        │  (crdt | lww | …)        │
        └──────────────────────────┘
                     │  merged value as ordinary cell update
                     ▼
        root cell ──► derived cells ──► effects
                    (single-writer)   (single-writer authority)
                     └─ direct reactive propagation, identical for all kinds ─┘
```

## Cell = merge unit

The **cell is the unit of merge.** Each multi-write cell converges **independently**;
a merge mechanism operates within one cell's value and MUST NOT move content across cell
boundaries.

This is normative because the cell graph already supplies the natural merge boundaries:
making the cell the merge unit makes cross-cell contamination **impossible by
construction**. A whole-document merge that splices one logical region's content into
another (for example an agent's console output bleeding into a queue region) is a
conformance violation — each region is a distinct cell and converges on its own.

An implementation MUST scope every merge to a single cell. Coarser-grained merge (whole
snapshot, whole document) is permitted only as an *optimization* that is observably
equivalent to per-cell merge; if it can produce a result no sequence of per-cell merges
could, it is non-conforming.

## Liveness vs mechanism

Whether a cell is multi-write (`merge:` present) is **static**. How many writers are
**live** against it at a given moment is **dynamic**, governed by an attach/detach
authority state machine (e.g. an editor plugin attaching or detaching). The authority
SM governs only *liveness* — it never changes a cell's kind or mechanism:

- **No live writer** → the cell still declares its mechanism, but with zero concurrent
  ops the merge is inert and a durable replica MAY be ephemeral (rebuilt from a
  checkpoint on demand).
- **One or more live writers** → ops flow and the declared mechanism reconciles them.

Mechanism is a property of the cell's **meaning**; liveness is a property of the current
**session**. Conforming implementations MUST keep these independent.

## Conformance summary

An implementation conforms to the cell model when:

1. Every cell is classified **single-writer** or **multi-write**, statically, by
   representation.
2. Multi-write cells carry a `merge: <mechanism>` attribute; multi-write is **not**
   modeled as a hardcoded `crdt` cell kind.
3. `crdt` is implemented as the first mechanism; unimplemented reserved mechanisms are
   rejected explicitly, never silently aliased.
4. Merge is an **ingress** step on **root** cells only; derived cells and effects are
   never merged.
5. Every merge is scoped to a **single cell** (cell = merge unit); no cross-cell
   content movement.
6. Downstream reactive propagation is the **same direct mechanism** regardless of cell
   kind.
7. The attach/detach authority governs writer **liveness** only, never a cell's kind or
   mechanism.
8. A **keyed cell collection** (`CellMap` + the `CellFamily` factory) is implemented —
   entries are ordinary cells, a dedicated membership cell tracks the key set, and the
   value / set-membership / order reactivity-independence, stable-handle, and
   atomic-move invariants below hold. Collections are **required of every binding**, not
   optional.
9. An **ordered keyed tree** (`CellTree`) is implemented, inheriting the per-cell merge
   and atomic-move guarantees node-by-node (required of every binding).
10. **Keyed reconciliation** emits the move-minimized `{insert, remove, move, update}`
    op set (LIS over prior indices preserved), and a stable entry is not invalidated by a
    sibling reorder (required of every binding).
11. A **reactive queue** (`QueueCell`) is implemented — a FIFO collection whose reactive
    shell invalidates by *reader kind* (head / length / empty / full / closed), backed by
    a pluggable `QueueStorage` backend. The shell / storage split, closure observable
    contract, bounded-queue backpressure, and ordering guarantees below hold (required of
    every binding).
12. **Materialization mode** is exposed with **eager as the default**; any **lazy** mode is
    opt-in, keyed, and **observationally transparent** — identical read values, allocation
    deferred only (see [Materialization mode](#materialization-mode)). *Lazy evaluation*
    (bounded-viewport recompute) is provided in **both** modes and is never conflated with
    *lazy materialization*.

## Materialization mode

Cell kind (above) fixes *how a cell converges*. **Materialization mode** is an
**orthogonal** axis: it fixes *when a derived cell's backing node is allocated* — not what
it computes, not how it converges, not how it merges. It trades **memory and first-touch
latency** against **cold full-scan cost**, and it MUST NOT be observable through the value
of any cell.

### The `ReactiveFamily` vehicle

Materialization mode is a property of a **`ReactiveFamily`** — the unified keyed reactive
family, of which the keyed cell collection ([`CellFamily`](#keyed-cell-collections)) is the
input-cell specialization. A `ReactiveFamily` maps keys `K` to per-entry reactive nodes and
abstracts over the entry's **handle kind**, the axis a binding can express as a type
parameter (`ReactiveFamily<K, V, H>`):

- **Cell entries** (`H = CellHandle`) are **input** nodes. They are **always materialized**
  regardless of mode — an input has no derivation to defer. Lazily *minting* an input on
  first `get` (as `CellFamily` does today) is a collection concern, not the materialization
  axis.
- **Slot entries** (`H = SlotHandle`) are **derived** nodes. These are what materialization
  mode governs: eager allocates them up front, lazy defers each to first read.

Entry kind is **orthogonal to mode** (proved in `lazily-formal`'s `Materialization` module
as `cell_entries_materialized_in_every_mode` / `slot_entries_deferred_under_lazy`): choosing
lazy defers only slot entries, never cell entries. The two modes below therefore describe how
a `ReactiveFamily`'s **derived (slot)** entries are allocated.

There are two modes:

- **Eager (default).** Every derived cell's node is allocated when the graph is
  constructed. This is the shared high-performance core: a read is a direct node access,
  and a full recompute pays only compute (allocation already happened at build). An
  implementation MUST make eager the **default**.
- **Lazy (opt-in).** A derived cell's node is allocated on its **first read**
  ("materialize on pull"), addressed by a **key** rather than a held handle. A never-read
  derived cell is never allocated. Lazy is a **keyed overlay on the eager core**, not a
  second graph engine: the first read of key `k` constructs the *same* node the eager
  build would have, then caches it. An implementation that offers lazy MUST expose it as an
  explicit opt-in (e.g. a keyed-context constructor), **never as the default** and **never
  as a per-read toggle** on an eager handle.

### Observational transparency (normative)

For every node and every read, the observed value MUST be identical under either mode.
Materialization mode is **not observable on the value axis** — it changes allocation timing
and memory, never results:

```
observe(build(eager, spec), id) = observe(build(lazy, spec), id) = spec.val(id)   ∀ id
```

This is proved in `lazily-formal`'s `Materialization` module
(`observe_canonical`, `eager_lazy_observationally_equivalent`). An implementation MUST
preserve these consequences:

1. **Same values.** A lazy read returns the value an eager read would (`observe_canonical`).
2. **No churn from allocation.** Materializing one node MUST NOT change any other node's
   observed value (`materialize_preserves_observe`).
3. **Deferral, not de-allocation.** Lazy materialization only *grows* the materialized set;
   a materialized node is never silently dropped, and the lazy set is a subset of the eager
   set (`materialize_present_monotone`, `lazy_present_subset_eager`).
4. **Reactivity is orthogonal.** *Lazy evaluation* — leaving off-viewport derived cells
   dirty and never recomputing them (the microsecond bounded-viewport read) — is required
   of **both** modes and is independent of materialization. Eager materialization still
   evaluates lazily; lazy materialization *additionally* defers allocation. An
   implementation MUST NOT conflate the two.

### When to opt into lazy

Lazy pays off only for **sparsely-touched large keyed address spaces** — e.g. a
10,000,000-cell spreadsheet where a session reads ~1% of the derived cells: it lowers peak
memory and makes "open" cost `O(inputs)` rather than `O(derived cells)`. It costs a
keyed-cache lookup per read instead of a handle dereference, and a cold full scan pays
allocation and compute together (`eager_materializes_all` vs `lazy_defers_slots`).
Handle-based graphs that read most of what they build SHOULD stay eager. The choice is a
**per-context construction decision**, not a per-cell or per-read one.

## Keyed cell collections

A *keyed cell collection* (`CellMap`, and the `CellFamily` factory over it) is a
**composition of cells**, not a new cell kind. It maps keys `K` to per-entry cells and
adds a dedicated **membership cell** tracking the set of keys.

> **Required.** The keyed cell collections layer is normative for **every** lazily
> binding — it is not an optional lazily-rs extension. A conforming binding MUST implement
> `CellMap`, the ordered keyed tree (`CellTree`), and keyed reconciliation, and MUST
> validate against the canonical fixtures in [`conformance/collections/`](conformance/collections/).
> The single-writer / multi-write classification, `merge:` mechanism, and ingress rules
> below are exactly those defined above — the collection adds **no new merge unit**.

It conforms to the cell model when:

1. Each entry is an ordinary cell — its single-writer / multi-write classification,
   `merge:` mechanism, and ingress rules are exactly those above. The collection adds no
   new merge unit; **cell = merge unit** still holds per entry.
2. **Value, set-membership, and order reactivity are independent**: writing one entry's
   value MUST NOT invalidate membership or order readers; adding/removing a key MUST NOT
   invalidate readers of unrelated entry values; and a **pure reorder** (atomic move) MUST
   NOT invalidate set-membership readers (`len` / `contains`) — only order readers (`keys`).
3. A key resolves to a **stable handle** for the key's lifetime; membership and order
   changes are signalled by their dedicated cells, never by mutating sibling entries.
4. **Atomic ordered move** (`move_to` / `move_before` / `move_after`): reordering a key MUST
   keep the entry's same cell handle, dependents, and lineage (not remove + re-mint) and
   bump only the order signal once.

### Ordered keyed tree

An *ordered keyed tree* (`CellTree`) is a further **composition**: each node is
`(stable id, value cell, ordered keyed child collection)`. It conforms when per-node value
reactivity holds (editing a node invalidates only that node's readers), per-level
membership/order reactivity holds (a sibling subtree or descendant change MUST NOT
invalidate an unrelated level's child readers), and child reorder inherits the atomic-move
guarantee. The tree is still a composition of cells — not a new cell kind — so per-cell
merge applies node-by-node.

This is the runtime substrate for stable keyed/wire addressing of collection entries
(see the protocol spec's node-key addressing) and for keyed reconciliation of document
trees (minimal `{insert, remove, move, update}` ops per item → per-cell CRDT merge).

### Keyed reconciliation

Reconciling a level diffs two keyed sequences **by stable key, not position**, emitting the
minimal `{insert, remove, move, update}` op set. It conforms when reordering is
move-minimized (keys already in relative order — the longest-increasing-subsequence over
their prior indices — MUST NOT move; only the remainder emit `move`), and when applied to
the reactive collection a **stable** entry (unchanged value, in the LIS) MUST NOT have its
value cell invalidated by a sibling reorder. Applying this minimal op set per-cell is the
enabling step for per-cell CRDT merge of a document tree — it replaces whole-subtree
replacement with proportional-to-the-diff work.

### Memoized semantic tree

The syntactic tree holds input cells; a **semantic** tree (unresolved prompts, drainable
heads, summaries) is a layer of **memoized computeds** derived from it — one memo slot per
node folding `(node value, child derived values)`. It conforms when the derivation is
incremental and glitch-free: editing one node recomputes only its **ancestor chain** (a
sibling subtree's derived value stays cached), and a node edit that does not change the
folded result MUST NOT re-run a downstream consumer (memo equality guard). Semantics are
derived, not materialized eagerly — cost is proportional to the diff, not the document.

### Manufactured identity for text

Markdown has no inherent node ids, so reconciliation keys are *manufactured* from text in
three layers: in-band **anchors** (exact, survive a body rewrite), **content-derived hashes**
of normalized text (survive reflow/reorder, change on edit), and **alignment** by similarity
(word-LCS ratio) to distinguish an *edit* (key inherited from the matched predecessor → an
`update`) from a genuine *insert*. A true rewrite legitimately reads as insert+remove. This
is why the controlled skeleton uses in-band markers: stable identity is the linchpin that
keeps keyed reconciliation from degrading to whole-document replacement over unstable text.

### Free-text CRDT + re-parse

For anchorless prose under concurrent edits the merge unit drops to **characters**: a
Fugue/RGA-style character CRDT (each char an element with a unique id + left origin; deletes
tombstoned) whose order is a pure function of the element set, so merge is commutative,
associative, idempotent and concurrent same-point inserts converge with both preserved. The
structural tree is then a **projection** of the merged text (re-parse → manufactured-identity
keys → reconcile), not the merge unit. Honest floor: a true rewrite is a replace — no
character identity survives it. The anchored layer keeps per-node lineage; the free-text
layer's guarantee is "merge the text, re-derive the tree."

#### Delta sync (#lztextsync)

Whole-replica `merge` requires transporting the entire element set; a conformant binding also
exposes **delta synchronization** so replicas converge by exchanging only what a partner
lacks. Three operations, over the same element set:

- **`version_vector()` → `{peer → counter}`** — the greatest [`OpId`] counter this replica
  holds per originating peer, taken over **both** insert ids and tombstone (delete) ids. It is
  the compact frontier a replica publishes; an op `(c, p)` is unknown to a partner iff
  `c > their_vv[p]` (absent peer = 0).
- **`delta_since(their_vv)` → `[TextOp]`** — the ops this replica holds that `their_vv` has not
  observed: elements whose **insert** id is newer, plus elements whose **tombstone** id is
  newer (a fresh deletion of an already-shared element). Each `TextOp` is the transport form of
  one element — `{ id, ch, origin, deleted }`. A whole-state snapshot is
  `delta_since(∅)`.
- **`apply_delta(ops)`** — applies a delta op list with the **same** algebra as `merge`: a new
  id adds its element (preserving that id); an incoming tombstone is merged sticky-minimally
  (concurrent deletes keep the smaller delete id); the local Lamport counter advances past
  every observed id. It is therefore commutative, associative, and idempotent, and re-applying
  a delta is a no-op.

Identity preservation is the load-bearing property: rebuilding a replica by `apply_delta`-ing a
snapshot onto a fresh buffer keeps every character's `OpId`, so a later concurrent edit merges
without duplication — unlike re-parsing the text, which would mint fresh ids and double content
on the next merge. This is what lets a canonical replica fork per-member replicas from an
encoded snapshot and keep them converged by bidirectional `delta_since`/`apply_delta`.

The three operations and their convergence/idempotence/identity invariants are pinned by the
compute fixture [`conformance/collections/textcrdt_delta_sync.json`](conformance/collections/textcrdt_delta_sync.json)
(`#lztextsync`): version-vector shape, bidirectional exchange, whole-snapshot fork identity, and
no-op re-apply.

### Move-aware sequence order

Sibling order under concurrency is a separate **composition** above per-cell value merge: a
move-aware sequence CRDT (fractional-index positions tiebroken by peer). It conforms when a
move is a **single LWW reassignment** of an element's position — not delete + reinsert — so
two concurrent moves of the same element converge to the later one **without duplication**,
and a concurrent move + value-edit of one element both apply (position and value are
independent registers). Removal is an LWW tombstone. This is the order layer beneath keyed
reconciliation; it lives only at the multi-writer boundary, leaving the single-producer
Snapshot/Delta mirror unchanged.

### Tombstone garbage collection

Tombstones (both the sequence-CRDT LWW flag and the character-CRDT sticky delete, which
carries the delete's own id) accumulate without bound — the standard set-CRDT memory-bloat
cost. Conformant GC is **causal-stability-gated**: a tombstone is collectable only once
*every* replica has observed the deletion (the version-vector frontier supplied by the
distributed plane, never a single replica's clock). The sequence layer drops a stable
tombstone directly (observationally inert: order/contains already skip it, re-merge re-adopts
it as a tombstone, a genuine resurrection wins by LWW). The character layer is conservative:
it collects a stable deleted element only when nothing references it as a left origin, so
removal never orphans a survivor; interior tombstones are reclaimed bottom-up. Bloat is
bounded to the multi-writer plane — the single-producer Snapshot/Delta mirror accrues none.

## Reactive queues

A *reactive queue* (`QueueCell`) is a FIFO collection composed of cells — **not a new cell
kind** — that adds queue semantics (push to tail, pop from head) to the reactive graph. Like
the keyed collections above, it adds no new merge unit; each element's value is an ordinary
cell subject to the same single-writer / multi-write classification.

The distinguishing property of a reactive queue is that invalidation is scoped to **reader
kind**, not to individual positions: a push invalidates length/empty/full readers (and the
tail signal); a pop invalidates head/length/empty/full readers. The head reader observes the
*current* head value — after a pop, the head reader sees the next element (or empty), not a
stale value. There is no random-access `queue[N]` reader; per-position reactivity is the
domain of `CellMap`, not `QueueCell`.

### QueueCell — SPSC primitive with MPSC usage rule

`QueueCell` is specified as a **single-producer, single-consumer** (SPSC) primitive: one
writer owns the tail, one reader owns the head. The producer is the natural FIFO sequencer
(push order = delivery order).

**MPSC** (multi-producer, single-consumer) is a *usage rule on the same primitive*, not a
separate type. Multiple producers push to the same tail inside a `batch()`; the batch
boundary serializes the pushes into a deterministic order. A conforming implementation
MUST document the MPSC usage rule and MUST NOT introduce a separate `MPSCQueueCell` type.

> **Naming discipline.** The cardinality of producers/consumers is not a type parameter.
`SPSCQueueCell` would imply `MPSCQueueCell` / `SPMCQueueCell` / `MPMCQueueCell` siblings —
but those shapes differ in *semantics* (invalidation model, handoff exclusivity), not
cardinality. See [§ Future queue primitives](#future-queue-primitives) for the genuinely
distinct primitives (`TopicCell`, `WorkQueueCell`).

### Reactive shell vs storage backend

A `QueueCell` factors into two layers:

```
  ┌─────────────────────────────────────────────────────────┐
  │                   Reactive shell                         │
  │  head version cell │ tail version cell │ closed cell     │
  │  len / is_empty / is_full / head — reactive reads       │
  │  invalidation scoped by reader kind                     │
  └────────────────────────┬────────────────────────────────┘
                           │ QueueStorage trait
                           │  try_push(v) → Result<(), Full|Closed>
                           │  try_pop() → Result<T, Empty|Closed>
                           │  len() → usize
                           │  capacity() → Option<usize>
                           │  is_closed() → bool
   ┌───────────────────────┼───────────────────────────────┐
   │                       │                               │
   ▼                       ▼                               ▼
 VecDequeStorage      RaftQueueStorage              KafkaStorage
 (local default)      (embedded consensus;          (external broker;
                       per distributed-queue PRD)    via adapter)
```

The **reactive shell** owns the version cells and invalidation logic; it is
storage-agnostic and is what the formal model ([`QueueCell.lean`](formal-model.md)) pins.
The **storage backend** owns the actual FIFO data structure and is pluggable via the
`QueueStorage` trait (Rust) / concept (C++) / interface (Py/JS/etc.).

An implementation MUST split the shell from the storage. The shell MUST NOT assume a
specific storage type (VecDeque, ring buffer, broker client). A binding MAY ship multiple
backends; the default MUST be an unbounded `VecDeque`-backed storage.

### Storage backend contract

A `QueueStorage` backend conforms when:

1. **FIFO order**: `try_pop` returns elements in the order they were `try_push`-ed. A
   backend that reorders or silently drops elements is non-conforming.
2. **Cardinality compatibility**: the backend's native producer/consumer shape MUST be a
   superset of the shell's required shape. (SPSC shell = any backend; MPSC usage requires
   a backend that accepts multi-writer pushes.)
3. **Bounded contract** (optional): a bounded backend exposes `capacity() → Some(n)` and
   `try_push` returns `Full` when at capacity. The **overflow policy** (block / drop-oldest
   / drop-newest / reject) is a backend property — the shell's observable contract only
   distinguishes `Full` from `Empty`/`Closed`.
4. **Position identity**: invalidation is phrased over reader kind (head/len/empty/full),
   *not* over storage indices. A ring-buffer backend whose slot index wraps MUST NOT cause
   spurious invalidations; the shell layers its own logical version counters above the
   storage.

### Closure and lifecycle

Closure is an **observable contract**, not a mechanism:

1. `try_pop` on a closed, non-empty queue returns the next element (drain continues).
2. `try_pop` on a closed, empty queue returns `Closed` — a signal distinct from `Empty`.
3. `try_push` on a closed queue is an error, regardless of capacity.
4. Close is **idempotent** (closing an already-closed queue is a no-op) and **terminal**
   (once closed, a queue cannot be reopened).

The *mechanism* (a dedicated closed cell, a flag in storage, a sentinel value) is a
binding-level choice. The formal model pins closure as a monotonic flag:
[`Closed_then_stays_Closed`](formal-model.md).

### Bounded queue and reactive backpressure

When the storage backend is bounded (`capacity() → Some(n)`), the reactive shell exposes
`is_full` as a **reactive read**. A consumer's pop that transitions the queue from full to
not-full MUST invalidate `is_full` readers (true → false), enabling push-side effects to
react to capacity recovery without polling. This is the backpressure signal: a producer
observes `is_full` and backs off; a consumer's pop invalidates the producer's `is_full`
subscription and the producer resumes.

An implementation MUST expose `is_full` as a reactive cell when the backend is bounded.
The unbounded default (`capacity() → None`) has no `is_full` reader to invalidate.

### Ordering guarantee

| Shape | Guarantee |
|-------|-----------|
| SPSC | **Total FIFO** — pop order exactly matches push order. The producer is the single sequencer. |
| MPSC | **Per-producer FIFO** — messages from each producer arrive in that producer's push order. **Inter-producer interleaving** is deterministic within a `batch()` but implementation-defined across batches; under distribution it converges. |

A consumer MUST NOT assume total-FIFO across multiple producers. If total order across
producers is required, route all pushes through a single producer or use a consensus-backed
storage backend (per the [distributed-queue PRD](distributed-queue-prd.md)).

### Wire and snapshot shape

The `QueueCell` shell has **no own IPC schema** — the head/tail/closed version cells are
trivial counters, not independently serialized. Queue state on the wire is the **storage
backend's snapshot form**. Cross-backend interop (e.g., `VecDeque`-backed on one peer,
`RaftQueueStorage` on another) requires explicit storage-format agreement between the
peers; the shell does not mandate a canonical storage snapshot.

The reference `VecDequeStorage` backend serializes as a JSON array (element order = FIFO
order) for conformance fixture purposes. Bindings MAY choose a more efficient binary
encoding (bincode, postcard) for production use.

### Distribution

Distribution of a `QueueCell` is a **storage-backend property**, not a shell property. A
`QueueCell` is distributable iff its storage backend provides a distributed synchronization
mechanism. The shell itself is sync-mechanism-agnostic.

v1 does **not** specify any distributed backend. The
[Native Distributed Queue PRD](distributed-queue-prd.md) covers the future consensus-based
`RaftQueueStorage` backend (Phase 1+) and the positioning relative to external brokers
(Kafka, RabbitMQ, Redis Streams, SQS) via the `QueueStorage` adapter. CRDT-based
distribution is explicitly out of scope for queues — destructive pop requires agreement,
not merge (see the PRD's § "Background: Why Consensus, Not CRDT").

### Threading, permissions, and instrumentation

- **Threading contract**: `QueueCell` inherits the `Context` threading model. MPSC on the
  same `Context` uses `batch()`; cross-thread MPSC requires `ThreadSafeContext`;
  cross-process requires a distributed storage backend.
- **Permissions**: over the distributed plane, push and pop are distinct capabilities under
  `PeerPermissions` (`distributed.json`). A peer MAY be granted push-only, pop-only, or
  both.
- **Atomicity**: `push` and `pop` are individually atomic. Multi-op transactions (e.g.,
  "enqueue N items then close") MUST use `batch()` so a concurrent observer never sees a
  partial state.
- **Instrumentation**: a binding SHOULD expose depth / push-count / pop-count metrics via
  the standard instrumentation surface (parallel to `effect_queue_pushes` /
  `max_effect_queue_depth`).
- **Named observables**: `is_empty` and `len` are reactive reads dual to `is_full`. All
  three (`is_empty` / `len` / `is_full`) MUST be reactive when their respective conditions
  can change.

## Future queue primitives

`QueueCell` covers SPSC and MPSC. Two genuinely distinct primitives are reserved for
future work — they differ in **invalidation model and handoff semantics**, not in producer/
consumer cardinality:

### TopicCell (broadcast)

A *broadcast topic* where every subscriber receives every pushed element. Invalidation is
"all subscribers," not "head reader." Each subscriber maintains its own cursor; the topic
retains elements until all cursors have advanced past them (or a TTL expires).

**Semantics**: SPMC broadcast / MPMC pub-sub. **Delivery**: each subscriber sees the full
sequence independently. **GC**: bounded by the slowest subscriber's cursor.

**Relationship to QueueCell**: a `TopicCell` is not a multi-consumer `QueueCell`. A
`QueueCell` has one consumer that destructively pops; a `TopicCell` has N subscribers that
each independently read. The invalidation models are different in kind.

**Status**: future work — not in v1 conformance. See the
[distributed-queue PRD](distributed-queue-prd.md) Phase 3.

### WorkQueueCell (competing consumers)

A *work queue* where N consumers compete for elements from a shared FIFO. Each element is
delivered to **exactly one** consumer (exclusive handoff). This requires an authority
(designated leader peer) to serialize pop-assignment — pure CRDT cannot provide exclusive
handoff (concurrent pops both survive merge → duplicate delivery).

**Semantics**: true MPMC with exclusive handoff. **Delivery**: exactly-once via
leader-assigned delivery IDs + consumer ack/nack. Unacked entries are redelivered (pending
entries list). Dead-letter queue for poison messages.

**Deferred features** (land with `WorkQueueCell`, not `QueueCell`): ack/nack,
visibility-timeout / lease with TTL, dead-letter queue, producer/consumer deduplication,
fairness policy.

**Status**: future work — not in v1 conformance. Requires the consensus core from the
[distributed-queue PRD](distributed-queue-prd.md) Phase 2.
