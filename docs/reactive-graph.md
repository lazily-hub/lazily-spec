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
| `dispose_slot(handle)` / `dispose_cell(handle)` | Tear down a derived slot or source cell: detach edges in both directions, clear the node, recycle its id |
| `scope()` | Open a **teardown scope**: nodes created through it are disposed together when the scope ends |
| `scope.disarm()` | Disarm a scope — ending it disposes nothing; its nodes revert to context ownership |
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
  **SHOULD** expose disposal for slots and cells, not only for effects, or a
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

  A scope carries the **same hazard** as `dispose_slot`: ending it tears down its
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

### Observer semantics (`Cell.subscribe`) (`#lzdartobservercow`)

`Cell.subscribe(callback)` registers an **observer**: a callback invoked on each
`set_cell` that passes the `==` guard, returning a **disposer** that removes it.
This is a different mechanism from the dependency edges above — observers are
registered by hand, are not discovered by the tracking stack, and are not part of
the glitch-free pull. Everything the tracking stack decides for itself, a caller
decides here, which is why the contract has to be written down.

It was not, until now. Four bindings each answered these questions
independently while repairing observer-list defects, and shipped **different**
answers; the same caller code observes different behavior on different bindings
today. The clauses below are the family position. Where a binding contradicts
one, it is named — see *Known divergences* at the end of this section.

- **Firing order is registration order.** A notification **MUST** invoke
  observers in the order they were registered. This is the only order a caller
  can predict without reading an implementation, and the alternative is not
  "some other order" but a *different* order per notification: a hash- or
  set-backed observer collection reorders on rehash, and `lazily-go`'s map
  iteration is randomized by the runtime deliberately, so its observers fired in
  a fresh order every publish. A binding **MUST NOT** rely on that
  unpredictability as licence to leave the order free — callers write observers
  with side effects (a log line, a queue push, a paint) whose composition is
  order-dependent whether or not the contract admits it.

  Order is a property of the *registration sequence*, not of the callback: an
  observer removed and re-registered goes to the back.

- **Every registration is independent — no deduplication.** Subscribing the same
  callback twice **MUST** produce two registrations. Both are invoked on each
  notification, in registration order, and each disposer removes exactly one of
  them; after disposing one, the other still fires. A binding **MUST NOT**
  deduplicate observers by callback identity or by callback equality.

  Deduplication is not portable and is not safe. It is inexpressible where
  callbacks are neither hashable nor comparable, which is most bindings' natural
  closure type. Worse, it silently couples unrelated callers: two components that
  happen to subscribe the same bound method share one registration, so the first
  to unsubscribe cancels the second's subscription. Identity-keyed collections
  make this the *default* behavior rather than a bug a binding chose, which is
  why the clause is a `MUST NOT` on the mechanism and not only on the effect.

- **Subscribing during a notification is deferred.** An observer registered from
  inside a callback **MUST NOT** be invoked by the notification in flight; it
  first runs on the next one. Every binding already holds, or emulates, a
  snapshot of the observer list taken before the first callback, and this clause
  only writes that down.

  The deferral is load-bearing rather than incidental: without it a self-feeding
  observer — one that subscribes on every notification — extends the loop it is
  running in and never terminates. Bounding the pass by the count captured before
  the first callback is sufficient; a binding is **NOT** required to copy the
  list.

- **Unsubscribing during a notification takes effect immediately.** An observer
  disposed from inside a callback **MUST NOT** be invoked by the notification in
  flight, *including when the loop has not yet reached it*. Observers the loop
  has already visited are unaffected — they ran before the disposal, which is not
  retroactive.

  This is the clause the family actually disagreed on, and it is settled against
  the majority. A stable pre-notification snapshot — dart's and go's choice — is
  the simpler implementation and invokes a disposed observer one final time in
  that pass. Under a tracing collector that extra call is harmless: the closure
  is still alive because the snapshot references it. It is **not** harmless
  anywhere else. In a manually-managed binding `unsubscribe` is routinely the
  step immediately before freeing the state the callback reads, so "one more
  call after you asked to stop" is a use-after-free with a specification behind
  it. A contract that is safe in five bindings and unsound in three is the wrong
  family default, so the GC'd bindings migrate rather than `lazily-zig`,
  `lazily-cpp`, and `lazily-rs` adopting a rule they cannot honour.

  This does not mandate a mechanism. A binding **MAY** tombstone the entry and
  skip it (`lazily-zig`), consult a live-set before each call, or re-check the
  registration before invoking — the contract fixes *which observers run*, never
  how removal is represented. A binding **MUST NOT** implement removal in a way
  that relocates an unvisited observer behind the notify cursor: a swap-remove
  under a live iteration silently drops whichever entry it moved, which is the
  defect this section was written from.

- **Disposers are idempotent and single-shot.** A disposer **MUST** latch: the
  first call removes its registration, and every later call is a no-op. It
  **MUST NOT** remove any other registration — in particular not one created
  after it, and not one whose callback is equal or identical to its own.

  Latching is not a defensive nicety. Where removal is keyed by the callback
  rather than by the registration, an unlatched disposer called a second time
  removes whatever now matches that key, which is a *later* subscription of an
  equal callable belonging to a caller that never asked to be unsubscribed —
  found in `lazily-py` (`b2de504`) as exactly that. A disposer that is latched
  cannot express the bug regardless of how the collection is keyed, so bindings
  **SHOULD** latch in the disposer rather than relying on the collection.

  Disposing an observer and disposing the cell are independent: tearing down the
  cell **MUST** drop its observers without invoking them, and a disposer called
  after its cell is gone is a no-op, not an error.

**Known divergences (migration status).** Each row is a binding bug against this
section, not a tolerated variation.

> **This table was found to be incomplete on 2026-07-19, and the way it failed is
> worth recording.** It listed two violated clauses for `lazily-py`. There were
> three: py also invoked observers disposed mid-notification — the same defect
> this table documents against `lazily-dart` and `lazily-go`, in this table, in
> the revision that added it. It went unrecorded because a py test asserted the
> behavior as intended and the `subscribe` docstring described it as a deliberate
> "snapshot dispatch" design, so it did not read as a bug to anyone reviewing py
> in isolation.
>
> It was found by *executing* the fixtures, not by reading. A hand-maintained
> audit of where implementations diverge from a spec is itself an implementation
> of that spec, and it drifts the same way. **Do not extend this table by
> inspection.** Add a row only when a conformance run produces it, and treat the
> table as a record of runner output rather than as a source of truth.

| Binding | Clause | Status | Detail |
|---|---|---|---|
| `lazily-py` | firing order | **migrated** `b2bc6bd` | Was a `set`, so order was neither registration order nor stable. Now a dict keyed by a monotonic per-cell registration token; CPython insertion order is registration order. |
| `lazily-py` | duplicate registration | **migrated** `b2bc6bd` | Was deduplicated by **equality**. Now keyed by token, so two subscribes are two entries and each disposer pops its own. Tokens are never rewound, so a spent disposer cannot name a later registration. |
| `lazily-py` | unsubscribe during notify | **migrated** `b2bc6bd` | **Was missing from this table.** `touch` iterated a stable `tuple(subs)` snapshot, so an observer disposed mid-pass was invoked once more. Now snapshots *tokens* to bound the pass but re-reads each callback from the live table before invoking. |
| `lazily-dart` | unsubscribe during notify | **migrated** `16a0b93` | Was a stable pre-notification snapshot (`95acb1d`). The slot representation already tombstoned in place; the snapshot was discarding the liveness bit by flattening to bare callbacks. Now snapshots slots and re-reads liveness before each call. |
| `lazily-go` | unsubscribe during notify | **migrated** `c654cf6` | Same defect (`8781f2b`), same fix. Steady-state notify remains 0 allocs/op. |
| `lazily-zig` | firing order | **migrated** `da7610c` | Was a swap-remove, so removing any observer relocated the tail over it — not registration order, and not even *stable*, since each removal reshuffled differently. Tombstone-then-compact is now the only removal mechanism, so survivors keep order and no live entry is relocated past the notify cursor. |
| `lazily-zig` | duplicate registration | **migrated** `da7610c` | Was deduplicated by callback **address**. `subscribe` now returns a `Subscription` token (per-cell monotonic id, never reused; `0` is the tombstone sentinel) and `unsubscribe` takes it. Breaking API change, approved 2026-07-19. |

`lazily-dart` and `lazily-go` already conformed on ordering, and both pin it with
tests. `lazily-zig` already conformed on both notify-reentrancy clauses
(`9d72b14`), which is why it was the one binding not migrating on the clause the
family disagreed about.

**Unverified bindings.** `lazily-cpp`, `lazily-js`, and `lazily-kt` have never
been run against the `observer_*` fixtures. Their absence from the table above is
**not evidence of conformance** — it is absence of measurement. Given how that
table failed for `lazily-py`, treat all three as unknown until a runner reports.

**Fixtures.** The normative cases are
`conformance/reactive-graph/observer_*.json`. As of 2026-07-19 these are executed
by `lazily-py`, `lazily-dart`, `lazily-go`, and `lazily-zig` via runners that
load this repository directly rather than from a bundled copy.

A note for whoever writes the next runner, learned by writing four: where a
fixture shares one `callback` label across two registrations, the runner **must**
hand both the *same* callable — the same function pointer, the same object. Give
each its own and a binding that deduplicates by address or by equality passes the
duplicate-registration fixture vacuously, which is precisely the bug that fixture
exists to catch. The corollary is that a shared callable cannot report which
registration invoked it, so every runner resolves labels to registration ids
afterwards, in registration order, against the registrations live at the start of
the pass.

Two ops are **not** uniformly expressible, and every runner so far has had to
model rather than measure them:

- The `dispose` op and its `readable` expectation assume a Cell teardown API.
  `lazily-dart`, `lazily-go`, and `lazily-zig` have none — a Cell's lifetime ends
  at unreachability, and in a manually-managed binding a token cannot legally
  probe freed memory. All three assert the observable contract instead (nothing
  fires, the disposer afterwards is a latched no-op) and track `readable` in
  harness bookkeeping. Either those bindings gain explicit disposal or the
  expectation becomes binding-conditional. **Unresolved.**
- `scope_teardown_equals_fold_of_disposals.json` has no `steps` key at all; it is
  `scenarios`-shaped, so every runner must special-case it. Whether that is
  intentional or a fixture defect is **unresolved**.

The eight disposal and teardown fixtures in this directory remain unexecuted by
every binding. They are not a quick follow-up: they require `TeardownScope`
(`ctx.scope()` / `disarm()`) plus dependency-graph introspection
(`dependents_of`, `dependencies_of`, `cleanup_order`) that at least `lazily-py`
does not currently expose.

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
