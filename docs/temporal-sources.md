# Temporal source primitives (`#lztime`)

Phase 1 of the realtime + distributed primitives plan
(`agent-loop/tasks/software/plan-lazily-realtime-distributed-primitives.md`).
The temporal sources are the foundation everything time-shaped (leases,
expirations, retries, windows, presence heartbeats) sits on.

## Logical-clock discipline

Time is modeled by a **logical clock**: a monotone `now: u64` tick, exactly the
discipline already used by `relay_policy` (`tick`/`advance`). A binding drives
the sources from its own runtime timer (`tokio::time`, `async-std`, a manual
game loop) by calling `tick(now)` with a non-decreasing `now`. Nothing here
reads a wall clock, so every source is deterministic and portable.

A source is a **`TimelineSource`**: a pure compute core with

- `tick(&mut self, now) -> bool` — advance to logical time `now`; returns `true`
  on a **fire edge** (a fire happened on this tick), `false` otherwise.
- `next_fire(&self) -> Option<u64>` — the logical time of the next fire, or
  `None` when the source is exhausted / never fires again.

The pure core is split from the reactive glue (backend-portability rule): the
core is a side-effect-free state machine over plain integers, and the reactive
cell projects the core's edges onto a `Cell` so dependents invalidate **only on
an actual fire**. Payload class: **`BytesPayload`** (`TimerCell` / `IntervalCell`
/ `CronCell` state is `u64`/`bool`); `DeadlineCell<T>` is **`PyObjectPayload`**
(it carries an opaque user value alongside a bytes-eligible deadline core).

## `TimerCell` — single-shot

State: `fire_at: u64`, `fired: bool`. `value` is `None → Some(())`, flipping to
`Some(())` at the first tick with `now ≥ fire_at`.

- **Fire once.** Once `fired`, it stays fired; further ticks return `false` and
  never change `value` (idempotent fire).
- **Edge-only invalidation.** The `value`/`fired` reader invalidates only on the
  fire edge; a tick that does not fire (before `fire_at`, or any tick after the
  fire) leaves dependents cached.
- `next_fire()` is `Some(fire_at)` before the fire, `None` after.

## `IntervalCell` — periodic

State: `period: u64` (≥ 1), `next: u64` (next boundary, starts at `period`),
`count: u64` (fires so far). `count` is the observable.

- **Every `period` ticks.** A fire boundary lands at `period, 2·period, …`. On
  `tick(now)`, every boundary in `(previous frontier, now]` fires; `count`
  increases by the number of boundaries crossed. A `now` that jumps past several
  boundaries counts them all (`fires_this_tick = 0` when `now < next`, else
  `(now − next)/period + 1`).
- **Monotone count.** `count` never decreases; the reader invalidates only when
  `count` changes.
- `next_fire()` is always `Some(next)`.

## `CronCell` — pattern-periodic

A cron expression is, structurally, a periodic pattern with a **match set**: an
`IntervalCell` whose fire points are the ticks matching the pattern. We model it
directly as `cycle: u64` + `offsets: [u64]` (each `< cycle`, sorted/deduped):
a tick `m ≥ 1` fires iff `m mod cycle ∈ offsets`. (`cycle = 60, offsets = [0, 30]`
is "at second 0 and 30 of every minute".)

- State: `cycle`, `offsets`, `cursor: u64` (last `now` processed, starts `0`),
  `count`. On `tick(now)`, `count` grows by the number of matching ticks in
  `(cursor, now]`, then `cursor = now`.
- The match count is computed arithmetically (no range scan), so a large `now`
  jump is O(offsets): for offset `o`, matches in `1..=n` is
  `n/cycle` if `o == 0`, else `(n−o)/cycle + 1` if `o ≤ n` else `0`.
- **Monotone count.** Same reactive contract as `IntervalCell`.
- `next_fire()` is the smallest `m > cursor` with `m mod cycle ∈ offsets`.

## `DeadlineCell<T>` — value + deadline

Composite over a `TimerCore` and a `Cell<T>`. State is `Deadlined<T>`, either
`Live(T)` or `Expired(T)`; it flips `Live → Expired` at the first tick with
`now ≥ deadline`, **preserving the value**.

- **Expiry is monotone** and preserves the payload (`Expired(v)` carries the
  same `v` that was `Live(v)`); the reader invalidates only on the expiry edge.
- Used to build every deadline-driven primitive downstream: lease expiry
  (`#lzcoord`), ephemeral expiry (`#lzpresence`), RPC timeouts (`#lzresilience`).

## Conformance

`conformance/temporal/` replays each source under a logical clock:

| Fixture | Model | Checks |
|---------|-------|--------|
| `timer_single_shot.json` | `TimerCell` | pre-fire no edge; fire edge at `fire_at`; idempotent post-fire (no edge, `value` stable) |
| `interval_periodic.json` | `IntervalCell` | count per boundary; a jump crossing two boundaries counts both; monotone count |
| `cron_pattern.json` | `CronCell` | fires at ticks matching `mod cycle ∈ offsets`; count monotone across a jump |
| `deadline_expiry.json` | `DeadlineCell` | pre-deadline `Live`; expiry edge flips to `Expired` preserving value; idempotent post-expiry |

Each step is `{ "op": { "type": "tick", "now": N }, "returns": <edge:bool>,
"expected": { <projected readers>, "invalidates": { <reader>: bool } } }`.

## Formal model

`lazily-formal/LazilyFormal/Temporal.lean` proves the load-bearing invariants:
timer fires at most once and stays fired (`timer_stays_fired`,
`timer_fire_idempotent`), interval/cron `count` is monotone under `tick`
(`interval_count_monotone`, `cron_count_monotone`), a below-frontier tick is a
no-op (`interval_no_fire_before_next`), and deadline expiry is monotone and
value-preserving (`deadline_expired_monotone`, `deadline_preserves_value`).
