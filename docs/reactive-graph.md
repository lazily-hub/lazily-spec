# Reactive Graph

The **reactive graph** is the dependency-tracking core of every lazily binding:
a set of nodes whose values are derived from each other, where a change to a
source invalidates only its transitive dependents and recomputation is pull-based
and glitch-free. This chapter fixes the cross-language *behavior* — the
[`lazily-formal`](https://github.com/lazily-hub/lazily-formal) kernel and the
lazily-rs / lazily-py / lazily-zig / lazily-kt implementations are the executable
references.

The reactive graph is **compute, not protocol**: only resolved values cross
IPC/FFI as ordinary cell payloads. Every binding that ships a reactive graph
MUST honor this contract.

## The reactive family

| Primitive | Role |
|-----------|------|
| **Cell** | A mutable source value. `setCell` invalidates dependents on a `==` (PartialEq) change; an equal set is a no-op. |
| **Slot** | A lazily-computed, memoized derived value. Tracks its dependencies automatically, computes on first read, caches, and recomputes only when read after an upstream invalidation. |
| **MergeCell** | A source whose write is a **merge** `⊕` under a [`MergePolicy`](#mergecell-and-the-merge-algebra-relaycell) rather than a replace. `Cell ≡ MergeCell<KeepLatest>`: a plain cell is the keep-latest instance. Backed by a cell node, so it inherits the `==` store-guard and store-without-cascade. |
| **Effect** | A side-effecting observer that reruns whenever a tracked dependency invalidates. An optional cleanup closure runs before each rerun and on dispose. |

The three core primitives are **`Cell`** / **`Slot`** / **`Effect`** (with
`MergeCell` the merge-generalized source, `Cell ≡ MergeCell<KeepLatest>`).

**`Signal` is a derived construct, not a core primitive.** It is
`Signal ≡ Slot.eager` — a memo Slot plus a puller Effect that reads the slot on
creation and after every invalidation, so its value is materialized by the time
the invalidating `setCell`/`batch` returns (observers never see an intermediate
unset state — `relaycell-backpressure-analysis.md` §4.0). It composes the core
primitives; bindings expose it as a convenience (`signal(compute)`), not as a
distinct kind of node.

Values are **lazy by default**; reach for the derived `Signal` when eager push
semantics are required. Handles (`SlotHandle` / `CellHandle` / `SignalHandle` /
`MergeCellHandle` / `EffectHandle`) are lightweight, copyable ids over a shared
node table — they are usable only with the owning context.

**The read/write type split.** Every primitive above is a **`Reactive<T>`** — the
read supertype exposing `get` (auto-subscribing) and `subscribe`, nothing more.
Writability is the sub-interface **`Source<T>: Reactive<T>`**, which adds `set`
(replace) and `merge` (fold under the source's policy). A derived Slot/Signal is
`Reactive<T>` only (read-only); `Cell`/`MergeCell` are `Source<T>`. The payoff
(`relaycell-backpressure-analysis.md` §4.0): a composite reader-kind can be typed
`Reactive<T>` and the backend chooses the impl — pull-Slot, push-fed Cell, or
polling-Slot — behind one interface, so ownership of the mutation (not the type)
decides the invalidation source.

## API surface

| Method | Description |
|--------|-------------|
| `cell(value)` | Create a mutable source cell |
| `get_cell(handle)` | Read a cell value (auto-subscribes the running computation) |
| `set_cell(handle, value)` | Update a cell and invalidate dependents (no-op on `==`) |
| `computed(compute)` / `slot(compute)` | Create a lazy derived slot (no memo guard) |
| `memo(compute)` | Create a lazy derived slot with a `==` memo guard |
| `get(handle)` | Read a slot, computing/refreshing if necessary (auto-subscribes) |
| `signal(compute)` | Create an eager derived value (memo slot + puller effect) |
| `get_signal(handle)` | Read a signal's current (always-materialized) value |
| `merge_cell<M>(value)` | Create a `MergeCell` whose write folds under policy `M` |
| `merge(handle, op)` | Fold `op` into a `MergeCell`/`Source` under its policy (`⊕`; routes through `set_cell`, so the `==` guard + store-without-cascade apply) |
| `effect(run)` | Register an observer; `run` may return a cleanup closure |
| `dispose_effect(handle)` | Deschedule, drop edges, run cleanup |
| `batch(run)` | Coalesce several cell updates into one invalidation + effect flush |

## Semantics

- **Pull-based, glitch-free refresh.** A slot that reads other slots always
  observes values consistent with the current inputs. On `get`, a slot first
  refreshes its own dependencies (recursively, lazy pull), then recomputes only
  if any dependency actually changed — it never observes a half-updated graph.
- **`==` guard on `set_cell`.** Setting an equal value is a no-op: no
  downstream cascade fires. Equality is structural/value equality, not
  reference identity, so two distinct-but-equal values suppress invalidation.
- **`memo` adds a `==` guard.** An equal recompute suppresses downstream
  invalidation — the slot's value version does not bump, so subscribers see no
  change. `computed`/`slot` (no memo guard) always propagates.
- **Dynamic dependencies.** A tracking stack auto-discovers edges on each
  recompute: every `get`/`get_cell` read inside a running slot/effect registers
  a dependency. Stale dependencies from a previous run are removed before
  re-registering; a slot that reads a different set of inputs on rerun has its
  edge set updated to match. There is no manual subscribe/unsubscribe.
- **Cycle detection.** A slot that depends on itself (directly or transitively)
  is detected during refresh and throws — the graph is acyclic by construction.
- **`batch` coalesces.** Multiple `set_cell` calls inside `batch(run)` queue
  their invalidation roots; at the outermost batch exit the roots propagate and
  effects flush once. Mutation inside a batch is synchronous; only the
  invalidation propagation is deferred to the boundary.
- **Effects are scheduled, not inline.** An effect rerun is scheduled when a
  tracked dependency invalidates and runs in the subsequent flush (which may be
  the same tick, at batch exit). A rerun does not start until the previous
  cleanup completes. Disposal removes pending reruns, runs the current cleanup,
  and unsubscribes all dependency edges.
- **Signal eagerness (derived construct).** A signal is not a core primitive — it
  is a `memo` slot plus a puller effect: the
  effect reads the slot on creation and after every invalidation, forcing the
  memo to re-materialize. Because the puller runs inside the invalidating
  `set_cell`/`batch`'s effect flush, the value is fresh by the time the mutator
  returns. Disposing the puller effect reverts the signal to lazy behavior (the
  backing value stays readable but is no longer eagerly kept fresh).

## MergeCell and the merge algebra (`#relaycell`)

A **`MergeCell<T, M>`** is a `Source<T>` whose write is a *merge* rather than a
replace: `merge(handle, op)` computes `⊕(current, op)` under `MergePolicy` `M`
and routes the result through `set_cell` — so the `==` store-guard,
store-without-cascade, and `batch` all apply unchanged. A plain **`Cell` is
exactly `MergeCell<KeepLatest>`** (the keep-latest instance); a binding MAY
implement `Cell` as that instance or keep it as a distinct fast path with
identical semantics.

A **`MergePolicy`** is an associative fold `⊕ : T × T → T`. The properties it
satisfies are *selected by the transport contract*, not fixed
(`relaycell-backpressure-analysis.md` §2):

| Property | Requirement | Purpose |
|----------|-------------|---------|
| **Associativity** | **Always** — the irreducible law | Regrouping a run of merged ops never changes the converged state, which is what licenses *variable flush points*: a bounded relay may flush at any post-merge watermark and converge identically. Not a flag; a law every policy MUST satisfy. |
| **Commutativity** | Per policy (`const COMMUTATIVE`) | The *reordering tax* — required only when ops may be applied out of order (concurrent producers / replicas / pages). |
| **Idempotency** | Per policy (`const IDEMPOTENT`) | The *durability tax* — required only for at-least-once / crash-replay. For an idempotent `⊕`, re-applying an op is a no-op, which is exactly the `==` store-guard one layer up: **free dedup**. |

The canonical policies (each names its algebraic structure and flags):

| Policy | `⊕` | Structure | Comm | Idem |
|--------|-----|-----------|:----:|:----:|
| `KeepLatest` | `old ⊕ op = op` | right-zero band | ✗ | ✓ |
| `Sum` | `old + op` | commutative monoid | ✓ | ✗ |
| `Max` | `max(old, op)` | semilattice (total order) | ✓ | ✓ |
| `SetUnion` | `old ∪ op` | grow-only semilattice | ✓ | ✓ |
| `RawFifo` | `old ++ op` | free semigroup (concat) | ✗ | ✗ |
| `CrdtJoin<C>` | `C::merge_from` | join semilattice | ✓ | ✓ |

`KeepLatest` (positional last-writer-wins, **not** commutative) is distinct from
a timestamped LWW register (`CrdtJoin<LwwRegister>`, commutative): both conflate,
they differ only on commutativity — the CRDT-vs-LWW branch. `RawFifo` cannot
conflate (order and multiplicity are meaning); its only bounded-lossless option is
Spill (Phase 3+). `CrdtJoin<C>` wires the existing cell CRDT units
([Merge mechanisms](cell-model.md#merge-mechanisms)) into the algebra without
reimplementing their join.

> **Verification form.** The three properties are algebraic identities over `T`
> values (`(a⊕b)⊕c == a⊕(b⊕c)`, `(a⊕b)⊕c == (a⊕c)⊕b`, `(a⊕b)⊕b == a⊕b`), so a
> binding pins them with **property-based law-tests** (associativity for every
> policy; commutativity/idempotency asserted exactly when the flag is set, plus a
> counterexample proving a cleared flag does not lie) — lazily-rs uses
> `tests/merge_laws.rs`. The cross-language **converged-state determinism**
> invariant (same op multiset, any grouping → same egress) is additionally pinned
> by the `mergecell_algebra.json` compute fixture.

## Invalidation propagation

When `set_cell` changes a value (post-`==`-guard):

1. The cell's dependents are marked dirty (slots) or scheduled (effects).
2. Dirty marks propagate transitively through slot dependents — a dirty slot
   marks its own dependents, and so on. A memo slot that recomputes to an equal
   value stops the propagation (the memo guard).
3. On the next `get` of a dirty slot, the slot refreshes: it pulls each
   dependency (recursively refreshing/ recomputing as needed), and recomputes
   only if a dependency actually changed value.

This is a push-invalidated, pull-recomputed graph — invalidation travels
downstream eagerly (so effects fire), but the new value is computed lazily on
read (so untouched branches do no work).

**Store-without-cascade** (the write-side dual of lazy reads). When `set_cell`
changes a value whose transitive dependent cone contains **no Effect**, the new
value is stored (step 1's dirty-marking of lazy Slot dependents still happens, so
a *future* subscriber reads the current value glitch-free — late-subscribe
correctness) but **no effect flush is scheduled** — there is no active reactor to
run. A binding MAY skip the flush machinery entirely in this case. Combined with
demand-driven derivation on the read side, an **unobserved** reactive node —
pull-derived or push-populated — costs approximately its raw storage: the merge
cost law tiers the write cost by dependent kind (none → store only; lazy-only →
store + O(deps) dirty-mark, no flush; active → store + dirty + flush). A **burst**
of N value-changing writes with no interleaved active read pays the transitive
dirty-mark **once** (dirty-marking is idempotent and monotonic — an already-dirty
Slot is not re-walked), i.e. `N·(==/⊕)` + one dirty-propagation. See
[`relaycell-backpressure-analysis.md`](relaycell-backpressure-analysis.md) §4.0.

## Handles and identity

Handles are stable ids minted monotonically and recycled on dispose. A disposed
handle is inert: reads on a disposed slot return its last cached value if any;
reads on a disposed cell/signal are undefined (the caller MUST not retain a
handle past disposal of its effect/signal puller). Re-entrancy of a disposed
effect is prevented by removing it from the schedule before running cleanup.

## Context layers

- **Single-threaded** — the base context (mirrors lazily-rs `Context`). The
  graph is not `Send`/`Sync`; it lives on one thread/executor. **Unconditionally
  required** of every binding (it is the reactive core).
- **Thread-safe** — a lock-backed counterpart (mirrors lazily-rs
  `ThreadSafeContext`); handles are clonable and the transition function and
  state are `Send + Sync`. Observers fire synchronously within the invalidating
  `send`/`batch` preserving glitch-free pull-based ordering. **Required of any
  binding whose platform exposes preemptive multi-threading or shared-memory
  concurrency** — see [Wire Protocol § Concurrency layers are required](protocol.md#concurrency-layers-are-required).
- **Async** — a separate reactive surface for future-returning computations;
  see [Async Reactive Context](async.md). **Required of any binding whose
  platform exposes an async/future runtime** — see
  [Wire Protocol § Concurrency layers are required](protocol.md#concurrency-layers-are-required).

The single-threaded context is the unconditional base; the thread-safe and async
layers are required **conditionally**. A platform that structurally lacks either
primitive (a strictly single-threaded runtime, a process/actor-isolation model,
or a platform with no suspendable async computation) declares the matching
`thread_safe` / `async` capability as `none` and advertises it, never silently.
The flat [State Machine](state-machine.md) and [State Charts](state-charts.md)
compose with whichever reactive context a binding ships, with identical `send`
semantics.

## Conformance

A reactive context conforms when:

1. The three core primitives (`Cell` / `Slot` / `Effect`) and the handles above
   are implemented; `Signal` (the derived `Slot.eager` construct) is exposed as a
   convenience.
2. `set_cell` is `==`-guarded (equal value is a no-op); `memo` adds the same
   guard to a recompute.
3. Refresh is pull-based and glitch-free: a slot observes consistent inputs;
   untouched branches are not recomputed.
4. Dependencies are tracked dynamically through a tracking stack (edges
   re-registered each recompute; no manual subscribe).
5. Cycles are detected and throw.
6. `batch` coalesces into one propagation + effect flush at the outermost exit.
7. Effects fire scheduled (not inline), cleanup runs before each rerun and on
   dispose, and disposal unsubscribes edges.
8. A `Signal` is materialized by the time the invalidating `set_cell`/`batch`
   returns (eager push).
9. **`Reactive<T>` / `Source<T>` split.** Reads (`get`/`subscribe`) are the
   `Reactive` supertype; writes (`set`/`merge`) are the `Source` sub-interface. A
   derived Slot/Signal is `Reactive` only.
10. **MergeCell + merge algebra (`#relaycell`).** `merge(handle, op)` folds under
    an associative `MergePolicy` and routes through the `==`-guarded `set_cell`
    (so an idempotent policy's no-op merge fires no cascade). `Cell ≡
    MergeCell<KeepLatest>`. Every policy is associative; the `COMMUTATIVE` and
    `IDEMPOTENT` flags match the policy's algebra (verified by law-tests); the
    converged egress state is independent of merge grouping/order for a
    commutative policy (verified by `mergecell_algebra.json`).

### Thread-safe context conformance

The lock-backed context ([Context layers](#context-layers)) is **required of any
binding whose platform exposes preemptive multi-threading or shared-memory
concurrency**. A binding's thread-safe context conforms when it holds these
deterministic properties under concurrent access:

1. Handles are **clonable**, and the transition function and cell/slot state are
   `Send + Sync`; one reactive graph is shared across OS threads.
2. **Observers fire synchronously within the invalidating `send`/`batch`**,
   preserving the same glitch-free pull-based ordering as the single-threaded
   context — a concurrent reader never observes a half-updated graph. "Synchronously
   within" mandates **glitch-free ordering** (every observer that runs sees the fully
   settled graph, never an intermediate state), **not** literal in-lock dispatch. A
   threaded binding **MAY** defer observer dispatch out of the graph lock (so a callback
   may re-enter the context) provided the ordering invariant holds: observers are still
   delivered in dependency order and none observes a mixed state (`#lzspecobserverclarify`).
3. The `==` (PartialEq) cell guard and the `memo` equality guard both hold under
   concurrent mutation: an equal write invalidates nothing, an equal recompute
   suppresses downstream work.
4. The graph lock is **released before user compute/effect/cleanup callbacks**
   run, so callbacks may re-enter the same context without deadlock.
5. An **in-flight recompute is parked on a per-slot generation/condvar sidecar**;
   a stale completion (the slot was invalidated during compute) is discarded and
   the waiter retried against a fresh value rather than observing a mixed state.

> **Verification form.** Concurrent interleaving is **not** a deterministic
> load/replay sequence, so it is not pinned by a portable conformance fixture in
> `lazily-spec`. Each binding verifies its lock-backed context with a
> **synchronization-model checker** over the same semantics above — lazily-rs
> uses Loom (`tests/thread_safe_loom.rs`, behind the `loom` feature). The five
> properties above are the contract that model check exercises; a binding with no
> such tooling MUST at minimum exercise 1–4 under a threaded stress harness.

## Implementation status

The single-threaded reactive context is required of every binding that
advertises the reactive core. lazily-rs, lazily-py, lazily-zig, lazily-kt, and
lazily-js implement it. The thread-safe and async counterparts are required of
any binding whose platform supports them (see [Wire Protocol § Concurrency
layers are required](protocol.md#concurrency-layers-are-required)); a platform
that structurally lacks either declares the matching `thread_safe` / `async`
capability as `none` and advertises it, never silently.
