# Durable Effect Sinks (`#lzdurablesink`)

Lazily fixes **one direction of authority** between live reactive state and
durable storage:

```text
cold durable state ──hydrate once──▶ live Lazily state
                                      │
                                      ▼
                          computed projection or ordered fact stream
                                      │
                                      ▼
                              Effect / AsyncEffect
                                      │
                                      ▼
                             write-only durable sink
                                      │
                                ack / failure
                                      └────────▶ live Lazily state
```

> **Invariant.** While a Lazily runtime is live, transitions are decided from
> Lazily state. Durable storage receives a projection or an ordered fact as an
> *effect*. A sink MUST NOT reload storage and use it to arbitrate the transition
> it is currently persisting.

This makes durable storage an **effect sink**. It does not claim that every effect
is durable, nor that durable storage is always eventually consistent. Lazily is
not a database framework: applications continue to own serialization,
transactions, schema migration, storage selection, and startup recovery. Lazily
ships no SQLite, filesystem, or cloud-store adapter as part of this decision —
the sink is an application-owned trait (see examples below).

## Authority rule

- Live coordination, compare-and-swap, ownership, deduplication, leases, and
  transition selection happen in Lazily state.
- Durable I/O runs from an `Effect` / `AsyncEffect`, or from a
  `TopicCell` / `DurableOutbox` drain when history must be lossless.
- A runtime sink is **write-only with respect to transition authority**. Loading
  and migration belong to a separate **startup hydrator** that runs once before
  the runtime is live, not on the decision seam.
- `Computed` values and transition reducers stay **pure** — a reducer MUST NOT
  perform I/O or read storage to decide a transition.
- Success advances a **monotone acknowledgement** such as `durable_through(epoch)`.
- Failure stays represented in **live state** as `pending` / `retrying` /
  `backpressured`. It MUST NOT trigger a database reload at the decision seam.
- Values on the existing [`Ephemeral`](presence.md) plane MUST NOT enter a durable
  sink. Reuse the existing `Durable` marker — do not invent a second marker
  hierarchy. (The `Ephemeral`-never-`Durable` separation is already pinned by
  `Presence.ephemeral_never_durable`.)

## Projection vs history — pick the shape before the API

Ordinary `Effect` / `AsyncEffect` observe **settled** reactive state. Lazily
already coalesces effect reruns across a batch, so a batch containing
`A → B → C` may persist only `C`. That is correct for a durable **projection**
(current/recoverable state). Durable **history** has a different contract: every
accepted fact must survive and remain ordered. It uses the existing
[`TopicCell`](cell-model.md#topiccell-broadcast) / [`DurableOutbox`](protocol.md#durableoutbox-durable-outbox)
family — stable cursor, replay, idempotency key, and monotone acknowledgement —
not ordinary effects. Do **not** modify ordinary effects to retain intermediate
values; that would weaken their coalescing semantics and duplicate the
ordered-stream primitives.

Before choosing an API, answer two questions:

1. Is this sink persisting the **latest projection** or an **ordered history**?
2. Must the transition be **durable before it is externally visible**?

Those two answers fix the shape:

| Need | Lazily source | Sink contract |
| --- | --- | --- |
| Latest recoverable state | `Computed` read by `Effect` / `AsyncEffect` | Idempotent upsert of the latest epoch |
| Every accepted fact | `TopicCell` or existing `DurableOutbox` | Append / replay / ack with a stable cursor |
| Durable before visible | Ordered fact + application acknowledgement cell | Visibility waits for monotone `durable_through` |
| Ephemeral state | `Presence` / `Ephemeral` primitives | Persistence rejected |

## Application-owned sink trait

The sink is a narrow, write-only trait owned by the application. The reactive
graph holds no reference to a query/hydration interface — those live in a
separate module used only by the startup hydrator, never passed into the runtime
effect. (Phase 3 adds architecture tests that fail if a hot-path actor module
imports the persistence query/CAS or file-lock modules.)

The two examples below sketch the trait shape in Rust-flavoured pseudocode. The
store API is deliberately minimal — `upsert_latest` for a projection,
`append_fact` for history — and always carries the epoch so success can advance a
monotone `durable_through`.

## Example 1 — coalesced current-state projection

A `Computed` projects the actor's current state. An `Effect` reads it and
upserts only the settled value; intermediate batch values are coalesced away by
Lazily's existing effect-batch dedup, so the sink sees one write per batch.
Acknowledgement advances `durable_through`; a sink failure flips the live actor
to `retrying` without reloading storage.

```rust
// Application-owned, write-only. No read/CAS surface reaches the runtime effect.
trait ProjectionSink {
    fn upsert_latest(&mut self, epoch: u64, state: &ActorState) -> Result<(), SinkErr>;
}

// Live state. Pure reducer; no I/O.
let live_state: Source<ActorState> = ctx.source(initial);
let epoch:     Source<u64>         = ctx.source(0);
let projected: Computed<ActorState> = ctx.computed(|c| c.get(live_state).clone());

// Durable I/O runs from an Effect — never reads storage to decide a transition.
ctx.effect(|c| {
    let s = c.get(projected);
    let e = c.get(epoch);
    match sink.upsert_latest(e, s) {
        Ok(())  => c.set(durable_through, e),            // monotone ack
        Err(_)  => c.set(status, Status::Retrying),      // failure stays live
    }
});
```

## Example 2 — lossless ordered fact sink

Every accepted fact must survive and stay ordered, so the source is a
`TopicCell` (or the existing `DurableOutbox`), drained by an effect into the
application store. Replay from a stable cursor covers every epoch after the
durable frontier; duplicate delivery is idempotent by the `event_id` key. This is
the [`DurableOutbox`](protocol.md#durableoutbox-durable-outbox) append-before-send
/ replay-from-cursor / `ack_through` contract, applied as a sink.

```rust
trait HistorySink {
    fn append_fact(&mut self, epoch: u64, fact: &Fact) -> Result<(), SinkErr>;
    fn ack_through(&mut self, epoch: u64);
}

let facts: TopicCell<Fact> = ctx.topic();
// Drain: every unacked fact is appended in order; ack advances the cursor.
ctx.effect(|c| {
    while let Some(fact) = facts.read_after(cursor) {
        sink.append_fact(fact.epoch, &fact)?;
        sink.ack_through(fact.epoch);          // cursor advances; GC-safe below it
        cursor = fact.epoch;
    }
});
```

## Visibility policy (caller-chosen)

A caller picks an explicit policy per transition; Lazily mandates none:

- **`eventual_projection`** — live state is immediately authoritative; the sink
  persists in the background and may lag.
- **`durable_before_applied`** — external visibility waits for the
  `durable_through(epoch)` acknowledgement before the transition is observed as
  applied (an ordered fact plus an application acknowledgement cell).
- **`ephemeral`** — no durable sink; the value lives on the `Ephemeral` plane.

## Cold restart

Restart recovery is the **hydrator's** job, run once at startup before the
runtime is live: load the last acknowledged projection (or replay the ordered
fact log up to the durable cursor) into live state, then resume. After
hydration, authority is live-only — a sink failure during a live transition never
rolls authority backward by rehydrating storage at the decision seam.

## Formal backstop

`lazily-formal/LazilyFormal/DurableSink.lean` pins the load-bearing invariants:
`durable_through` is monotone; a batched projection persists only the settled
epoch (coalescing); an ordered history replays every epoch past the durable
cursor; and a sink failure leaves live authority unchanged (no rehydrate-at-
decision-seam). The `Ephemeral`-never-`Durable` separation is already proven in
`Presence.ephemeral_never_durable`.
