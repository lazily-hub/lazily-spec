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

## Keyed cell collections

A *keyed cell collection* (`CellMap`, and the `CellFamily` factory over it) is a
**composition of cells**, not a new cell kind. It maps keys `K` to per-entry cells and
adds a dedicated **membership cell** tracking the set of keys.

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
