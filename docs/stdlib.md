# Portable standard-library primitives

This document specifies the language-neutral `Timer`, `Timeout<T>`, and
`RevisionBarrier` convenience APIs. Bindings may expose idiomatic names and
types, but an implementation earns the corresponding coverage feature only by
replaying the canonical fixtures against its public production API.

The three versioned features are:

- `stdlib_timer_v1`
- `stdlib_timeout_v1`
- `stdlib_revision_barrier_v1`

All time in this contract is monotone logical time. Production implementations
normally read a platform monotone clock; conformance runners inject a clock and
wait driver and must never sleep or depend on wall-clock scheduling.

## Shared rules

- Logical instants and durations are unsigned 64-bit integers.
- `start + duration` is checked. Overflow returns typed `Unavailable` and never
  wraps.
- A clock observation lower than the most recently accepted observation returns
  `Unavailable(clock_regression)` without changing the stored state.
- A deadline is inclusive: `now >= deadline` reaches the deadline.
- The first terminal result is latched. Later reads return the same result and
  invoke no caller-supplied adapters.
- The adapter owns no executor, async runtime, or thread. Waiting is driven by a
  caller-owned clock/wait seam.

## `Timer`

Starting a timer at `start` for `duration` produces a pending timer whose
deadline is `start + duration`. A zero duration therefore fires on the first
observation at `start`.

`observe(now)` has two non-error observations:

- `Pending(deadline)` when `now < deadline`;
- `Fired(fired_at)` when `now >= deadline`.

The first firing latches its actual observation instant as `fired_at`; later
observations preserve that value. A timer cannot return to pending.

## `Timeout<T>`

`Timeout<T>` is a caller-driven adapter around an operation probe and a
cancellation probe. It is not a future executor and it is not the reactive
[`TimeoutCell`](resilience.md#timeoutcell--deadline-bounded-call).
`TimeoutCell` emits a reactive timeout edge; this adapter resolves a single
operation to one of:

- `Completed(T)`
- `TimedOut`
- `Cancelled`
- `Unavailable(reason)`

Each nonterminal `poll(now, operation, cancellation)` uses this precedence:

1. Reject a regressed clock without polling either adapter.
2. If `now >= deadline`, return `TimedOut` without polling either adapter.
3. Sample the operation and cancellation adapters once each.
4. A completed operation wins, including when cancellation is observed in the
   same poll.
5. An unavailable operation returns `Unavailable(operation_unavailable)`.
6. Cancellation returns `Cancelled`; an unavailable cancellation adapter
   returns `Unavailable(cancellation_unavailable)`.
7. Otherwise remain pending.

This order makes exact-deadline behavior and simultaneous
completion/cancellation deterministic in every binding.

## `RevisionBarrier`

A revision barrier waits for both:

1. `current_revision >= required_revision`; and
2. a caller-supplied derived predicate to be true.

Revisions never decrease. Registration increments a wake generation, then the
waiter re-reads the revision and predicate after registration. This
register-then-recheck rule closes the check-to-sleep race: an advance that lands
between the initial check and waiter registration is observed immediately.

A waiter may have an inclusive deadline and a cancellation adapter. Deadline
dominance is checked before cancellation. Its terminal outcomes are
`Satisfied(revision)`, `TimedOut`, `Cancelled`, `Disposed`, and
`Unavailable(reason)`. Disposal wakes all waiters and latches.

Effect receipts and transport acknowledgements are application-owned
observations. Recording a receipt cannot advance a barrier revision, change its
wake generation, or satisfy a waiter.

## Canonical fixtures and mutation gates

The canonical corpus is under `conformance/stdlib/` and validates against
`schemas/stdlib-fixture.schema.json`. Each family declares a scenario and
assertion floor. A runner that opens zero fixtures, executes fewer than the
declared floor, or merely echoes fixture expectations fails conformance.

The spec test runner also applies named mutations. At minimum it proves that the
corpus detects:

- changing `>=` to `>` at a deadline;
- checking cancellation before pre-deadline completion;
- failing to latch a terminal result;
- omitting the barrier's post-registration recheck;
- treating an effect receipt as barrier authority; and
- replacing production transitions with fixture bookkeeping.

Bindings may advertise a feature to the peer suite only after their public API
passes the matching canonical family and its mutation checks. Unsupported
bindings stay visible as staged and receive no pass credit.
