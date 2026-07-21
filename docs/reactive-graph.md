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

A **cell** is a value-bearing reactive node — a node with a readable value. There
are exactly two kinds of cell and one sink:

| Kind | Handle | Node | Role |
|---|---|---|------|
| **source** | `Source<T, M = KeepLatest>` | `SourceCell` | Written from outside. `set` replaces (invalidating dependents on a `==` (PartialEq) change; an equal set is a no-op); `merge` folds an op `⊕` under [`MergePolicy`](#the-merge-algebra-and-sourcet-m-relaycell) `M`. `M` defaults to `KeepLatest`, so `Source<T>` is a plain source cell and `Source<T, M>` with `M ≠ KeepLatest` is what used to be called a `MergeCell`. |
| **computed** | `Computed<T>` | `ComputedCell` | Computed from upstream. Tracks its dependencies automatically, computes on first read, caches, and recomputes only when read after an upstream invalidation. **Guarded, always**: an equal recompute suppresses downstream invalidation (matches TC39 `Signal.Computed`). |
| **effect** | `Effect` | — | A side-effecting **sink** — no readable value, so nothing can ever depend on it. Reruns whenever a tracked dependency invalidates; an optional cleanup closure runs before each rerun and on dispose. It sits **outside** the cell hierarchy, by capability, not by current degree. |

**`Cell` is the value-bearing-node concept, never a handle.** The word `Cell`
names "a reactive node with a readable value"; the two kinds of cell are the
`SourceCell` and the `ComputedCell` (the arena nodes `Node::Source(SourceNode)`
and `Node::Computed(ComputedNode)`). A caller never holds a `Cell` — the two
handles are the concrete types **`Source<T, M>`** and **`Computed<T>`**. There is
**no `Cell<T, K>` genus struct** and no phantom kind parameter: `Source`'s policy
`M` is a real parameter of the `Source<T, M>` handle, present only where writes
exist. `Reactive` is the umbrella *adjective* — the reactive graph is cells plus
effects — never a type and never a synonym for one kind.

The partition is one axis with both sides covered and no leftover: **a cell's
value comes either from outside it (a `SourceCell`) or from upstream of it (a
`ComputedCell`).** `Effect` has no value to read, so it cannot be folded in — the
sink position is a real boundary, not a naming accident.

A plain cell — `Cell ≡ Source<KeepLatest>` — is the keep-latest instance of the
source kind; this is a **default type parameter**, not a spec assertion. A binding
MAY implement `Source<T>` as that instance or keep it as a distinct fast path with
identical semantics.

**The eager construct is an *eager* `Computed`, not a distinct kind.** The
eager construction is `computed(compute).eager()`: a guarded `Computed` plus a
puller `Effect` that reads it on creation and after every invalidation, so its
value is materialized by the time the invalidating `set`/`batch` returns (readers
never see an intermediate unset state — `relaycell-backpressure-analysis.md`
§4.0). `.eager()` is **declarative and idempotent** and returns the **same**
`Computed` handle, mutated — so the per-write puller of the old `Signal` cannot be
constructed (see *Eager computed cells* under Semantics, and §9.2.2's theorem that
a writer is always a sink). `.lazy()` is the reverse transition; `is_eager()` is
the predicate, so the bare verbs are never confused with a query.

The normative eager semantics are four observable clauses — materialize once at
creation, fresh at mutator return, once per flush rather than once per write, and
disposal that removes only the puller. They are stated under *Eager computed cells*
below and fixtured in `conformance/reactive-graph/signal_*.json`. The
computed-plus-puller construction is the recommended way to satisfy them, not
itself a requirement.

Values are **lazy by default**; call `.eager()` on a `Computed` when eager push
semantics are required. Handles are the two concrete types —
`Source<T, M>`, `Computed<T>` — plus `EffectHandle`: lightweight, copyable ids
over a shared node table (arena slots; see *Handles and identity*), usable only
with the owning context.

**Read is on every cell; write is on the source kind.** Both handles expose
`get` (auto-subscribing) — and *only* `get`; there is no `subscribe`, because
observation is a declared dependency edge, never a registered callback (see
*Reactives have no observers*). Writing is not a supertype/subtype relationship
but a **kind restriction**: `set` (replace) and `merge` (fold under the source's
policy) live on the inherent impl for `Source<T, M>` alone, so
`computed.set(…)` is a *compile error* — no method found, no trait in sight. A
`Computed` reads and never writes; a `Source` does both. The payoff
(`relaycell-backpressure-analysis.md` §4.0): a composite reader that needs to
accept either kind takes a small per-binding read-only view (an enum, or Go's
`Cell[T]` interface below) and the backend chooses the impl — pull-computed,
push-fed source, or polling-computed — behind one type, so ownership of the
mutation (not the type) decides the invalidation source. Where a binding has no
way to restrict methods by type parameter (Go), a read-only interface `Cell[T]`
carrying `Get` is reintroduced, with `SourceCell`/`ComputedCell` as structs — the
same compile error under a different mechanism (§4 of the design).

## API surface

Two constructors and one transition, symmetric with the kernel. `source` /
`computed` / `.eager()` replace the eight old constructors (`cell`, `merge_cell`,
`computed`, `memo`, `slot`, `signal`, `get_signal`, `dispose_signal`) — and
because every `Computed` is now guarded, the old `computed`-vs-`memo` distinction
is gone: `memo` is removed and `computed` **is** the guarded derivation.

| Method | Description |
|--------|-------------|
| `source(value)` | Create a `Source<T, KeepLatest>` — a plain mutable source cell |
| `source::<M>(value)` | Create a `Source<T, M>` whose write folds under policy `M` (was `merge_cell`) |
| `get(handle)` | Read either kind — a `Source` or a `Computed` — computing/refreshing a `Computed` if necessary (auto-subscribes the running computation) |
| `set(handle, value)` | Update a `Source` and invalidate dependents (no-op on `==`) — a compile error on a `Computed` |
| `computed(compute)` | Create a lazy derived `Computed`, **guarded** (an equal recompute suppresses downstream — the guard is never optional, and `memo` folded into this). `T: PartialEq`, the same uniform bound as `source` |
| `computed(compute).eager()` | Make the `Computed` **eager** (attach a puller `Effect`). Declarative and idempotent; returns the same `Computed` handle (was `signal`) |
| `computed(compute).lazy()` | Revert an eager `Computed` to lazy (removes the puller only, keeps the value) — replaces `dispose_signal`; exists only if a binding needs the reverse transition (§9.3.4) |
| `is_eager(handle)` | Predicate: whether a `Computed` currently has a puller attached |
| `merge(handle, op)` | Fold `op` into a `Source` under its policy (`⊕`; routes through `set`, so the `==` guard + store-without-cascade apply) — a compile error on a `Computed` |
| `effect(run)` | Register a side-effecting computation (a sink); `run` may return a cleanup closure |
| `dispose_effect(handle)` | Deschedule, drop edges, run cleanup |
| `dispose(handle)` | Tear down any node kind: detach edges in both directions, clear the node, recycle its slot id. Disposing an **eager** `Computed` also tears down its puller (§9.3.4) |
| `scope()` | Open a **teardown scope**: nodes created through it are disposed together when the scope ends |
| `scope.disarm()` | Disarm a scope — ending it disposes nothing; its nodes revert to context ownership |
| `batch(run)` | Coalesce several source updates into one invalidation + effect flush |

## Semantics

- **Pull-based, glitch-free refresh.** A `Computed` that reads other cells
  always observes values consistent with the current inputs. On `get`, it
  first refreshes its own dependencies (recursively, lazy pull), then recomputes
  only if any dependency actually changed — it never observes a half-updated graph.
- **Every cell is guarded — one rule, two sides.** A cell suppresses an equal
  value. On the source side this is the **`==` guard on `set`**: setting an equal
  value is a no-op, no downstream cascade fires. On the computed side it is the
  **equality guard on recompute**: an equal recompute suppresses downstream
  invalidation — the `Computed`'s value version does not bump, so subscribers see
  no change (matching TC39 `Signal.Computed`). Equality is structural/value
  equality, not reference identity, so two distinct-but-equal values suppress
  invalidation. `T: PartialEq` is the **uniform bound** on every cell, source and
  computed alike — the guard is not a mode a caller opts into.
- **There is no unguarded cell, and no `equals:false` escape.** The guard is
  never wrong: if it suppresses an update you wanted, the value did not encode the
  change. To always propagate, **make the value genuinely `PartialEq`-distinct**
  (encode the distinction you care about into the value), or **use a merge policy**
  to express accumulate/always-apply semantics. This is not a library toggle, and
  there is no unguarded constructor — `memo` (the old guarded form) has been
  removed because `computed` is now guarded and the two are the same thing.
- **Dynamic dependencies.** A tracking stack auto-discovers edges on each
  recompute: every `get` read inside a running `Computed`/effect registers a
  dependency. Stale dependencies from a previous run are removed before
  re-registering; a `Computed` that reads a different set of inputs on rerun has
  its edge set updated to match. There is no manual subscribe/unsubscribe.

> **Implementation note.** The dedup that keeps edge registration idempotent is
> an implementation concern, not an observable one — the contract fixes the edge
> *set*, not how membership is tested. A binding **MAY** dedup by linear scan
> while a node's degree is small; above a wide-fanout threshold it **SHOULD**
> promote to a hash-indexed edge set, so registration stays amortized O(1) in
> node degree and a wide-fanout graph does not degrade to O(n²) per propagation.
> The threshold matters in both directions: below it the linear scan is
> measurably the faster of the two, so an unconditional hash set is a regression
> on the common low-degree case (`#lzspecedgeindex`).
>
> The threshold is **not portable — measure it per binding.** Naively it is
> where a scan of contiguous ids crosses the cost of one hash lookup, so it moves
> with both, and the same number can be right or wrong in the same language
> depending on unrelated choices. In `lazily-rs` that crossover measured near
> degree 170 with the standard library's SipHash and near degree 40 once ids were
> hashed with a multiply-shift finalizer — a 4x shift from changing the hash
> function alone. `lazily-dart` measured 60 under AOT and 96 under JIT, a 1.6x
> spread from *compilation mode* with no code change at all. Copying another
> binding's constant is how a promotion threshold ends up making mid-degree nodes
> slower than the scan it replaced. Across bindings the measured thresholds so
> far are 32, 64, 128 and 160 — there is no family constant.
>
> **Measure the hybrid, not the pure crossover.** The crossover between a
> *pure* scan and a *pure* index is the wrong number, because a list arriving at
> degree T pays the full scan **plus** the one-time index build, with no indexed
> insert at exactly T to amortize against. Every candidate threshold therefore
> parks a regression on its own width, and the pure crossover cannot predict
> where. Sweep the real implementation against the unfixed tree across candidate
> thresholds and take the knee — `lazily-dart`'s pure crossover said 60–96, but
> the hybrid sweep put the worst-case regression at 1.63x for T=64 and 1.31x for
> T=128, so 128 shipped.
>
> Two ways to get this measurement wrong, both observed:
>
> - **Comparing always-indexed against always-scanning inflates the crossover.**
>   It charges the index's overhead on every one-element dependency list to the
>   wide list. `lazily-cpp` first estimated 96 this way against a true 32 — a 3x
>   error. Sweep the threshold constant alone, with everything else fixed.
> - **A width ladder's narrow rungs cannot answer the low-degree question.** A
>   few hundred registrations is noise; `lazily-dart` measured 1.4x run-to-run
>   variance at widths 2–4 and nearly reported a phantom regression at width 96
>   from ladder data. Low-degree behavior needs a separate high-repetition
>   harness, not the tail of the ladder.
>
> Two further hazards, both observed:
>
> - **Demotion needs hysteresis, or it thrashes.** A dependent list oscillates by
>   one on every recompute, because edges are removed and re-registered, so a
>   single shared promote/demote boundary makes a list sitting at the threshold
>   rebuild its index on every recompute. Demote well below the promote
>   threshold, or do not demote at all.
>
>   The cost is severe where the hazard exists and varies far more than the
>   mechanism suggests: **~4x** in `lazily-rs`, **7.67x** in `lazily-js`, and
>   **21.5x** in `lazily-kt` — each at exactly threshold+1 and within noise at
>   every neighbouring width, which is why a ladder must cluster rungs there or
>   it will not see this at all.
>
>   It is **not universal**, and the reason is structural: the hazard needs a
>   list that oscillates by one. `lazily-zig` has no demotion path, so nothing
>   can thrash. `lazily-dart` clears its dependent list wholesale during cascade
>   rather than removing one edge at a time, and no thrash was observable at
>   threshold±1 (0.99–1.05x) — it keeps hysteresis as cheap insurance on the
>   detach path, not because measurement forced it. A binding **SHOULD** check
>   which shape its own recompute has before assuming either result.
> - **A recycled id must not inherit an index.** Where the index is held outside
>   the node — a side table keyed by owner — its entries have to be dropped
>   whenever the list is cleared or the owner is torn down. A binding that
>   recycles ids will otherwise alias a stale index onto an unrelated node.
- **Disposal is explicit.** Handles are copyable ids, not owners, so dropping
  every handle to a node reclaims nothing: without an explicit disposal call the
  node and its edges live as long as the context. A binding whose nodes can
  outlive their usefulness — anything with subscribe/unsubscribe churn —
  **SHOULD** expose disposal for computed and source cells, not only for effects, or a
  workload whose live size is constant still grows without bound in both memory
  and propagation cost. Disposal detaches edges in *both* directions; reading a
  disposed node afterwards is an error, the same contract as disposing an
  effect (`#lzspecedgeindex`).

  **Detection of a stale handle is bounded, deliberately.** A binding that
  recycles ids and checks only the node's *kind* catches a handle naming a
  disposed node of a different kind, but cannot catch one whose id has been
  reused by a new node of the *same* kind — the classic ABA case. Closing that
  requires generational ids or reference-counted handles, and this spec does
  **not** require either: both cost either handle size or the copyability that
  fan-out depends on. Conforming bindings therefore reject the cross-kind case
  and **MAY** admit the same-kind one. Callers must not rely on read-after-
  dispose failing.

  **Garbage collection does not substitute for this.** The reverse edge set is a
  *strong* reference to each dependent, so a long-lived source retains every node
  that ever read it — the same unbounded growth a manual binding has, arrived at
  by a different route. A tracing binding that wants reclamation to follow
  reachability **MUST** make its back-edges weak; until it does, its disposal
  story is exactly the explicit one above.

- **Teardown scopes (`scope`).** A scope records what was created through it and
  disposes that set when it ends. It **bounds teardown, not visibility**: a
  scope's nodes read parent- and sibling-owned nodes freely, and scoping never
  restricts what an edge may point at.

  Ending a scope **MUST** be observationally equal to disposing each of its
  members individually — a scope introduces no disposal semantics of its own, it
  only names a set and a moment. Proved as `disposeScope_eq_disposeAll` in the
  standalone [`lazily-formal`](https://github.com/lazily-hub/lazily-formal)
  `LazilyFormal.Reactive` module. A binding is therefore free to implement the
  scope as a bulk sweep rather than a loop, and **SHOULD**, since reading each
  node's kind from the arena at teardown is cheaper than a per-node dispatch.

  The resulting *graph state* depends only on the set of members, not on their
  order or multiplicity (`disposeAll_order_independent`). Effect **cleanups**
  are a different matter: they are side effects, so the order they run in is
  observable, and a binding **MUST** tear a scope down in reverse creation
  order — dependents before what they read — so a scope never transiently
  dangles inside itself and every binding runs cleanups in the same sequence.
  Order is therefore free for the edge bookkeeping and fixed for the cleanups.

  A scope carries the **same hazard** as `dispose`: ending it tears down its
  nodes even if something outside the scope still reads them. A binding **MUST
  NOT** present scope teardown as safe against that; only reference-counted
  handles close it, and they cost copyable handles.

- **Scope and reachability are different questions.** Disposal and teardown
  scopes answer *"this work is over — free it now"*, deterministically, at a
  point the program names. Weak back-edges and reference-counted handles answer
  *"is anyone still using this?"*, and answer it whenever the collector or the
  last release gets around to it. Neither subsumes the other, and a binding
  **SHOULD** offer both rather than picking one:

  | binding class | scope | reachability |
  |---|---|---|
  | non-GC, no destructors (zig) | scopes, ended at an explicit `deinit`/`defer` | none available; explicit disposal is the whole story |
  | non-GC, destructors (rs, cpp) | scopes, ended by the scope's own destructor | reference-counted handles, **opt-in** — they cost copyable handles, which fan-out needs |
  | tracing GC (js, kt, py, go, dart) | scopes, ended by an explicit call | weak back-edges, which need no user-facing API |

  Reference-counted handles are opt-in in every class because a source read by
  two dependents cannot be moved twice, so making the handle an owner forces a
  clone at every fan-out capture site. Per-*node* destructor ownership is not a
  third option: a node an arena-stored closure can capture must outlive the
  capture, so a handle that borrows the context can only ever be a leaf — the
  constraint that makes the scope, not the node, the right unit of teardown.
- **Cycle detection.** A `Computed` that depends on itself (directly or
  transitively) is detected during refresh and throws — the graph is acyclic by
  construction.
- **`batch` coalesces.** Multiple `set` calls inside `batch(run)` queue
  their invalidation roots; at the outermost batch exit the roots propagate and
  effects flush once. Mutation inside a batch is synchronous; only the
  invalidation propagation is deferred to the boundary.
- **Effects are scheduled, not inline.** An effect rerun is scheduled when a
  tracked dependency invalidates and runs in the subsequent flush (which may be
  the same tick, at batch exit). A rerun does not start until the previous
  cleanup completes. Disposal removes pending reruns, runs the current cleanup,
  and unsubscribes all dependency edges.
- **Eager computed cells (`.eager()`).** Eagerness is not a kind — it is a
  `Computed` with a puller `Effect` attached, produced by `computed(compute).eager()`:
  the effect reads it on creation and after every invalidation, forcing it
  to re-materialize. Because the puller runs inside the invalidating `set`/`batch`'s
  effect flush, the value is fresh by the time the mutator returns. `.eager()` is
  **declarative and idempotent** — a second call is a no-op, so a `Computed` never
  acquires two pullers and the per-write over-compute is structurally
  unrepresentable. `.lazy()` (or disposing the `Computed`) reverts it to lazy
  behaviour (the backing value stays readable but is no longer eagerly kept fresh);
  `is_eager()` reports the current state.

  **Normative eager semantics.** The four clauses below are what a binding
  conforms to. They are stated as observations a caller can make, so that any
  implementation strategy satisfying them conforms — see *Composition is
  recommended, not required* below. (The conformance fixtures still carry the
  historical `signal` filenames; the concept is an eager `Computed`.)

  1. **Creation materializes once.** `computed(compute).eager()` **MUST** run
     `compute` exactly once at creation and **MUST NOT** expose an intermediate
     unset state. A reader immediately after creation observes the computed value
     without triggering a compute of its own.
  2. **Fresh at mutator return.** After a `set` that invalidates the eager
     `Computed`'s dependency cone returns, its value **MUST** already equal
     what `compute` yields from the current sources, with **no intervening
     read**. This is the clause a lazy `Computed` does not satisfy, and it is the
     operational meaning of "eager".
  3. **Once per flush, not once per write.** Inside `batch(run)`, an eager `Computed`
     whose dependencies are written N times **MUST** re-materialize **once**, at the
     outermost batch exit — not once per write. The puller is an effect and
     obeys *Effects are scheduled, not inline*; a `Computed` that re-materializes
     during invalidation rather than during the flush violates this clause even
     though it satisfies (2). N writes inside a batch **MUST** produce exactly
     one compute.
  4. **`.lazy()` removes only the puller.** Reverting an eager `Computed` to lazy
     **MUST** dispose the eager puller and **MUST NOT** dispose the backing value.
     After `.lazy()` the value remains readable, remains correct on read (it reverts
     to lazy recompute-on-read), and **MUST NOT** re-materialize on write. This is
     why the operation is a state transition back to lazy rather than a teardown,
     and why the old `dispose_signal` naming was an inaccuracy.

  **Composition is recommended, not required.** Clauses 1–4 are observable.
  "A guarded `Computed` plus a puller effect" is the construction that satisfies them
  and is what every binding **SHOULD** use — it is five lines over the public API
  and needs no teardown special case. It is deliberately **not** a `MUST`, because
  which nodes exist internally is not something a caller can observe, and this
  specification does not mandate unobservable representation (the same rule that
  lets a binding choose weak back-edges). A binding that welds eagerness into its
  computed-cell invalidation path conforms if and only if it satisfies all four
  clauses — and clause 3 is the one such a binding is most likely to fail, because
  re-pulling during invalidation is earlier than the flush.

  A binding **MUST NOT** make eagerness a node kind in its graph representation:
  the kernel's node enumeration is `SourceCell`, `ComputedCell`, `Effect` — the
  two value-bearing cell kinds plus the sink. An eager `Computed`
  is a `ComputedCell` with an `Effect`, not a fourth kind to dispatch on.
  This is now a `MUST NOT` rather than the old `SHOULD NOT`, because
  `computed().eager()` makes the composition the *only* way to build eagerness: the
  handle a caller holds is the `Computed` itself, read with ordinary `get`,
  and there is no `Signal` type left to ship. The kernel stays closed because the
  DAG positions are closed — the same reason this specification declines to mandate
  weak back-edges is why it need not police a construction that cannot be written.

  Conformance: `conformance/reactive-graph/signal_*.json` (historical filenames).

  **Measured 2026-07-20.** What replaying the three signal fixtures against every
  context each binding ships actually found. Recorded as measurements, not as
  inferences from which types exist — the discipline established by the capability
  table above.

  | Binding | Clauses 1, 2, 4 | Clause 3 | Construction |
  |---|---|---|---|
  | `lazily-js` | pass | pass | composed |
  | `lazily-kt` | pass | pass | composed |
  | `lazily-cpp` | pass (`Context`) | pass | composed |
  | `lazily-py` | pass | **failed, fixed** | welded → composed |
  | `lazily-dart` | pass | **failed, fixed** | welded → composed |
  | `lazily-go` | pass | **failed, fixed** | welded → composed → Memo-backed |
  | `lazily-zig` | 4 fails on `AsyncContext` | **failed on `ThreadSafeContext`, fixed** | composed |

  **Clause 3 caught four bindings across two unrelated mechanisms**, and every one
  of them produced correct values while doing 2–3× the computes — which is why
  none of the other 11 reactive-graph fixtures saw them.

  *Mechanism A, welded eagerness (py, dart, go).* Three bindings independently
  grew a signal-specific slot subclass whose invalidation handler re-pulled the
  signal inline. Re-pulling during invalidation is earlier than the effect flush,
  so the compute count scaled with the number of changed sources. No effect
  existed anywhere in the construction. Nobody coordinated this; the same wrong
  design was reached three times in three languages.

  *Mechanism B, a batch that does not bound the flush (zig).* `set_cell` flushed
  effects unconditionally while `batch` only nested a depth counter, so a
  correctly composed puller still ran once per write. A composition is not
  sufficient if the batch boundary does not gate the flush.

  **The async surface is the family's weakest, systematically.** `lazily-cpp`'s
  `AsyncContext` exposes no signal API at all and its async slots carry no
  dependency graph; `lazily-zig`'s async context has no lazy mode, so every
  derived slot is eager whether or not a puller is attached and clause 4 is
  unobservable there; `lazily-py` and `lazily-dart` ship no async signal
  constructor. A binding **MAY** omit `signal` from a context — clause conformance
  is per surface, and a context that does not offer the constructor is not
  non-conformant. What it **MUST NOT** do is offer it and diverge silently.

  `lazily-go` was the deepest case and is now resolved. Its `Memo` implemented
  the `==` guard by recomputing during invalidation, so a memo-backed signal
  could not satisfy clauses 3 and 4 while a slot-backed one lost equal-recompute
  suppression — neither could hold, because the cascade **consumed reverse edges
  as it walked**. Marking a dependent clean without recomputing meant it never
  re-registered, so its source could no longer reach it and the next write was
  lost at depth two, which is `hybrid_serves_stale_value_at_depth_two`.

  Its sync plane now uses a non-consuming mark-frontier walk with a pull-time
  guard, converged on `lazily-rs`'s model rather than a new design. Two details
  from that convergence are worth recording for any binding attempting the same
  migration, because both were initially judged redundant and both were forced
  back by the corpus:

  - **Notifying dependents when a slot's value actually changed** is what makes
    the pull walk *order-independent*. Without it, a dependent that refreshes in
    an unlucky order observes "no dependency changed" and keeps a stale cache.
    Full-cone marking does not subsume it.
  - **A force-run flag on effects.** Without one the guard cannot reach effects
    at all: a transitively scheduled effect runs before the memo can suppress it.
    The pull-time re-mark must *not* re-schedule effects, or an effect re-runs
    itself mid-flush.

  Its `AsyncContext` was deliberately scoped out and still does value-only
  suppression where the sync plane suppresses downstream entirely. That
  divergence between a single binding's two planes is recorded in the binding
  rather than resolved here.

### Reactives have no observers (`#lzdartobservercow`)

**No reactive exposes an observer API.** Not a `Source`, not a `Computed`,
eager or lazy — no kind of cell. No `subscribe`, no `on_write`, no `on_change`, no
`add_listener`, no callback collection of any kind attached to a reactive node. A
binding **MUST NOT** provide one, and **MUST NOT** carry per-node storage
reserved for one.

The clause is stated on *reactives* rather than on `Cell` because it was first
written too narrowly and a second registry survived it: `lazily-py` carried a
`Signal.subscribe` — documented in its own docstring as "an external
(non-reactive) change callback", with the real graph edges tracked separately —
that a Cell-only prohibition did not reach. It deduplicated by equality via a
`set`, the same defect this section elsewhere calls a `MUST NOT`. If the rule is
worth having it is worth having on every node kind, so it is written that way.

This is a `MUST NOT` about a mechanism rather than a behavior, which is unusual
for this document. It is stated that way because the mechanism cannot be made
safe by constraining it — every constraint below was tried, written down, and
abandoned.

#### Observation is a graph edge, not a callback

Reading a cell inside a computation *declares a dependency*. The tracking stack
records the edge, invalidation propagates structurally, and the graph decides
when dependents run. Nobody registers anything. That is the whole design, and
every guarantee the family makes — batching, glitch-freedom, coalescing,
cone-settled consistency — follows from the graph knowing what depends on what.

A callback list attached to a cell knows none of that. It cannot batch, because
it has no notion of a cone to settle. It cannot be glitch-free, because it fires
mid-update by construction. It cannot participate in scope teardown, because it
is not a node. It is the observer pattern, living inside the reactive primitive
and bypassing it.

**This is the substance behind a common objection: "isn't a reactive just an
observer with extra steps?"** While `Cell.subscribe` existed the answer was
embarrassing, because in four bindings it was *literally true* — there was an
observer registry inside the cell, and callers could reach it. The honest answer
is that a reactive is not an observer, and the way to be able to say so is to not
ship one. Observation is declarative and structural; if a caller is registering
callbacks against a value, they have left the reactive model, and the library
should say so rather than provide a door.

#### How to tell an edge set from a registry

A binding auditing itself against this clause needs a test that does not depend
on what a collection is *called*, because naming is exactly what hid these:

> **Anything that survives an invalidation is not a graph edge.**

Dependency edges are re-discovered on every recompute — the tracking stack clears
them and the next run re-registers whatever it actually reads. That is what makes
dependencies dynamic. A collection that *persists* across invalidation is
therefore not participating in dependency tracking, whatever its name, whatever
its docstring, and whatever it sits next to.

This criterion is stated because it was arrived at expensively. `lazily-py`
carried **three** registries — on `Cell`, on `Signal`, and on `Slot` — and every
one of them was either labelled or assumed to be dependency-graph state. Two
separate readers, with the source open, misclassified one each. In every case the
registry sat beside a real edge set with a similar name (`_subscribers` next to
`_parents`), and in every case the deciding fact was a single line: the edge set
is rebound and cleared on invalidation, the registry is iterated and kept.

Apply the criterion mechanically rather than reading intent. It resolves all
three without argument, and it is the only check here that does not require
trusting a description.

#### Effect and observer are not two spellings of one thing

The distinction is worth stating flatly, because the two look interchangeable at
the call site and are not:

| | **Effect** | **Observer** (removed) |
|---|---|---|
| Registration | implicit — reading a value inside the body declares the edge | explicit — hand a callback to a node |
| Position | a **node in the graph** | a callback list **hanging off** a node |
| Runs | once per settled cone | once per write |
| Batch | honours it — one run per batch | ignores it — one call per write |
| `==` store-guard | sees the coalesced result | cannot see a suppressed write at all |
| Computed guard | respects it — no run on an equal recompute | not subject to it |
| Merge `⊕` | sees converged state — the only guaranteed value | sees a flush-timing artifact (below) |
| Glitch-free | yes — inputs are mutually consistent | no — fires mid-update by construction |
| Dependencies | dynamic; re-discovered every run | none; bound to one node forever |
| Teardown | disposed with its scope | manual, and outlives its scope |
| Per-node cost when unused | zero | storage on every node |

**Coalescence is the row that matters most, and it is not one mechanism but
five.** This family coalesces at every layer: the `==` store-guard drops an equal
write entirely; the computed guard drops an equal recompute so downstream never
learns; `batch` folds many writes into one invalidation and one flush;
store-without-cascade skips effect scheduling for a cell whose cone holds no
effect; and the **merge algebra folds a run of ops into one state through `⊕`**.
Every one of those is the graph deciding that some change does not need to be
propagated — which is most of what makes a lazy reactive graph cheaper than
recomputing everything.

**Merge coalescence is where an observer fails hardest, and it is worth spelling
out because it is not a quality-of-implementation matter.** Associativity is the
irreducible law of `MergePolicy`, and what it buys is *variable flush points*: a
bounded relay may flush at any post-merge watermark and converge identically. The
converged state is guaranteed; **the sequence of intermediate values is not.**
Two runs of the same program over the same ops may legitimately produce different
intermediate values under different backpressure, buffer sizes, or transports.

An `Effect` reads the converged state, which is the value the algebra actually
promises. An observer fires on intermediate writes — so what it receives is an
artifact of flush timing rather than data, and it is non-deterministic *by
design*, not by defect. A caller cannot write correct code against it, because
there is no contract there to be correct against.

Last-writer-wins sharpens this to a point. `KeepLatest` is `old ⊕ op = op` — the
new op annihilates the previous state — and **`Cell ≡ Source<KeepLatest>`**,
so every plain source cell in the family is already an LWW instance. Under a timestamped
LWW register (`CrdtJoin<LwwRegister>`) a losing write is dropped outright: after
convergence, it never happened. An observer that fired on that write reported an
event the system has since decided did not occur, and any side effect it took —
a log line, a queue push, a paint, an outbound message — is now describing a
state that no replica will ever agree existed. An `Effect` never sees it, because
it observes only what survived the merge.

That is the general shape of the whole objection, stated at its most concrete:
**observers report writes; the system's actual semantics are about values that
survive.** Those are different questions, and in a coalescing, converging,
distributed graph they diverge constantly.

An `Effect` is downstream of all four. It sees what the graph decided was worth
propagating, which is why it can be glitch-free and why an unobserved subgraph
costs nothing to write to.

An observer is upstream of all four and outside all of them. It fires on the raw
write, before coalescence has a chance to apply. That is not a different
observation strategy; it means a caller holding an observer is looking at a
system whose central optimization is invisible to them, and cannot tell the
difference between a change that mattered and one the graph suppressed.

#### Use an Effect

Everything an observer expressed, an `Effect` expresses:

```
// instead of: cell.subscribe(cb)
ctx.effect(|ctx| cb(ctx.get(&cell)))
```

The effect is batched, glitch-free, participates in teardown scopes, and is
disposed by handle. Where a caller wants both the previous and the new value —
the state-machine `on_transition` shape — the effect captures the previous value
in its closure; see `lazily-rs` `state_machine.rs` for the reference form.

The behavioral difference is real and intended: under a `batch`, an effect
observes the *settled* value. Writing `A → B → C` inside one batch reports
`A → C`. Intermediate states are not observable, because that is what a batch
asserts. A caller who did not want that should not have opened a batch.

#### Use a Topic when you need every transition

A `Cell` is a **value**: latest-wins, batched, glitch-free. A stream of every
transition is a different thing, and the family already has it — `Topic`, present
in all eight bindings, with cursors and durability. `Topic.subscribe` keeps its
name because a topic genuinely *is* a subscription: an ordered stream a consumer
reads at its own position.

The design error this section removes was a `Topic` hiding inside a `Cell`. A
consumer needing every write — a mutation log, a replication feed, a persistence
tap — should publish to a topic. That also makes the cost honest: only machines
that actually expose a stream allocate one, and a plain cell pays nothing.

#### Why not keep it, constrained

Recorded so the argument is not re-run from scratch. `Cell.subscribe` was
specified in detail before being removed, and each clause below was a genuine
attempt to make it safe:

- **Firing order is registration order**, because a `set`- or hash-backed
  collection reorders on rehash and `lazily-go`'s map iteration is deliberately
  randomized. Four bindings had four answers.
- **No deduplication by callback identity or equality**, because two components
  subscribing the same bound method silently share one registration and the first
  to unsubscribe cancels the second. `lazily-py` deduplicated by equality,
  `lazily-zig` by address.
- **Subscribe during notify is deferred**, or a self-feeding observer extends the
  loop it is running in and never terminates.
- **Unsubscribe during notify takes effect immediately**, because in a
  manually-managed binding `unsubscribe` is routinely the step before freeing the
  state the callback reads, so one more call is a use-after-free.
- **Disposers latch**, or an unlatched second call removes a later registration
  belonging to a caller who never asked.
- **Delivery is per write and `batch` does not coalesce it** — which put the
  mechanism in permanent conflict with the batching model it sat beside.

Six clauses, four bindings, and the specification was still wrong twice in a
single day: it omitted a violated clause in one binding, and its central argument
cited two bindings that had never implemented the mechanism at all. A primitive
requiring six normative clauses to be safe, that still diverges across the
family, and whose delivery discipline contradicts the surrounding model, is not
under-specified. It is misdesigned.

Two things settled it: **memory carried by the graph itself, and semantics that
were footguns at the edges.**

The memory is measured, not estimated. Removing the observer API from
`lazily-zig` moved `@sizeOf(Cell(u64))` from **168 bytes to 32** — 136 bytes,
81%, reclaimed from *every cell in every program* whether or not anything ever
registered. It was not only the callback collections: the reentrancy counters
(`notify_depth`, `before_notify_depth`, and two tombstone flags) and the
monotonic registration counter were all unconditional per-node state that existed
solely to make the notify loop safe. At cell-family scale that is the dominant
memory term in the graph, paid by every reactive value to support a feature with
one caller family-wide. A reactive graph's whole value proposition is holding
many nodes cheaply; a per-node cost multiplied across the graph is the one kind
of overhead it cannot absorb.

The semantics were worse, because the failures were all at the edges where they
are hardest to find. Delivery that ignores `batch` while everything beside it
honours it. Firing order that depends on a collection's rehash. Two components
sharing a bound method and silently sharing one registration, so the first to
unsubscribe cancels the second. A disposer that removes a *later* caller's
registration. An observer invoked once more after asking to stop, which is
harmless under a tracing collector and a use-after-free without one. Each of
these is fine in the common case and wrong in a case the caller cannot see
coming, which is the definition of a footgun rather than a bug: correct code and
broken code look identical at the call site.

Underneath all of them is the defect no clause could patch: **an observer cannot
distinguish batching from coalescence.** It receives a flat sequence of callbacks
with no framing. Three invocations may be three separate updates or one logical
update whose writes were grouped, and nothing in the callback distinguishes them
— there is no signal for where an update begins or ends. Nor can it see what the
graph coalesced away: a write dropped by the `==` store-guard, a recompute
dropped by the computed guard, a flush skipped because the cone held no effect. So
"the value did not change", "nothing was written", and "the graph decided this
did not need propagating" are all the same non-event to an observer. It is an
event stream stripped of both its transaction boundaries and its elisions.

This is not a missing feature to be added. It follows from sitting outside the
graph: the graph is what knows where an update starts and stops, and a callback
list attached to one node is structurally unable to observe that. An `Effect` has
the framing for free, because running once per settled cone *is* the transaction
boundary. The two mechanisms are therefore not two ways of observing a value —
one can express "this update is complete" and the other cannot, at any level of
specification effort.

#### Conformance

There are no observer fixtures. The clauses above were removed along with the
mechanism, and `conformance/reactive-graph/observer_*.json` no longer exists. A
binding conforms to this section by not having the API.

`lazily-rs`, `lazily-cpp`, `lazily-js`, and `lazily-kt` never implemented one and
require no change. `lazily-py`, `lazily-dart`, `lazily-go`, and `lazily-zig`
carried one and remove it, re-expressing `on_transition` as an effect.

The reactive-graph fixtures that remain cover disposal, teardown scopes, and
eager computed cells. They require `TeardownScope` (`ctx.scope()` / `disarm()`)
and dependency-graph introspection (`dependents_of`, `dependencies_of`,
`cleanup_order`). Every binding replays this corpus as of 2026-07-19.

**The eager-computed fixtures (historical filenames `signal_*.json`) need one
observable the rest of the corpus does not: `computes_of`.** It maps a node id to
the cumulative number of times its compute function has run, counted from the
start of the scenario. A runner **MUST** count every invocation of the compute,
including the one at creation, and **MUST NOT** reset it per step. This key exists
because an eager `Computed` and a lazy `Computed` return identical values for every read
sequence — the only caller-observable difference between them is *when* compute
runs, so a corpus that asserts values alone cannot distinguish `computed().eager()`
from `computed()` and will pass against a binding that implements the former as the
latter.

Three ops are specific to these fixtures. The caller-facing transitions are
`.eager()` / `.lazy()` (§*Eager computed cells*); the fixture ops retain the
historical `signal` / `dispose_signal` names, which a runner maps to those
transitions (create-eager and revert-to-lazy). A runner **MUST** accept these op
names — the runner panics on an unknown op, so this acceptance is the contract:

| op | shape | meaning |
|---|---|---|
| `signal` | `{id, reads, offset}` | create a guarded `Computed` (compute is `sum(reads) + offset`, the same convention as `computed`) and make it eager — the `computed(…).eager()` construction |
| `dispose_signal` | `{id}` | revert an eager `Computed` to lazy (`.lazy()`) — the puller only, **not** a node teardown, see clause 4 |
| `batch` | `{writes: [{id, value}, ...]}` | perform every write inside one batch; invalidation propagates and effects flush once, at the outermost exit |

`batch` is a single op rather than a `begin_batch`/`end_batch` pair so that a
runner need not carry nesting state. Bindings whose batch API is a closure take
the writes as the closure body; bindings with explicit begin/end call them
around the writes. Note that `batch` also appears in the `reliable-sync` and
`collections` areas with unrelated semantics — these are per-area op
vocabularies, not one global namespace.

**Fixture shape is declared, not inferred.** Every `ReactiveGraph` fixture
carries a top-level `"shape"` field, either `"steps"` or `"scenarios"`. A runner
**MUST** switch on that field rather than probing for whichever key happens to be
present, and **MUST NOT** special-case a fixture by filename — the first runner
written against this corpus did exactly that, which goes stale silently the
moment a second `scenarios` fixture is added. The schema suite cross-checks the
declaration against the keys actually present, so `shape` cannot drift from the
fixture it describes.

The two shapes are not interchangeable and the split is deliberate. A `steps`
fixture asserts a single trace. A `scenarios` fixture asserts a **relation
between two op streams** — `scope_teardown_equals_fold_of_disposals.json` claims
that ending a scope is observationally equal to disposing its members
individually, and a single `steps` array structurally cannot express "these two
paths must agree." It names the scenarios that must agree in
`expected.observationally_equal`.

One trap in that fixture, stated here because every runner will hit it:
**`cleanup_order` is cumulative across a scenario, not per-step.** The
`individual_disposal` scenario spreads three disposals across three steps and
pins the whole resulting order on the last of them, while `scope_teardown`
produces all three from a single `end_scope`. A runner reading `cleanup_order`
per-step will see the scenarios disagree and report a divergence that is not
there.

## The merge algebra and `Source<T, M>` (`#relaycell`)

A **`Source<T, M>`** is a source cell whose write is a *merge* rather than a
replace: `merge(handle, op)` computes `⊕(current, op)` under `MergePolicy` `M`
and routes the result through `set` — so the `==` store-guard,
store-without-cascade, and `batch` all apply unchanged. A plain **`Cell` is
exactly `Source<KeepLatest>`** (the keep-latest instance, the default of the
one source kind); a binding MAY implement it as that instance or keep it as a
distinct fast path with identical semantics. The policy `M` is a real parameter
of the `Source<T, M>` handle, so it exists exactly where writes exist and is
absent on the computed side — never a third parameter every signature must spell.

> **Theorem — merge policies must be cheap (§9.2.1).** `MergePolicy::merge`
> **MUST NOT** block and **SHOULD** be O(1)-ish in the size of `old`. The algebra
> **is** the convergence guarantee, so the fold stays synchronous; the async or
> expensive work that *produces* an op lives in the `Effect` that feeds the cell,
> never in the fold. In a `ThreadSafeContext` the fold runs under the mutex, so an
> expensive `merge` holds the lock for its duration. This constrains
> implementations rather than observable behaviour, so it is **review-enforced**,
> not fixtured — the same construction the observer prohibition uses.

### Feeding a `Source` from another reactive

A recurring question, answered here because the answer is not obvious and the
failure mode is one cycle detection cannot see.

**A `Source` never acquires a dependency edge.** That is what makes it a
source: source and computed partition the graph by incoming edges, so a node fed by
the graph would be both, and `Computed → Source → Computed` would become
constructible. So "feed this source cell from that reactive" is **not** a new
capability on the cell.

> **Theorem — a writer is always a sink (§9.2.2).** Writing is not having a value:
> anything whose job is to write *reads* something and produces no readable value,
> which is incoming edges and no value — the `Effect` position. So a network-fed
> cell, a feedback writer, and an eager puller are each an `Effect`, not a new node
> kind. The kernel is closed because the DAG positions are closed. The family
> reached this answer three times from three directions — eager values (proposed as
> `Signal`), feedback (proposed as `FeedbackEffect`), and writer encapsulation —
> and each was an `Effect` composed with `set`/`merge`/`.eager()`. Stating it once
> retires the question; only the *ergonomics* (a named `feed_async` constructor)
> stay open, and those wait on two real call sites.

So feeding a source is an `Effect` that reads the reactive and calls `merge`:

```
effect(|ctx| { merge(acc, ctx.get(upstream)) })
```

The edge belongs to the effect. The cell stays edge-free, the partition holds,
and the construction needs no new node kind — the same answer the family gave for
eager values.

**Delivery is per settled cone, not per write.** The effect runs once per flush
carrying the post-coalescence value, so `1 → 2 → 3` inside a batch produces
**one** merge, of `3`. This is a feature rather than a limitation: the
intermediates were never materialized, because eliding them is what a lazy graph
is for. An `Effect` is the only mechanism with the framing to do this correctly —
it sees a settled value at a boundary, where an observer would see raw writes
with neither.

**Therefore merge granularity is flush granularity, and this MUST be stated
wherever the construction is offered.** With a non-idempotent policy (`+`, count,
append-to-log) the accumulated result depends on how writes were batched: three
unbatched writes fold three times, the same three writes inside a batch fold
once. That is not a defect — it follows from *Effects are scheduled, not inline* —
but the accumulator is the case callers reach for first, and it is the case where
the difference is visible.

**For an exact fold over every operation, do not drive it from a dependency
edge.** Drive it from explicit `merge` calls or from a `Topic`:

| driver | merges performed | fold is over |
|---|---|---|
| explicit `merge()` calls | one per call, batched or not | **every op** — exact |
| `Topic` subscription | one per event | **every op** — exact |
| dependency edge, via an effect | one per settled cone | **settled values** — flush-granular |

The first two are exact because the caller or the topic decides how many
operations exist. The third is flush-granular because the *graph* decides, and
deciding not to produce an intermediate is the graph working as designed. This is
the same event-versus-state split recorded in
`relaycell-backpressure-analysis.md` — retained events versus coalescible state —
and it is why the answer to "I need every transition" is `Topic`, not a new
capability on a reactive.

**`merge` folds synchronously inside a `batch`; only propagation defers.** This
follows from `merge` routing through `set` and from *Mutation inside a batch
is synchronous*, but it is stated explicitly because "does batching lose my
merges?" is the first question the accumulator case raises. It does not. Every
`merge` call folds when it is called. What a batch defers is the invalidation and
the flush, so `N` calls inside a batch produce `N` folds and **one**
invalidation.

### Feedback: the construction cycle detection cannot see

An effect that reads `R` and merges into `M`, where `M` is upstream of `R`,
closes a loop through the **scheduler** rather than through the graph. It is not
a dependency cycle, so the acyclicity check will not fire.

> **Theorem — feedback is when an argument is also a dependency (§9.2.3).** An
> `Effect` relates to a cell in two ways that look alike and behave nothing alike.
> A **write target** is an *argument*: passed in, captured by the closure, known
> statically, creating **no edge** — and, because `set`/`merge` are kind-restricted
> to `Source`, an effect cannot even take a `Computed` as a write-argument
> (it does not compile). A **read** is a *dependency*: discovered at run time by
> the tracking stack and re-discovered on every rerun. **Feedback is exactly the
> case where an effect writes a cell it also reads** — a write-argument that is
> also in `deps(E)`. Nothing about that is a graph cycle (the argument is no edge),
> which is why acyclicity never fires and the loop closes through the scheduler.
> Prefer this phrasing over "an effect that writes into its own dependency cone,"
> which makes a scheduler property sound like a graph one.

This is deliberate and it is the family's **only** way to express feedback: the
dependency graph is acyclic by construction, so a cycle cannot be an edge. Closing
it through the scheduler makes each iteration a flush, which bounds it in time and
makes it observable — a discrete-time recurrence rather than an unbounded walk:

```
x_{n+1}  =  x_n ⊕ f(x_n)
```

**Termination needs two properties, and the policy's algebra supplies only one.**

Where `⊕` is a **join on a semilattice** — idempotent, commutative, associative,
the properties a CRDT policy carries — every step satisfies `x_{n+1} ⊒ x_n`, so
the state traces a non-decreasing chain. That is the ascent, and it is all the
join gives you.

**It does not give you termination.** The chain stabilizes only if the lattice
also satisfies the **ascending chain condition** — no infinite strictly
increasing chains — and idempotence, commutativity and associativity imply
nothing about chain height. A G-Set or OR-Set over an unbounded domain is a
perfectly good join semilattice whose chain ascends forever if `f` keeps
producing fresh elements; LWW over unbounded timestamps is the same. **Most CRDT
policies are not finite-height.** A policy declaration therefore does *not*
certify that a feedback loop over it terminates; ACC is a separate property of
the value domain and must be established separately.

**ACC and bounded height are different properties, and the weaker one is the one
that matters.** ACC says no ascending chain is infinite. *Bounded height* says
there is a single constant `H` bounding the length of every chain. Bounded height
implies ACC; the converse fails. A witness: take `⊥`, a top `⊤`, and for each
`n ≥ 1` a disjoint ladder `(n,1) ⊏ … ⊏ (n,n)`, with joins across different
ladders landing on `⊤`. Every ascending chain is finite — so ACC holds — while
chain lengths are unbounded, so no `H` exists. Termination needs only ACC. The
distinction is recorded because a flag can only ever declare the *stronger*
property (see below), so the two must not be written as synonyms.

Where ACC does hold, the `==` store-guard is the fixpoint detector: once the join
stops moving the value, nothing invalidates and the cascade ends. `f` need not be
monotone for the ascent, which is why this is **not** the classical
monotone-framework result — Kleene iteration requires a monotone transfer
function and delivers the *least* fixed point. This construction reaches *a*
fixed point and offers no leastness guarantee.

**The termination condition, stated correctly, is `x ⊕ f(x) == x`** — the loop
ends exactly when the store-guard suppresses. Two consequences that an earlier
draft of this section got wrong:

- **An identity is sufficient, never necessary, and need not exist.** If `f(x)`
  is the policy's identity the step is a no-op, but any absorbing or saturating
  value is equally a fixed point — a `Sum` at its maximum absorbs every op. And
  a `MergePolicy` is only required to be an *associative fold*; nothing mandates
  a unit. `KeepLatest` is a right-zero band and has none, so "terminates when
  `f` yields the identity" is not merely false there, it is undefined.
- Correspondingly, a non-idempotent policy does **not** diverge by construction.
  It has no *guaranteed* fixed point; whether it reaches one is a property of
  `f` and the value domain, and the caller owns that argument.

### The three termination classes

The split is not two-way, and the default policy is in the third class.

| `⊕` | recurrence | termination |
|---|---|---|
| join with ACC | monotone ascent, no infinite ascending chain | **always halts** |
| join without ACC — G-Set, OR-Set, LWW over unbounded domains | monotone accumulation | halts iff the accumulated set is finite; **semi-decidable** |
| **`KeepLatest`** and other idempotent-but-not-commutative bands | `x ⊕ op = op` collapses it to `x_{n+1} = f(x_n)` | **undecidable** — unrestricted iteration of an arbitrary function |
| non-idempotent — `+`, `append`, counters | accumulates | no guarantee; halts at an absorbing or saturating value |

**`KeepLatest` is the case a caller will actually hit**, because
`Cell ≡ Source<KeepLatest>` — an effect that reads a `Computed` and writes back to
a plain source cell is the most reachable feedback loop in the family. Under a right-zero
band the merge discards prior state entirely, so there is no ascent, ACC is
irrelevant, and the lattice framing does not apply at all. What remains is
`x_{n+1} = f(x_n)` over unbounded state with arbitrary `f`, which is **Turing
complete**: no analysis can decide in general whether such a loop halts.

A caller in that class cannot appeal to the algebra. They must supply one of: a
decreasing measure, an iteration bound, or a cancellation observed in the effect
body (see below).

Accordingly:

- A caller building a scheduler-closed feedback loop **MUST** be able to state
  why it terminates. The policy's declared algebra is sufficient evidence **only**
  for a join over a domain satisfying ACC. In every other class the caller owes
  an argument the specification cannot supply.
- Bindings **MUST** bound the **effect-drain iteration count** within a single
  flush, and report exhaustion rather than spinning. Note this is *not*
  re-entry depth: every binding surveyed guards re-entrant flushes and returns
  immediately, so the loop is a flat unbounded drain at constant stack depth, and
  a re-entry-depth bound would be pinned at 1 and could never fire.

  The bound's **value** is deliberately unspecified and is not part of the
  contract — it is a binding's tuning parameter, and pinning a number would make
  a legitimately long cascade non-conformant. What is normative is that the
  drain has an exit other than an empty worklist, and that taking that exit is
  **observable**: exhaustion **MUST** surface as a distinguishable outcome
  (a raised error, a reported diagnostic, a context-level status) and **MUST
  NOT** be a silent truncation of the cascade. A silently truncated flush leaves
  the graph in a state no clause of this specification describes — dependents
  marked dirty with their effects never run — which is worse than the livelock
  it replaced, because it is indistinguishable from convergence.

  **Why this was raised from SHOULD.** Three flush loops were read directly
  (lazily-rs `Context::flush_effects` and `ThreadSafeContext::flush_effects`,
  lazily-js `flushEffects`). All three are re-entrancy-guarded flat drains whose
  only exit is an empty worklist; **none bounds anything**. A SHOULD that no
  surveyed binding implements is not a requirement, and the failure it permits
  is a silent livelock on a thread that has starved whatever would diagnose it.
  The bound is also the **enabling condition for fixturing this section at all**:
  a conformance runner cannot replay a divergent feedback loop against a binding
  whose only exit is convergence, because the fixture hangs the runner. This
  section has stood as unfixtured normative prose precisely because there was no
  bounded failure mode to assert against.

**Where a cancellation can be observed.** In a synchronous context the flush does
not return to the caller between iterations, so the calling thread cannot observe
an interrupt and in fact starves whatever would deliver one. The available yield
point is the **effect body**, which is caller code running once per iteration;
declining to write ends the cascade, because an empty worklist is the drain's only
exit. Async contexts additionally suspend between iterations. **Unmeasured:
whether any binding's async drain observes cancellation between iterations has
not been checked.**

**Exhaustion SHOULD say what was cycling.** A bound that reports only that it was
hit sends the reader to a debugger on a thread that has just stopped livelocking.
A binding **SHOULD** report the nodes that re-ran repeatedly and, where cheap, the
repeating values — the difference between *"drain exhausted after N iterations"*
and *"drain exhausted; `acc` and `total` alternated"*. Only the second is
actionable. Representation is a binding's choice.

### Termination state belongs in the graph, not in a closure

The stop predicate that ends a feedback loop **SHOULD** be a `Computed`, read by
the effect, rather than a branch buried in the effect body:

```
done = computed(|ctx| ctx.get(acc) >= threshold)
effect(|ctx| { if ctx.get(done) { return } merge(acc, f(ctx.get(upstream))) })
```

This is a recommendation about where to put a condition, not new surface — it is
a `Computed` and an `Effect`, both already kinds. What it buys:

- **It is inspectable.** Other nodes may read `done`; a UI can show it; another
  effect can react to it.
- **It is fixturable.** A fixture can assert `done` transitions and that merging
  stops. A predicate inside an effect body is opaque to the corpus, which is part
  of why this area went untested.
- **It is reviewable.** The termination argument the clause above requires a
  caller to *state* becomes a named node rather than a comment.

The shape is legal under the source/computed partition, which is worth checking
explicitly because it looks circular: `acc → done → effect → acc`. The final hop
is a **write**, not a dependency edge, so `acc` acquires no incoming edge and no
dependency cycle exists. It remains scheduler-closed, one iteration per flush.

It does **not** make termination decidable. A `done` that never becomes true
diverges exactly as before; the drain bound remains the backstop.

### Accumulators

An accumulator is a **`Source<M>`** under an accumulating policy. That is what
the merge algebra is for.

A **`Computed` cannot be an accumulator**, for two independent reasons, and the
second is a live hazard:

1. **No self-edge.** A `Computed`'s value is a function of its dependencies'
   *current* values; accumulation is a function of history. Reading its own
   previous value would be a self-dependency, which the acyclic graph forbids.
2. **Recomputes are elidable, so an impure workaround silently loses data.** A
   compute body closing over a mutable counter compiles everywhere and looks
   correct. But the graph is free *not to run it*: the guard suppresses a
   recompute whose value is unchanged, a `Computed` with no readers never runs, and
   a batch coalesces N invalidations into one recompute. Each of those drops an
   increment. A binding **MUST NOT** document or example this pattern.

The structural rule, stated once because it decides these questions generally:

> **Memory of its own past implies a `Source`.** A `Computed` must be
> recomputable from its dependencies, and a value determined by history is not.
> This is why a `Source<M>` is a source even though it computes —
> `⊕(current, op)` reads its own prior state, which no `Computed` may do.

The exception that confirms it: a `Computed` folding a **`Topic`**'s retained events
is an ordinary derivation, because the history is materialized in the topic and
the fold is a pure function of current state.

| pattern | where history lives | |
|---|---|---|
| `Source<M>` + accumulating policy | in the cell (a source) | ✅ |
| `Computed` folding a `Topic`'s retained events | in the topic | ✅ the fold is pure |
| `Computed` closing over a mutable counter | nowhere reachable | ❌ loses increments under elision |

Recall also that driving `merge` from a dependency edge is flush-granular, so an
accumulator fed that way counts *flushes*, not writes. For an exact count, drive
it from explicit `merge` calls or from a `Topic`.

### There is no `fixpoint` construct, and this records why

A termination construct was designed for this section and **declined**. Recorded
briefly so it is not re-derived; this is rationale, not specification.

The proposal was a `fixpoint` restricted to policies declaring a new
`BOUNDED_HEIGHT`, plus a `fixpoint_with(cell, f, measure)` taking a
strictly-decreasing measure. Three reasons it failed:

1. **The flag would be unverifiable.** `COMMUTATIVE` and `IDEMPOTENT` are honest
   because they are *refutable by sampling* — one counterexample disproves a
   claim; neither is confirmable, and this document does not pretend otherwise.
   ACC is **not even refutable**: every finite chain observed is consistent with
   it. The stronger bounded-height-with-constant *is* refutable and is vacuous —
   `Max` over a 64-bit integer has height `2^64`. **A declared property that is
   unverifiable or vacuous is worse than no property**, and that test generalizes
   past this proposal.
2. **It could not cover the reachable case.** `Cell ≡ Source<KeepLatest>`, and
   a right-zero band has no ascent, so an ACC-restricted construct is by
   construction absent from the class callers actually hit.
3. **A measure parameter adds no capability**, and the construct is a composition
   promoted to a primitive. A caller who can compute a decreasing measure over
   their own state can compute a stop predicate over that same state — which is
   the `Computed` pattern above, written with kinds that already exist.
   `Signal` was retired for exactly this shape.

What the proposal genuinely offered was diagnosis, which is retained above as a
`SHOULD` on exhaustion reporting.

### Conformance for this section

Three fixtures are specified; **they are not yet written.**

| fixture | asserts |
|---|---|
| `feedback_drain_bound_reports_exhaustion` | A divergent loop — `c` a source cell, `m` a `Computed` of `c + 1`, an effect merging `get(m)` into `c` under `KeepLatest` — **terminates the flush** and surfaces the exhaustion outcome. Asserts no iteration count, which is not contract. |
| `feedback_converges_below_the_bound` | The discriminating negative. The same shape with `m = min(get(c) + 1, 3)` under `Max` reaches its fixed point and **must not** report exhaustion. A binding that reports exhaustion for every feedback loop passes the first and fails this. |
| `feedback_declining_to_write_terminates` | Pins the caller-side exit: an effect that stops merging ends the cascade as ordinary convergence, **not** an exhaustion report. |

Deliberately absent: the bound's value, the exhaustion outcome's representation,
and any assertion about how many times a given effect ran.

**Unfixtured and unverified, stated explicitly.** Until these exist, treat
cross-binding agreement on this whole section as unverified — the eager-computed
semantics sat in exactly this state for months while a binding shipped a
different construction under a green checkmark. Separately unmeasured: whether
any binding's async drain observes cancellation between iterations. And the
`MUST` above is currently satisfied by **no** surveyed binding; it describes
required behavior, not observed behavior.

A **`MergePolicy`** is an associative fold `⊕ : T × T → T`. The properties it
satisfies are *selected by the transport contract*, not fixed
(`relaycell-backpressure-analysis.md` §2):

| Property | Requirement | Purpose |
|----------|-------------|---------|
| **Associativity** | **Always** — the irreducible law | Regrouping a run of merged ops never changes the converged state, which is what licenses *variable flush points*: a bounded relay may flush at any post-merge watermark and converge identically. Not a flag; a law every policy MUST satisfy. |
| **Commutativity** | Per policy (`const COMMUTATIVE`) | The *reordering tax* — required only when ops may be applied out of order (concurrent producers / replicas / pages). |
| **Idempotency** | Per policy (`const IDEMPOTENT`) | The *durability tax* — required only for at-least-once / crash-replay. For an idempotent `⊕`, re-applying an op is a no-op, which is exactly the `==` store-guard one layer up: **free dedup**. |

**Policies are open. A binding MUST permit application-defined policies.** The
list below is canonical, not exhaustive: a `MergePolicy` is *any* associative
fold with honestly declared flags, and a binding that ships a closed enum of
policies has implemented a subset rather than the algebra. Merge semantics are
domain knowledge — a text register, a set of tags, a running quantile, a
per-tenant precedence rule — and the family cannot enumerate them in advance. A
binding **MUST** expose the policy interface publicly, and **SHOULD** accept a
custom policy anywhere a canonical one is accepted.

**With one obligation attached, and it is the whole cost of the openness.** An
application-defined policy **MUST** declare `COMMUTATIVE` and `IDEMPOTENT`
truthfully, and a binding **MUST** ship the law-test harness that checks a policy
against its own declarations — the same harness that verifies the canonical
policies, exposed for application use.

A policy that misdeclares its flags does not fail loudly. It converges correctly
in every single-replica test, every in-order test, and every test without
redelivery — and diverges only under the conditions the flag was supposed to
license: a claimed-commutative policy that isn't will disagree between replicas
that saw the same ops in different orders, and a claimed-idempotent one that
isn't will drift under at-least-once delivery. Both surface as replicas that
silently stop agreeing, arbitrarily far from the code that caused it. That is why
the flags are verified rather than trusted for the canonical policies, and the
reasoning does not weaken for a policy an application wrote. **Shipping the
checker is therefore part of shipping the extension point** — an unverifiable
declaration is worse than no declaration, because the relay acts on it.

The canonical policies (each names its algebraic structure and flags):

| Policy | `⊕` | Structure | Comm | Idem |
|--------|-----|-----------|:----:|:----:|
| `KeepLatest` | `old ⊕ op = op` | right-zero band | ✗ | ✓ |
| `Sum` | `old + op` | commutative monoid | ✓ | ✗ |
| `Max` | `max(old, op)` | semilattice (total order) | ✓ | ✓ |
| `SetUnion` | `old ∪ op` | grow-only semilattice | ✓ | ✓ |
| `RawFifo` | `old ++ op` | free semigroup (concat) | ✗ | ✗ |
| `CrdtJoin<C>` | `C::merge_from` | join semilattice | ✓ | ✓ |

**A replicated cell that accepts writes from more than one authority MUST use a
commutative policy.** This follows from the reordering tax above, but it is
stated separately because the default is the trap: `Cell ≡ Source<KeepLatest>`,
and `KeepLatest` is **not** commutative. A plain cell replicated to peers that
also write it will converge differently depending on arrival order — the exact
defect the algebra exists to prevent, arrived at by writing no policy at all. The
multi-writer replicated case wants `CrdtJoin<LwwRegister>` or another commutative
policy, chosen deliberately.

"More than one authority" is about *who may write*, not about topology. A
replicated derivation pushed to a peer that only reads it has one authority and
needs no commutativity — on that peer it is read-only, exposing only `get`
without the `Source` write methods, which is the read-only replicated cell
shape. Commutativity becomes mandatory the moment the receiving peer may also write.

**Derived default with user override.** A recurring shape worth naming, because
it looks like it needs a new primitive and does not. Where a value has a computed
default that a user may override:

- **Co-located** — use the graph, not a policy. A `Source` holding the override
  (absent = defer), a `Computed` holding the derivation, and a `Computed`
  selecting `override ?? derived`. Glitch-free, self-documenting, and "reset to
  default" is clearing the override cell. No arbitration exists to get wrong.
- **Distributed** — a merge policy is required, and a valid one exists: tag ops
  with provenance and fold by precedence (user outranks derived, LWW within the
  user rank). It satisfies all three properties — associative because a higher
  rank absorbs a lower one regardless of grouping, commutative because rank
  comparison is order-free and ties resolve by timestamp, idempotent because
  re-applying an op of equal rank and stamp is a no-op.

  **The hazard is reset-to-default, and it is not obvious.** Clearing an override
  is an op that *lowers* precedence, and a naive "a clear beats the user rank"
  rule is **not commutative** — a clear arriving after a newer user edit would
  wrongly win. The clear **MUST** carry a timestamp and lose to any user op newer
  than itself, which makes it an ordinary participant in the LWW rank rather than
  a special case. A binding that special-cases the clear will pass single-replica
  tests and diverge only under reordering.

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

When `set` changes a value (post-`==`-guard):

1. The cell's dependents are marked dirty (computed cells) or scheduled (effects).
2. Dirty marks propagate transitively through computed dependents — a dirty
   `Computed` marks its own dependents, and so on. A `Computed` that recomputes to
   an equal value stops the propagation (the computed guard).
3. On the next `get` of a dirty `Computed`, it refreshes: it pulls each
   dependency (recursively refreshing/ recomputing as needed), and recomputes
   only if a dependency actually changed value.

This is a push-invalidated, pull-recomputed graph — invalidation travels
downstream eagerly (so effects fire), but the new value is computed lazily on
read (so untouched branches do no work).

**Store-without-cascade** (the write-side dual of lazy reads). When `set`
changes a value whose transitive dependent cone contains **no Effect**, the new
value is stored (step 1's dirty-marking of lazy computed dependents still happens, so
a *future* subscriber reads the current value glitch-free — late-subscribe
correctness) but **no effect flush is scheduled** — there is no active reactor to
run. A binding MAY skip the flush machinery entirely in this case. Combined with
demand-driven derivation on the read side, an **unobserved** reactive node —
pull-derived or push-populated — costs approximately its raw storage: the merge
cost law tiers the write cost by dependent kind (none → store only; lazy-only →
store + O(deps) dirty-mark, no flush; active → store + dirty + flush). A **burst**
of N value-changing writes with no interleaved active read pays the transitive
dirty-mark **once** (dirty-marking is idempotent and monotonic — an already-dirty
`Computed` is not re-walked), i.e. `N·(==/⊕)` + one dirty-propagation. See
[`relaycell-backpressure-analysis.md`](relaycell-backpressure-analysis.md) §4.0.

## Handles and identity

A handle is a `Source<T, M>` or `Computed<T>` (or `EffectHandle`) carrying a
**`SlotId`** — and here `Slot` is the storage concept, not a reactive value: a
slot is the arena position that holds a node, and it holds *any* kind
(`SourceCell`, `ComputedCell`, or `Effect`). `SlotId`, `SlotValue`, and the slab
vocabulary are accurate under this storage meaning and are **unchanged** by the
kernel rename; the reactive-value node the arena holds is a `SourceCell` or a
`ComputedCell`. The slot persists across recycling; its occupant does
not (`recycled_id_inherits_nothing`).

Slot ids are minted monotonically and recycled on dispose. A disposed handle is
inert: reads on a disposed `Computed` return its last cached value if any;
reads on a disposed `Source`, or on a `Computed` whose eager puller was
disposed, are undefined (the caller MUST NOT retain a handle past disposal).
Re-entrancy of a disposed effect is prevented by removing it from the schedule
before running cleanup. Detection of a stale handle is bounded (see *Disposal is
explicit*): a binding that recycles slot ids MAY admit a same-kind ABA read unless
its `SlotId` carries a generation tag.

## Context layers

- **Single-threaded** — the base context (mirrors lazily-rs `Context`). The
  graph is not `Send`/`Sync`; it lives on one thread/executor. **Unconditionally
  required** of every binding (it is the reactive core).
- **Thread-safe** — a lock-backed counterpart (mirrors lazily-rs
  `ThreadSafeContext`); handles are clonable and the transition function and
  state are `Send + Sync`. Effects are scheduled and flushed within the
  invalidating `send`/`batch`, preserving glitch-free pull-based ordering.
  **Required of any
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

1. The kernel's two cell kinds — nodes `SourceCell` / `ComputedCell`, handles
   `Source<T, M>` / `Computed<T>` — and the sink `Effect` are implemented; an
   **eager** `Computed` (`computed().eager()`) is the eager construct — not a
   fourth kind.
2. Every cell is guarded on `T: PartialEq`: `set` is `==`-guarded (equal value is
   a no-op) and `computed` is guarded on recompute (an equal recompute suppresses
   downstream). There is no unguarded mode.
3. Refresh is pull-based and glitch-free: a `Computed` observes consistent inputs;
   untouched branches are not recomputed.
4. Dependencies are tracked dynamically through a tracking stack (edges
   re-registered each recompute; no manual subscribe).
5. Cycles are detected and throw.
6. `batch` coalesces into one propagation + effect flush at the outermost exit.
7. Effects fire scheduled (not inline), cleanup runs before each rerun and on
   dispose, and disposal unsubscribes edges.
8. An eager `Computed` is materialized by the time the invalidating `set`/`batch`
   returns (eager push).
9. **Read on every cell, write on the source kind.** Reads (`get`) are on every
   cell — `Source` and `Computed` alike; writes (`set`/`merge`) are on
   `Source<T, M>` alone — a compile error on a `Computed`, enforced by the type
   rather than a trait (a read-only interface in Go, §4 of the design). There is
   no `subscribe` — see *Reactives have no observers*.
10. **The merge algebra (`#relaycell`).** `merge(handle, op)` folds under
    an associative `MergePolicy` and routes through the `==`-guarded `set`
    (so an idempotent policy's no-op merge fires no cascade). `Cell ≡
    Source<KeepLatest>`. Every policy is associative; the `COMMUTATIVE` and
    `IDEMPOTENT` flags match the policy's algebra (verified by law-tests); the
    converged egress state is independent of merge grouping/order for a
    commutative policy (verified by `mergecell_algebra.json`).

### Declared context capabilities

A binding **MUST** declare, per context it ships, where that context sits on two
independent axes. The declaration exists so the conformance harness can decide
**which fixtures apply**. It has no other purpose, and the constraints below are
part of the requirement rather than commentary on it.

**Axis 1 — read discipline.** Either *blocking* (reads return values) or *async*
(reads return futures/promises). Mutually exclusive per context.

**Axis 2 — concurrent access.** One of:

| Level | Meaning |
|---|---|
| `none` | Single-threaded; no concurrent access contemplated. |
| `serialized` | Concurrent callers are linearized against **per-thread or per-realm graphs**. No graph is shared. |
| `shared-graph` | **One** reactive graph is genuinely accessed from multiple threads. |

The three-way split on axis 2 is not pedantry — it was added because a two-way
`thread-safe: yes/no` flag would have been satisfied by four bindings offering
materially different guarantees. Measured 2026-07-19: `lazily-rs` and `lazily-py`
share one graph across OS threads; `lazily-js` shares an `Atomics`-backed lock
across worker realms while each realm keeps **its own** graph; `lazily-dart` is a
single-isolate reentrancy guard with no cross-isolate anything. Every one of those
is individually honest and documented, but a fixture asserting concurrent-access
behavior is meaningful only at `shared-graph` and vacuous at `serialized`. A flag
that cannot tell them apart produces exactly the failure this chapter exists to
prevent: a suite that passes while testing nothing.

**The axes are independent.** Read discipline does not imply a concurrency level
and vice versa. Single-threaded async is fully concurrent while requiring no
thread-safety at all, and a blocking context may be `shared-graph`. A binding
**MUST NOT** infer one axis from the other.

**The declaration is not wire-visible.** Context capability **MUST NOT** appear in
any protocol message, influence sync behavior, or be observable by a peer. The
reactive graph is *compute, not protocol*; only resolved values cross IPC/FFI, and
convergence is a property of the merge algebra rather than of any replica's local
execution model. Associativity already licenses variable flush points, so local
scheduling is unconstrained by the protocol — which is precisely why the execution
model producing that scheduling is irrelevant to a peer. A replica running an
async context and one running a `shared-graph` context converge because `⊕` says
so, not because they agree about threads.

This constraint is stated because the failure mode is quiet. Nobody sets out to
leak the execution model into the protocol; it happens when a sync path needs a
decision and a capability declaration is conveniently in scope. The declaration
answers exactly one question — which fixtures run — and the moment it answers a
second, the layering is broken.

### Thread-safe context conformance

The lock-backed context ([Context layers](#context-layers)) is **required of any
binding whose platform exposes preemptive multi-threading or shared-memory
concurrency**. A binding's thread-safe context conforms when it holds these
deterministic properties under concurrent access:

1. Handles are **clonable**, and the transition function and source/computed node
   state are `Send + Sync`; one reactive graph is shared across OS threads.

   This clause applies **only to a context declaring `shared-graph`** (see
   *Declared context capabilities*). A `serialized` context — `lazily-js`, whose
   graph is per-realm, or `lazily-dart`, whose guard is single-isolate — cannot
   satisfy it and is not required to. Conformance for those is the linearization
   property alone: concurrent callers are ordered, and none observes a
   half-updated graph. Requiring a shared graph of every "thread-safe" context
   would have made two bindings permanently non-conforming for having chosen a
   design their platform actually permits.
2. **Effects run glitch-free under concurrent access**, preserving the same
   ordering as the single-threaded context — a concurrent reader never observes a
   half-updated graph. This mandates **glitch-free ordering** (every effect that
   runs sees the fully settled cone, never an intermediate state), **not** literal
   in-lock dispatch. A threaded binding **MAY** defer effect dispatch out of the
   graph lock, so a callback may re-enter the context, provided the ordering
   invariant holds: effects are delivered in dependency order and none observes a
   mixed state.

   *(This clause previously governed observer callbacks, under
   `#lzspecobserverclarify`. Observers were removed from the family — see
   *Reactives have no observers* — and the requirement now attaches to effects,
   which are the only remaining way user code runs inside an invalidation wave.)*
3. The `==` (PartialEq) source guard and the `Computed` equality guard both hold under
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

**Measured 2026-07-19.** Shipping a type named `AsyncContext` or
`ThreadSafeContext` is not the same as implementing the capability, so this
records what was found by reading each implementation rather than by counting
type names:

| Binding | `async` | `thread_safe` | Note |
|---|---|---|---|
| `lazily-rs` | full | `shared-graph` | reference; the only binding replaying the reactive-graph corpus |
| `lazily-py` | full | `shared-graph` | `AsyncContext` added 2026-07-19 (`d115000`); it was the last binding without one |
| `lazily-dart` | full | `serialized` | single-isolate reentrancy guard; isolates share no memory |
| `lazily-js` | full | `serialized` | `Atomics`/`SharedArrayBuffer` mutex shared across worker realms, **graph is per-realm** |
| `lazily-go` | full | *unmeasured* | |
| `lazily-kt` | *unmeasured* | *unmeasured* | |
| `lazily-zig` | full | *unmeasured* | cascade rides the publish path rather than the invalidate path |
| `lazily-cpp` | **stub** | *unmeasured* | see below |

`lazily-cpp`'s async context is a **stub and MUST NOT be counted as implementing
the capability**: `AsyncSlotNode` carries no `dependents` or `dependencies`
fields, `get_async` unconditionally recomputes on every call, and the
synchronous `get()` returns a cached value that nothing ever invalidates. Depth
tests "pass" through `get_async` only because nothing is ever memoized. Per the
rule above it should declare `async: none` until it has a dependency graph, or
implement one.

The `unmeasured` entries are deliberately not guesses. Absence of a finding is
not a finding — that lesson is recorded in *Reactives have no observers*, where
three bindings' omission from a divergence table turned out to mean nobody had
looked.
