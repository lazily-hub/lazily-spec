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

The per-cell merge `⊕` is characterized as an **associative fold** by the
[merge algebra](reactive-graph.md#mergecell-and-the-merge-algebra-relaycell)
(`#relaycell`): a `MergeCell<T, M>` is a cell whose write folds under a
`MergePolicy` `M`, and a plain `Cell` is `MergeCell<KeepLatest>`. The
[merge mechanisms](#merge-mechanisms) below are the semilattice policies
(`CrdtJoin<C>`) of that algebra; associativity is the invariant that lets a
bounded relay flush at any watermark and still converge (Phase 2+).

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

**Cross-process liveness as a CRDT cell.** When *session liveness itself* must cross a process
boundary — "editor pid X has doc Y open", "pid X holds the owner lease" — it is modeled as an
ordinary multi-write cell on the CRDT plane, not as out-of-band state: an **OR-set** for open-set
membership (observed-remove, so a re-open wins over a lagging close) and an **LWW register** for the
per-pid `alive` flag / lease. The derived "is this doc live" aggregate is then a plain reactive
memo over that liveness keyed map (the `#lzfamilysync` derived-aggregate contract), and an OS
process-exit event is just the highest-stamp write to `alive[pid]`. This keeps liveness on the same
convergent, idempotent, frontier-resumable substrate as every other replicated cell. Normative
semantics: [protocol.md § Liveness cells](protocol.md#liveness-cells-or-set-and-lww-lzsync-liveness).

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
8. A **keyed cell collection** (`ReactiveMap` — the `CellMap`/`SlotMap` specializations) is
   implemented — entries are ordinary cells, a dedicated membership cell tracks the key set, and the
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
12. **Materialization** is **eager by default** — a `SlotMap`'s derived entries are pre-minted
    over the keyset; **lazy** materialization (`get_or_insert_with` mint-on-access) is opt-in,
    keyed, and **observationally transparent** — identical read values, allocation deferred only
    (see [Materialization](#materialization-a-caller-provided-recipe)). It is a **behavior, not a
    mode flag**. *Lazy evaluation* (bounded-viewport recompute) is provided **either way** and is
    never conflated with *lazy materialization*.

## Materialization (a caller-provided recipe)

Cell kind (above) fixes *how a cell converges*. **Materialization** is an **orthogonal**
axis: it fixes *when a derived cell's backing node is allocated* — not what it computes, not
how it converges, not how it merges. It trades **memory and first-touch latency** against
**cold full-scan cost**, and it MUST NOT be observable through the value of any cell.

> **Why a behavior, not a mode.** Materialization was first pinned as a bespoke `ReactiveFamily`
> type carrying an eager/lazy *mode* — a reaction to one binding (`lazily-zig`) implementing
> lazy materialization in the spreadsheet benchmark and thereby diverging from the others.
> Standardizing a *type with a mode* invites re-divergence: each binding builds it slightly
> differently, and most never need it. What must agree is the **observable behavior** the
> benchmark measures — *transparency* (a lazy read equals an eager read) and *deferral* (an
> unread lazy entry costs nothing) — not any type or flag. So materialization is normative as a
> **behavior of the keyed primitive**: it is simply what [`SlotMap`](#keyed-cell-collections)
> does — `get_or_insert_with` mints a derived slot on first access (lazy); a pre-mint loop over
> the keyset is eager. There is **no materialization *mode* and no *family* type** — the family
> types (`ReactiveFamily` / `CellFamily`) are removed; `SlotMap` (a `ReactiveMap` specialization)
> is the vehicle.

### The materialization recipe

Materialization is **caller-provided**: a keyed collection (a
[`CellMap`](#keyed-cell-collections) or any keyed address space) plus a **per-key factory
whose return type is the materialization choice**. Nothing new is required beyond the
cell/slot/signal primitives a binding already has:

- **Eager entry** — the factory yields an **input cell** or an **eager `signal`** (a
  memo-slot + puller effect): the node is allocated/pulled up front; a read is a direct node
  access.
- **Lazy entry** — the factory yields a **lazy `slot`**: the node is allocated on its
  **first observe**, addressed by **key**. A never-observed lazy entry is never allocated.

So the caller provides materialization through two levers it already owns — *whether it
observes a key* (unread lazy entries stay unallocated) and *what the factory returns* (slot ⇒
lazy, signal ⇒ eager) — with **no mode flag** and **no per-read toggle**. This is the same
"lazy by default, eager when asked (via `signal`)" model lazily already uses at the single-cell
level, applied per key. Entry kind is the pinned axis:

- **Cell entries** (`H = CellHandle`) are **input** nodes — **always materialized**; an input
  has no derivation to defer. Minting an input on first `get` is a collection concern, not
  materialization.
- **Slot entries** (`H = SlotHandle`) are **derived** — the ones deferral governs: an eager
  factory allocates them up front, a lazy factory defers each to first observe.

Entry kind is **orthogonal to the materialization choice** (proved in `lazily-formal`'s
`Materialization` module as `cell_entries_materialized_in_every_mode` /
`slot_entries_deferred_under_lazy`): lazy defers only slot entries, never cell entries.

Normative rules on the recipe:

- **Eager is the default.** Absent an explicit lazy opt-in, derived entries are eager — a read
  is a direct node access and a full recompute pays only compute. A binding MUST make eager the
  **default**.
- **Lazy is an explicit opt-in overlay on the eager core**, addressed by **key**, **never**
  the default and **never** a per-read toggle on an eager handle. The first observe of key `k`
  constructs the *same* node the eager build would have, then caches it — a keyed overlay, not
  a second graph engine. A binding that offers lazy MUST expose it as an explicit opt-in (e.g.
  a keyed factory / keyed-context constructor).

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

### Execution-context flavors (thread-safe / async)

`SlotMap` runs against a **context**, and the context is a third axis orthogonal to both entry
kind and materialization: it fixes *where and how* the graph executes, not *what* it computes.
The materialization laws hold over each context a binding provides — the `ReactiveMap` line has
one flavor per context, and each carries the context-specific law below:

- **Single-threaded** (`SlotMap`, over the base `Context`) — the reference semantics above.
- **Thread-safe** (`ThreadSafeSlotMap`, over a lock-backed context) — a `Send + Sync` map that
  can live in a cross-thread owner (e.g. a hub behind a global mutex, where an `Rc`-based map
  cannot go). It carries the *same* materialization laws, plus **materialization confluence**:
  the present set and every observed value are independent of the order in which keys are
  materialized. This is what makes lock-serialized concurrent materialization safe — any order
  the lock admits yields the same observable map. Proved in `lazily-formal`'s `Materialization`
  module (`materialize_present_comm` / `materialize_observe_comm`).
- **Async** (`AsyncSlotMap`, over an async context) — derived (slot) entries
  resolve **asynchronously**, so a non-blocking read returns an optional value
  (`None` while pending, `Some(v)` once resolved). Observational transparency weakens
  to **eventual transparency**: once a node resolves, its observed value is the
  canonical value — identical to what the synchronous `SlotMap` observes. Input cells
  are resolved at build. Proved in `lazily-formal`'s `AsyncMaterialization` module
  (`eventual_transparency`, `async_resolved_matches_sync`; a pending read is never a
  stale value, `observe_pending_is_none`).

A binding SHOULD keep the per-key factory uniform across flavors (the same
`Fn(&K) -> V`), so the flavors differ only in execution context — a derived async
slot wraps that factory in a ready computation. A flavor MUST preserve the entry-kind
and materialization laws above; it only adds the context-specific guarantee
(confluence for thread-safe, eventual transparency for async).

### When to opt into lazy

Lazy pays off only for **sparsely-touched large keyed address spaces** — e.g. a
10,000,000-cell spreadsheet where a session reads ~1% of the derived cells: it lowers peak
memory and makes "open" cost `O(inputs)` rather than `O(derived cells)`. It costs a
keyed-cache lookup per read instead of a handle dereference, and a cold full scan pays
allocation and compute together (`eager_materializes_all` vs `lazy_defers_slots`).
Handle-based graphs that read most of what they build SHOULD stay eager. The choice is a
**per-context construction decision**, not a per-cell or per-read one.

## Keyed cell collections

A *keyed cell collection* is a **composition of cells**, not a new cell kind. It maps keys `K`
to per-entry reactive nodes and adds a dedicated **membership cell** tracking the set of keys.
There is **one keyed primitive**, generic over the entry's handle kind:

- **`ReactiveMap<K, V, H>`** — a mutable reactive keyed dict: reactive membership + order,
  `get_or_insert_with` (mint-on-access), `remove`, `move`. `H` is the entry handle kind. Its two
  specializations are the concrete types a binding exposes:
  - **`CellMap<K, V>` = `ReactiveMap<K, V, CellHandle>`** — **input-cell** entries. Adds
    `set(key, value)` (an input is settable). Minting is eager-by-value.
  - **`SlotMap<K, V>` = `ReactiveMap<K, V, SlotHandle>`** — **derived-slot** entries.
    `get_or_insert_with(key, factory)` mints a slot on first access (**lazy materialization**);
    a slot's value is derived, so `SlotMap` has **no `set`**. Eager materialization is a pre-mint
    loop over the keyset; lazy is mint-on-access — there is **no eager/lazy mode flag**.

`set(key, value)` is therefore **cell-only** (lives on the `CellMap` specialization); the shared
surface — `get_or_insert_with` / `remove` / `move` / membership / order — lives on the generic
`ReactiveMap`. There are **no family types**: the "keyed materialized family" is `SlotMap` + the
mint recipe, and the "auto-mint keyed default" is `get_or_insert_with` — neither needs a separate
type (see [§ Materialization](#materialization-a-caller-provided-recipe)).

> **Required.** The keyed cell collections layer is normative for **every** lazily
> binding — it is not an optional lazily-rs extension. A conforming binding MUST implement
> `ReactiveMap` (at least its `CellMap` specialization; `SlotMap` where the binding supports
> derived slots), the ordered keyed tree (`CellTree`), and keyed reconciliation, and MUST
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

### The queue family — two axes (semantics defines the primitive)

`QueueCell`, `TopicCell`, and `WorkQueueCell` are one family of reactive cursor-stream cells,
separated by **two orthogonal axes**. Only the first defines the primitive; the second is a usage
tier every primitive shares.

**Axis 1 — consumer delivery semantics (the primitive axis).** Where does each pushed element go?

| Delivery semantics | Each element goes to | Consumption | Primitive |
|---|---|---|---|
| single | the one consumer | destructive pop | `QueueCell` |
| competing | **exactly one** of N consumers | destructive, exclusive handoff | `WorkQueueCell` |
| broadcast | **every** subscriber | non-destructive cursor read | `TopicCell` |

**Axis 2 — topology / ordering (a usage tier, not a type).** Producer and consumer *counts* —
fan-in and fan-out — never change *which* primitive you have; they only set the ordering guarantee
and its cost. Opt into exactly the tier you need:

| Ordering tier | Guarantee | Mechanism | Cost |
|---|---|---|---|
| per-producer FIFO (default) | each producer's substream in push order; interleave arbitrary | none — ≡ multiplexing N single-producer channels at the consumer | free |
| agreed total order | one global order across producers | a single leader sequencer | one hop, single point of failure |
| agreed total order + HA | total order surviving node death / partition | consensus (Raft/Paxos) | quorum latency |

**Why not name by cardinality or by fan-in/fan-out.** Both are the *same mistake* — naming a
primitive by topology instead of by delivery semantics:

- **`SP*`/`MP*`** mixes two axes: `QueueCell` already covers SPSC *and* MPSC (both single-consumer;
  MPSC is the multi-producer *usage*). `WorkQueueCell` and `TopicCell` are each usable single- or
  multi-producer, so `SPMC`/`MPMC` cannot tell them apart.
- **`FanOutCell`/`FanInCell`** fails identically. **Fan-in** (many producers → one consumer) is just
  `QueueCell` used multi-producer — the ordering tier, *not* a distinct primitive; a `FanInCell`
  collapses back into `QueueCell`. **Fan-out** (one → many consumers) is **ambiguous** between
  broadcast and competing — `TopicCell` *and* `WorkQueueCell` both fan out, and one `FanOutCell` name
  cannot say whether an element goes to *all* or to *one*. And fan-in and fan-out are **not mutually
  exclusive** (a topic or work queue may be many-producer *and* many-consumer at once), so they are
  orthogonal *descriptors of wiring*, not primitive identities.

So fan-in and fan-out are real and useful — but as the **topology axes** describing how a primitive
is wired, not as names: **fan-in = the multi-producer ordering tier** (Axis 2); **fan-out =
multi-consumer, which subdivides into broadcast (`TopicCell`) vs competing (`WorkQueueCell`)** by
Axis 1. A primitive is always named by its Axis-1 delivery semantics, which carries meaning a
topology name cannot.

**Naming rationale (suffix).** The shared family suffix is **`Cell`**; `Queue` appears only where
consumption is **destructive and exclusive** — `QueueCell` and `WorkQueueCell`. A `TopicCell` is a
**non-destructive broadcast log** (reading removes nothing; every subscriber reads every element),
so it carries no `Queue` — `TopicQueueCell` would conflate the deliberately contrasting messaging
terms *queue* (consumed once) and *topic* (delivered to all). Parity is the `Cell` suffix + this
family section, not a forced `Queue` infix.

**What multi-producer actually buys** (fan-in): a single merged **fan-in aggregation** stream, one
**shared backpressure / capacity bound**, and — only at the total-order tier — an **agreed order**.
Consensus is the price of *agreed total order under partition only*, never of multi-producer itself;
per-producer FIFO needs no sequencer (it *is* multiplexed single-producer channels). Full
cross-replica **retention** (every replica holds each item until all consumers ack + compaction) is
a **replication/HA cost**, orthogonal to producer count — a non-replicated queue retains each item
once.

**Distribution cost differs by primitive** (Axis 1 decides it):

| Property | `QueueCell` | `WorkQueueCell` | `TopicCell` |
|---|---|---|---|
| Each element → | the one consumer | exactly one of N | every subscriber |
| Consumption | destructive pop | destructive, exclusive handoff | non-destructive cursor read |
| Distribution cost | leader-election HA (fence one consumer) | **assignment consensus** (quorum) | per-subscriber cursors, **no** consensus¹ |
| Slow consumer | fills queue → backpressure | routed to others; fine until all saturated | grows *its* retention; evict on lease expiry |
| Consumer death | queue **stalls** until failover | in-flight **reassigned**; no stall | that subscription grows; others fine |
| Ordering | total FIFO | assignment-FIFO; processing unordered | per-subscriber FIFO¹ |
| Delivery | exactly-once local / effectively-once distributed | at-least-once + idempotency = effectively-once | at-least-once per subscriber |
| Consensus? | only for HA | **yes** (assignment) | only for agreed-order broadcast¹ |

¹ A topic is consensus-free only at the per-producer-FIFO tier; **total-order broadcast (all
subscribers agreeing on one order) is atomic broadcast ≡ consensus** — the same cost as an ordered
`WorkQueueCell`. Quorum-intersection safety for `WorkQueueCell` assignment is proven
`ReliableSync.majorities_intersect`. Detailed semantics follow in
[§ Future queue primitives](#future-queue-primitives).

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

**Minimal required contract.** A `QueueStorage` backend MUST implement exactly
`try_push` / `try_pop` / `len` / `is_closed` / `close`. `peek` and `capacity` are **optional
capabilities** with a default of "absent" (`None`): a backend that satisfies only the five
required methods — a raw channel, a consuming stream, a Go channel — is fully conforming. It
simply has no `head` reader (no `peek`) and no `is_full` reader (unbounded, `capacity() →
None`), exactly as an unbounded backend has always had no `is_full`. A backend that *can*
cheaply inspect its head MAY expose `peek` to gain a reactive `head`; a backend that is
bounded MUST expose `capacity() → Some(n)`. `head` was never in the MUST-reactive set (see
"Named observables" below), so removing `peek` from the required contract removes no required
reader.

> *Footnote — `LookaheadShim`.* A caller that wants a `head` reader over a non-peekable
> backend MAY opt into a shell-level lookahead shim that prefetches (early-pops) one element
> into a one-slot buffer. This is **SPSC-local only** — early-popping is incorrect for
> competing-consumer or consensus backends, where an element must not be committed to one
> consumer before assignment. The shim is not part of the core contract.

A conforming backend MUST also satisfy:

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
   spurious invalidations; the shell layers its own logical reader-kind derivations above the
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

The `QueueCell` shell's **version cells have no own IPC schema** — the head/tail/closed
counters are trivial and not independently serialized. A queue reconciles by two
complementary wire forms, chosen by plane:

- **Snapshot plane → storage-snapshot form.** Full queue state is the **storage backend's
  snapshot form**. The reference `VecDequeStorage` backend serializes as a JSON array
  (element order = FIFO order) for conformance fixtures; bindings MAY choose a more
  efficient binary encoding (bincode, postcard) for production. Cross-backend interop (e.g.
  `VecDeque`-backed on one peer, `RaftQueueStorage` on another) requires explicit
  storage-format agreement; the shell does not mandate a canonical storage snapshot.
- **Delta plane → op-log form.** Incremental change is the ordered shell op-log —
  `QueuePush` / `QueuePop` / `QueueClose` — carried in a `Delta` like any other `DeltaOp`
  ([protocol.md § QueueCell op-log delta form](protocol.md)). These are **shell** ops
  (storage-agnostic append/remove-head/close), so they need no storage-format agreement; the
  op-log is the form reliable-sync fuses under backpressure (a queue cannot state-supersede
  coalesce — order, multiplicity, and the receiver's pop position forbid it). The op-log
  delta form is normative here; a distributed *storage* backend (per the
  [distributed-queue PRD](distributed-queue-prd.md)) remains a separate v1 non-goal.

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
- **Demand-driven derivation** (permitted optimization): a reader-kind MUST be
  observable-consistent — a `get` returns the value consistent with all preceding ops — but a
  binding MAY **defer its derivation until it has a subscriber**. A reader-kind is a *derived*
  value (a `Slot`), not an eagerly-written cell; an op with no subscriber to a given
  reader-kind MAY only mark it stale (O(1)) and derive it lazily on the next `get`, provided
  the derived value is consistent with all preceding ops. This preserves the observable
  contract (conformance fixtures read the values and MUST stay green) while an **unsubscribed**
  `QueueCell` collapses toward raw-storage cost — the reactive shell is charged only along a
  path an effect actually observes. See [`docs/relaycell-backpressure-analysis.md`](docs/relaycell-backpressure-analysis.md)
  §5 (demand-driven reader-kinds) and §4.0 (the merge cost law).

## Future queue primitives

`QueueCell` covers SPSC and MPSC. Two genuinely distinct primitives are reserved for
future work — they differ in **invalidation model and handoff semantics**, not in producer/
consumer cardinality:

### TopicCell (broadcast)

A *broadcast topic*: every subscriber receives every pushed element. Invalidation is "all
subscribers," not "head reader." Each subscriber holds its **own cursor**; the topic retains an
element until all durable cursors pass it (or a TTL expires). Reading is **non-destructive** — a
subscriber's advance never removes the element for others.

**Relationship to `QueueCell`**: not a multi-consumer queue. A `QueueCell` consumer destructively
pops; a `TopicCell` subscriber reads by cursor and removes nothing. Different invalidation models in
kind.

**Distribution is cheap — no assignment consensus.** Every subscriber gets every element, so there is
**no "who gets this" decision to arbitrate**. A distributed topic is N independent per-subscriber
cursor-queues — the [per-peer `DurableOutbox`](protocol.md) fan-out already pinned for reliable sync.
At-least-once fan-out + idempotent apply per subscriber = effectively-once, no quorum. *Caveat:* this
holds only at the per-producer-FIFO tier; **total-order broadcast** (all subscribers agree on one
order) is **atomic broadcast ≡ consensus**.

**Durable vs ephemeral subscriptions.** A *durable* subscription persists its cursor and replays
elements missed while offline; an *ephemeral* subscription sees only elements published while
connected (fire-and-forget). Durable subscriptions drive retention.

**Backpressure is per-subscriber, and the answer is the state-vs-event split.** Each subscriber's
delivery buffer is itself a bounded `QueueCell`, so a slow subscriber's `is_full` fires *locally*;
what happens then is a **per-subscription policy**, and the right one depends on message semantics —
the same dichotomy as [outbox coalescing](protocol.md):

- **State topic (broadcasting a value)** — old elements are worthless once superseded, so a lagging
  subscriber **conflates to latest** (drop intermediates, keep the newest): the LWW/last-value
  coalesce applied to a subscriber. Memory-bounded and **effect-lossless** — the laggard simply gets
  current state, and the producer feels nothing.
- **Event/log topic (each element a distinct event)** — no conflation is possible (order and
  multiplicity are meaning), so a lagging subscriber resolves overflow one of three ways:
  - **Drop (lossy, isolated)** — `drop-oldest` / `drop-newest` for *that* subscription; fast
    subscribers and the producer are unaffected. This is the broadcast **default** — coupling defeats
    fan-out.
  - **Couple + backpressure (lossless, slowest-paces)** — the subscriber withholds ack, retention
    grows, and the **producer throttles to the slowest durable subscriber**. Opt-in, for
    "all-must-receive-losslessly" topics; the operator accepts one slow subscriber pacing the whole
    topic.
  - **Evict (bounded)** — on sustained lag past a liveness lease, drop the whole subscription
    ([§ Partition & eviction](protocol.md)); it full-resyncs (durable) or resumes from now
    (ephemeral) on return.

So a `TopicCell` producer **feels backpressure only if a subscription opts into coupling**; by default
a slow subscriber conflates (state) or drops/evicts (event), and **failure is isolated** — a dead
subscriber grows only *its* retention, never stalling other subscribers or the producer. This is the
opposite of `QueueCell`, where the single consumer *is* the backpressure path.

**Consumer groups = a topic of work queues.** The "Kafka consumer group" shape is a *composition*,
not a fourth primitive: `WorkQueueCell` semantics *within* a group (competing) and `TopicCell`
semantics *across* groups (each group gets the full stream). Model it as a `TopicCell` whose
subscribers are `WorkQueueCell`s.

**Status**: future work — not in v1 conformance. See the
[distributed-queue PRD](distributed-queue-prd.md) Phase 3.

### WorkQueueCell (competing consumers)

A *work queue*: N consumers compete for elements from a shared FIFO; each element is delivered to
**exactly one** consumer (exclusive handoff).

**Why pure CRDT cannot do this.** A queue pop is **not idempotent-commutative**: two consumers
concurrently popping the same head both survive a CRDT merge → duplicate delivery, and there is no
"un-pop." Exclusive handoff therefore needs a **single serialization point** for the assignment
decision — a designated leader assigning each element to one consumer, or a consensus-committed
assignment log. This is the queue's CP nature made concrete.

**Safety via quorum intersection.** With consensus-committed assignment, "element X → consumer W" is
a majority-committed log entry. Because **any two majorities of an `n`-voter set intersect in ≥1
voter** (`ReliableSync.majorities_intersect` / `majorities_overcount`), two conflicting assignments of
the same element can never both commit — no double-delivery, ever — and a minority (no quorum) cannot
commit an assignment, so it blocks rather than risking a duplicate.

**Three populations — do not conflate.**
- **Workers/consumers** — any count; clients of the queue, not voters. Scale freely.
- **Replication peers** (per-peer outbox) — any count; transport, not voting.
- **Voting replicas** (order + commit assignments) — want an **odd** count: `2f+1` replicas tolerate
  `f` failures; odd maximizes tolerance-per-node and keeps quorum unambiguous. Make an even data set
  odd with a **witness/arbiter** (votes, holds no data).

**Partition behavior.** Only a partition holding a majority makes progress; the rest block (safe, no
double-pop). A **2–2** split of 4 voters gives neither side a majority → *both* stall (the even-group
hazard, fixed by a witness). A **2–2–1** split of 5 voters leaves no side with 3 → *all* block until
partitions heal enough for some side to reach a majority. Odd counts protect *two-way* splits; they
never guarantee a majority under multi-way fragmentation. Halting is correct — safety over liveness.

**Delivery & lifecycle** (deferred features — land with `WorkQueueCell`, not `QueueCell`):
- **Assignment IDs + ack/nack.** Each handoff carries a delivery ID; the worker **acks** (done,
  remove) or **nacks** (requeue). Exactly-once *commit* is the consensus assignment; exactly-once
  *effect* needs an idempotent worker or a [causal receipt](protocol.md) on completion; delivery is
  **at-least-once** (redelivery on failure) — so effectively-once = at-least-once + idempotency.
- **Visibility-timeout / lease.** An assigned-but-unacked element is leased with a TTL; on expiry it
  reassigns (worker presumed dead) — the per-item analog of the liveness lease.
- **Dead-letter queue + poison detection.** An element exceeding a max-redelivery count (repeatedly
  crashing its worker) routes to a DLQ instead of redelivering forever.
- **Fairness / dedup.** Assignment policy (round-robin, weighted, pull-based) + producer/consumer
  dedup keys.

**Assignment-FIFO ≠ processing-FIFO.** Competing consumers trade ordering for parallelism: even if
elements are *assigned* FIFO, N workers process concurrently, so **completion order is unordered**. A
slow worker holding element 1 does **not** block element 2 (it routes to another worker) — the point
of the primitive — but a consumer MUST NOT assume total processing order. For total order, use one
consumer (`QueueCell`) or route through a single worker.

**Pull beats push for balancing.** A **pull** model (workers request when ready) is naturally
load-balancing and backpressure-friendly — a fast worker pulls more, a saturated worker stops pulling.
A **push** model needs the assigner to track worker capacity. Pull-based competing consumers are the
simpler, self-throttling default.

**Backpressure & failure — most resilient of the three.** A single slow worker does *not* fill the
queue (its items route to others); the queue backpressures only when **all** workers are saturated and
depth grows. A worker death does not stall the queue — its in-flight (unacked) items reassign on lease
expiry; throughput degrades, delivery continues. Opposite of `QueueCell`, whose single consumer dying
stalls until failover.

**Status**: future work — not in v1 conformance. Requires the consensus core from the
[distributed-queue PRD](distributed-queue-prd.md) Phase 2.
