# Deterministic-replay safety (`#lzreplay`)

Some hosts re-execute your code and require the *second* run to issue exactly
the same side effects, in exactly the same order, as the first: Temporal.io
workflow replay, event-sourced aggregates rebuilt from a log, lockstep netcode,
and deterministic simulation all work this way. This page states which parts of
lazily are safe to run inside such a host.

The short version: **the pure cores are replay-safe; the reactive layer is
not** — and that is by design, not a defect.

## What the family guarantees, precisely

[reactive-graph.md](reactive-graph.md) already pins two ordering properties,
and deliberately leaves a third free:

1. **Effects run glitch-free, in dependency order.** Every effect that runs
   sees the fully settled cone, never an intermediate state. A dependent is
   never delivered before what it reads.
2. **Scope cleanups run in reverse creation order**, and a binding **MUST**
   implement it so that *every binding runs cleanups in the same sequence*.
   This one is cross-binding deterministic.
3. **Sibling order is free.** For two effects at the same depth with no
   dependency between them, nothing fixes which runs first: "Order is
   therefore free for the edge bookkeeping and fixed for the cleanups."

Clause 3 is the whole subject of this page. Convergence does not need it — the
graph is confluent, so every node settles to the same value whatever order its
independent siblings were visited in — and pinning it would over-constrain the
edge bookkeeping for no gain in every non-replay host. But a replay host
compares the *sequence of emitted commands*, not the final values, so clause 3
is exactly the guarantee it needs and does not get.

### Do not rely on a binding's incidental stability

Bindings differ in whether sibling order happens to be stable, and none of it
is contractual:

| Binding | Dependent fan-out | Sibling order in practice |
|---|---|---|
| lazily-rs | `EdgeVec = SmallVec<[SlotId; 2]>` plus an `EdgeIndex` for O(1) dedup | insertion-ordered |
| lazily-js | `Set`, which preserves insertion order per ECMAScript | insertion-ordered |
| lazily-py | `Cell._parents: set[Slot]`, keyed by **object identity** | **varies between processes** — `set` order follows `id()`, i.e. memory addresses |

lazily-py is conformant: clause 3 permits this, and its `TeardownScope._owned`
is an ordered `list` iterated in reverse, so clause 2 holds. But code written
against lazily-rs or lazily-js can pick up a dependence on insertion order that
silently breaks when ported to lazily-py — and under a replay host it breaks as
an intermittent failure on a *different process*, which is the worst shape a
bug can take.

## The replay-safe subset

Safe: every **pure core**. These are side-effect-free state machines over plain
integers and ids, with no I/O, no randomness, no threads, no global mutation,
and no dependence on iteration order. They are driven by an explicit monotone
`tick(now: u64)` supplied by the caller, so they read no clock of their own.

- `#lztime` — `TimerCore`, `IntervalCore`, `CronCore`, `DeadlineCore`
- `#lzcoord` — `LeaseCore` and the lock / semaphore / barrier cores
- `#lzpresence` — `EphemeralCore`
- `#lzresilience` — `TimeoutCore`, `CircuitBreakerCore`, `RetryPolicyCore`, `BulkheadCore`
- `#lzwindow`, `#lzrateshape` — the window and rate-shaping cores
- `#lazilystatetable`, state machines and statecharts

Not safe for command ordering: `Context`, `Cell`/`Source`, `Computed`, `Slot`,
`Effect`, and anything built on them. Their *values* are replay-stable; the
*order their effects fire* is not.

The split is not a new boundary. It is the same core/cell split the family
already mandates for backend portability — the pure core carries the semantics,
the reactive cell carries the glue. It turns out to also be the
deterministic-replay boundary.

## Using the cores under a replay host

Import the cores and drive them from the host's replay-stable clock; keep the
reactive layer out of the replayed region entirely. Two practical notes:

- **Cores and cells share a module.** `temporal.py` and `resilience.py` define
  `TimerCore` next to `TimerCell`, and import the reactive module at module
  scope, so you cannot import a core without loading the reactive layer. That
  is harmless — merely importing it does nothing — but it means "safe subset"
  has to be a curated set of names, not an import boundary.
- **Prefer the host's own durable timers.** A replay host that offers durable
  sleeps, retries, and timeouts (Temporal's `workflow.sleep`, retry policies,
  `start_to_close_timeout`) already solves what `#lztime` and `#lzresilience`
  solve, and its versions survive process death, which the in-memory cores
  cannot. Reach for a lazily core when you need behaviour the host does not
  provide — cron-pattern match counting, rate shaping, windowing, a statechart
  — not to re-implement the host's timers.

## If the guarantee should be stronger

Making sibling order contractual would mean specifying insertion-ordered
fan-out across all bindings, changing lazily-py's `_parents` from a `set` to an
insertion-ordered container, and adding a conformance fixture that asserts the
sequence rather than the settled values. That is a real change with a real cost
and is **not** proposed here; clause 3 is currently deliberate. A
cross-process ordering test would be the thing that decides it, since a
single-process test cannot distinguish a stable order from a lucky one.
