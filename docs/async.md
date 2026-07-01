# Async Reactive Context

An **async context** is a separate reactive surface for computations whose
values are produced by `async`/future-returning functions. It is **not** an
overload of the synchronous or thread-safe context; it is a distinct graph with
its own handles, because futures introduce in-flight state, cancellation, stale
completion, and dependency tracking across suspension points that the
synchronous graph does not have.

This chapter fixes the cross-language contract. An async context is **compute,
not protocol** — only resolved slot values cross IPC/FFI as ordinary cell
payloads, exactly like the synchronous graph.

## Why a separate surface

A synchronous reactive context tracks dependencies through a thread-local stack
touched on every read, and a slot's value is either present or unset. An async
computation can be *in-flight* (suspended at an `.await`) when its inputs
change, can complete after those inputs are gone, and can be canceled mid-flight.
Those states require:

- an explicit per-slot **state machine** (not just present/absent),
- **revision tracking** so a stale completion is discarded,
- dependency edges registered **before** the read is awaited, and
- a **cancellation contract** that is safe under waiter drop, supersession, and
  context disposal.

A binding gates this surface behind a separate feature flag so downstream users
do not accidentally accept the larger semantic surface.

## Handles

An async context exposes its own copyable, id-only handles, distinct from the
synchronous handles:

| Handle | Wraps |
|--------|-------|
| `AsyncCellHandle<T>` | A mutable input cell (the synchronous input layer) |
| `AsyncSlotHandle<T>` | A computed/memoized async slot |
| `AsyncEffectHandle` | An async effect |

Handles are id-only and copyable; they are usable only with the owning async
context.

## API surface

| Method | Description |
|--------|-------------|
| `cell(value)` | Create a mutable cell (value type equality-comparable, cloneable, `Send + Sync`) |
| `get_cell(handle)` | Read a cell value (synchronous) |
| `set_cell(handle, value)` | Update a cell and invalidate dependents |
| `computed_async(compute)` | Create an async computed slot |
| `get(handle) -> Option<T>` | Synchronous cached read; `Some(T)` if resolved, `None` otherwise (warm-path fast path) |
| `get_async(handle) -> T` | Await a slot value; uses `get()` for resolved slots, otherwise spawns async compute |
| `memo_async(compute)` | Like `computed_async` with an equality memo guard |
| `effect_async(effect)` | Create an async effect with an async cleanup |
| `dispose_async_effect(handle)` | Dispose an async effect and await its cleanup |
| `batch(run)` | Synchronous batch boundary; schedules async reruns at batch exit |

Cells are the **synchronous input layer**: `cell`, `get_cell`, and `set_cell`
are synchronous. Only computed slots, memos, and effects are async.

## Async slot state machine

Each async slot tracks its state through a finite state machine:

```
            first get_async /         future Ok,          dependency
   Empty ──────────────────► Computing ──────► Resolved ──────► Computing
     ▲         (spawn)        │    │                              │
     │                         │    │ future Err                   │
     │                         │    ▼                              │
     │                         │  Error ──────────────────────────┘
     │                         │   retry get_async
     │                         ▼
     │      dependency invalidation      revision mismatch on
     └──── during in-flight compute ──► (stale) Computing ──► complete discards;
      hard clear                                                new future spawned
```

| State | Meaning |
|-------|---------|
| `Empty` | No cached value, no in-flight computation. Entered on creation and after a hard clear. |
| `Computing` | A handle tracks the in-flight future for the current **revision**. Concurrent `get_async` callers attach as waiters to the same in-flight result instead of spawning duplicate futures. |
| `Resolved` | The cached value is fresh, until dependency invalidation transitions back to `Computing`. |
| `Error` | The last computation failed; callers receive the error or retry on the next `get_async`. |

**Revision tracking** is load-bearing: a computation records the slot revision
at start; at publish time the graph accepts the value **only if the revision is
still current**. This is what makes stale completion safe.

Transitions:

- `Empty → Computing` — first `get_async` or invalidation with no cached value.
- `Computing → Resolved` — future completes `Ok` and the recorded revision still
  matches.
- `Computing → Error` — future completes `Err` and the recorded revision still
  matches.
- `Computing → Computing (stale)` — invalidation advances the slot revision
  during an in-flight computation. The completing future finds its revision no
  longer matches and discards the result; a new future is spawned for the
  updated revision.
- `Resolved → Computing` — invalidation marks the cached value stale and spawns
  a new computation.
- `Error → Computing` — `get_async` retry after an error.

## Cancellation contract

A conforming async context MUST honor all five of:

1. **Waiter cancellation is safe.** Dropping one `get_async` future does **not**
   cancel the shared in-flight computation while other waiters still need it.
   Each waiter holds a shared handle; dropping a receiver does not abort the
   in-flight task.
2. **Stale completion is discarded, not published.** When invalidation advances
   the slot revision during an in-flight computation, the completing future finds
   its recorded revision no longer matches and discards the result. Waiting
   callers are retried against the new revision or attached to the newly spawned
   future.
3. **Explicit cancellation.** A hard clear, invalidation, or context disposal
   may mark the in-flight revision as canceled; if an abort handle is available,
   the task is aborted. User futures MUST be cancellation-safe, because aborting
   drops them at an `.await` boundary.
4. **Context disposal.** Dropping the async context cancels all in-flight
   computations via their abort handles and awaits completion of all active
   cleanup futures before returning.
5. **Effect cleanup before next body.** An effect's cleanup future MUST complete
   before the next effect body starts. Disposal removes pending reruns before
   awaiting cleanup.

## `get_async` re-resolve contract

`get_async` MUST treat the slot state as authoritative and **re-resolve** rather
than assert, because the slot can change between its lock acquisitions and a
notifier can close under it. It runs an outer loop that, each pass, re-reads the
slot via the `get()` fast path and then re-locks to attach to or spawn a
computation. Two concurrency windows are benign (not data inconsistencies — the
published value is always correct):

1. **Resolved-since-`get()`:** the slot can transition `Computing → Resolved`
   between the fast-path `get()` (which releases the lock) and the re-lock.
   Observing `Resolved` at the re-lock is expected; the cached value is read
   directly. It is **not** an unreachable state.
2. **Notifier dropped:** the per-computation waiters can all close without a
   final `Resolved` signal when an in-flight compute is superseded by a newer
   revision (the stale `Computing → Computing` transition early-returns) or the
   slot is invalidated. A "the world changed" error means re-resolve from
   current slot state — return the now-published value, attach to the new
   in-flight compute, or respawn. It MUST NOT panic.

## Dependency tracking

Async compute and effect callbacks do **not** use a thread-local tracking stack
(a thread-local does not survive executor thread migration or suspension/resume
across `.await`). Instead each callback receives a **compute context**:

| Method | Tracking |
|--------|----------|
| `get_async(slot)` | Records the accessed slot as a dependency **before** awaiting its value |
| `get_cell(cell)` | Records the accessed cell as a dependency synchronously |

Edges register immediately, so source invalidation while the future is suspended
can cancel or supersede the in-flight computation before it publishes stale data.
On rerun, stale dependencies are removed and new ones registered; the dependency
set is carried by the compute context, not a thread-local.

## Async effects

An async effect runs an effect body returning an optional async cleanup:

- **Serialized reruns:** reruns are serialized per effect — a rerun does not
  start until the previous cleanup future completes.
- **Cleanup ordering:** the previous run's cleanup completes before the next
  body starts; disposal awaits the current cleanup before removing the node.
- **Auto-tracking:** the body receives a compute context and tracks dependencies
  through `get_async` / `get_cell`.
- **Scheduled, not inline:** dependency invalidation schedules an async rerun
  after the current invalidation pass; the rerun runs on the runtime executor,
  not inline within `send`/`batch`.
- **Disposal:** removes pending scheduled reruns, awaits the current cleanup
  future, and unsubscribes dependency edges.

## Batch support

`batch(run)` is a **synchronous** boundary. Cell updates queue invalidation
roots; at batch exit, queued roots trigger propagation. Async slots and effects
are *scheduled* for rerun but do not execute inside the batch callback — async
reruns execute after the batch returns, on the runtime executor. Mutation
semantics stay synchronous at the graph boundary: invalidations schedule async
reruns only after the outermost batch exits.

## In-flight deduplication & fast path

- **One in-flight computation per revision:** each async slot has one published
  cache and at most one in-flight computation for the current revision.
  Concurrent `get_async` callers await the same in-flight result instead of
  spawning duplicate futures.
- **Synchronous fast path:** `get()` returns the cached value synchronously when
  the slot is `Resolved`, avoiding async overhead. `get_async()` calls `get()`
  first; only unresolved or dirty slots enter the async spawn path.

## Async state machine

A flat [State Machine](state-machine.md) over the async context keeps `send` and
`state` synchronous (cells are the synchronous input layer) while reactive
observers use the async APIs: `on_transition` returns an async effect handle and
`state_is` returns an async signal handle. Because resolution is asynchronous,
eager recomputation settles on the runtime rather than synchronously within
`send`.

## Conformance

An async context conforms when:

1. The slot state machine (`Empty`/`Computing`/`Resolved`/`Error`) and its
   transitions, including the stale `Computing → Computing` discard, are
   implemented exactly.
2. Revision tracking discards every stale completion; a stale value is never
   published.
3. All five cancellation properties hold, and disposal awaits cleanup.
4. `get_async` re-resolves through both benign-race windows without panicking.
5. Dependencies are tracked through the compute context (not a thread-local) and
   registered before the awaited read.
6. Async effect reruns are serialized, cleanup-before-body ordered, and
   executor-scheduled rather than inline.
7. Batching is synchronous at the mutation boundary; async reruns fire only after
   the outermost batch exits.

## Implementation status

The async surface is **optional**. A binding MAY omit it entirely (the
synchronous and thread-safe graphs do not require it). A binding that ships it
MUST honor the full cancellation and re-resolve contract above. lazily-rs
implements it behind an `async` feature flag. Concurrency-window coverage is
pinned by targeted deterministic tests rather than exhaustive interleaving
exploration, because the async resolve loop runs on a real async executor whose
primitives a synchronization-model checker cannot shim.
