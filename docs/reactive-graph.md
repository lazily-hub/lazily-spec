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
| **Effect** | A side-effecting computation that reruns whenever a tracked dependency invalidates. An optional cleanup closure runs before each rerun and on dispose. |

The three core primitives are **`Cell`** / **`Slot`** / **`Effect`** (with
`MergeCell` the merge-generalized source, `Cell ≡ MergeCell<KeepLatest>`).

**`Signal` is a derived construct, not a core primitive.** It is
`Signal ≡ Slot.eager` — a memo Slot plus a puller Effect that reads the slot on
creation and after every invalidation, so its value is materialized by the time
the invalidating `setCell`/`batch` returns (readers never see an intermediate
unset state — `relaycell-backpressure-analysis.md` §4.0). It composes the core
primitives; bindings expose it as a convenience (`signal(compute)`), not as a
distinct kind of node.

Values are **lazy by default**; reach for the derived `Signal` when eager push
semantics are required. Handles (`SlotHandle` / `CellHandle` / `SignalHandle` /
`MergeCellHandle` / `EffectHandle`) are lightweight, copyable ids over a shared
node table — they are usable only with the owning context.

**The read/write type split.** Every primitive above is a **`Reactive<T>`** — the
read supertype exposing `get` (auto-subscribing), nothing more. Note it does
**not** expose `subscribe`: observation is a declared dependency edge, never a
registered callback — see *Reactives have no observers*.
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
| `effect(run)` | Register a side-effecting computation; `run` may return a cleanup closure |
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

### Reactives have no observers (`#lzdartobservercow`)

**No reactive exposes an observer API.** Not `Cell`, not `Slot`, not `Signal`,
not `MergeCell`. No `subscribe`, no `on_write`, no `on_change`, no
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
| Memo guard | respects it — no run on an equal recompute | not subject to it |
| Merge `⊕` | sees converged state — the only guaranteed value | sees a flush-timing artifact (below) |
| Glitch-free | yes — inputs are mutually consistent | no — fires mid-update by construction |
| Dependencies | dynamic; re-discovered every run | none; bound to one node forever |
| Teardown | disposed with its scope | manual, and outlives its scope |
| Per-node cost when unused | zero | storage on every node |

**Coalescence is the row that matters most, and it is not one mechanism but
five.** This family coalesces at every layer: the `==` store-guard drops an equal
write entirely; the memo guard drops an equal recompute so downstream never
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
new op annihilates the previous state — and **`Cell ≡ MergeCell<KeepLatest>`**,
so every plain cell in the family is already an LWW instance. Under a timestamped
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
ctx.effect(|ctx| cb(ctx.get_cell(&cell)))
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
dropped by the memo guard, a flush skipped because the cone held no effect. So
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

The reactive-graph fixtures that remain cover disposal and teardown scopes. They
are unexecuted by every binding as of this writing, requiring `TeardownScope`
(`ctx.scope()` / `disarm()`) and dependency-graph introspection (`dependents_of`,
`dependencies_of`, `cleanup_order`) that at least `lazily-py` does not expose.
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
