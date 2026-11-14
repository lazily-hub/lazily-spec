# Transport-agnostic reactive egress (`#lzegress`)

Egress is the send-side mirror of
[reactive ingress](transport-ingress.md). The pure `EgressCore<T>` owns delivery
authority:

- monotone sequence assignment;
- the pending queue and bounded unacknowledged window;
- the monotone cumulative acknowledgement watermark;
- retry attempts, bounded exponential backoff, and exhaustion; and
- the producer-generation fence.

The graph shells expose that state as Computeds. Transport I/O lives in exactly
one Effect per attachment:

```text
EgressCore<T>                 sequence, window, watermark, retry, fence
├── EgressCell<T>             Context shell
├── ThreadSafeEgressCell<T>   ThreadSafeContext shell
└── AsyncEgressCell<T>        AsyncContext shell
          │
          └── one attached Effect ──send──▶ transport
```

An Effect is not an egress family by itself: it has no retained delivery state.
The Effect observes the `pending` and `inflight` projections, asks the core to
claim eligible envelopes, and sends those envelopes. The core decides whether a
claim, acknowledgement, failure, retry, or reconnect is admissible.

This is reactive projection, not a request/ACK protocol. Enqueue invalidates
`pending`; claiming moves an envelope to `inflight`; an acknowledgement
invalidates `inflight` and re-runs the same attachment when it reopens a bounded
send window. The acknowledgement is domain delivery input to the core, not an
acknowledgement of a projection request.

## Envelope identity and ordering

Each enqueue assigns the next sequence in the current sequence space:

```text
enqueue(payload) =
  pending.push({ generation, sequence: next_sequence, attempt: 0, payload })
  next_sequence += 1
```

`(generation, sequence)` is the transport idempotency identity. Pending records
are claimed oldest-sequence first. A successful claim increments `attempt` and
moves the record into the unacknowledged window. A claim is refused when that
window reaches `inflight_limit`.

An acknowledgement is cumulative. `ack(generation, through)` advances
`acked_through` only when `through` is greater than the current watermark, and
removes all pending, in-flight, or retry-parked records at or below it.

An acknowledgement may only cover sequences the core has assigned. An
`ack(generation, through)` with `through >= next_sequence` acknowledges data
that was never enqueued, so never sent: it is a peer protocol error. The core
refuses it with `BeyondSent { next_sequence }` (`"ack": "beyond_sent"` in the
corpus), changes no state, and invalidates no reader. Accepting it would lift
the watermark over a sequence not yet assigned; the next enqueue would then
retain a record at or below the watermark, and the receiver's genuine ACK for
that record would return `Unchanged`, stranding it. The refusal keeps the
watermark-integrity invariant unconditional: `acked_through < next_sequence`
whenever it is set, and every retained record lies strictly above it.

| Operation | Outcomes (`returns` spelling) |
|---|---|
| `enqueue(payload)` | `{ "sequence": n }` |
| `claim(generation)` | `claimed` + envelope, `empty`, `window_full`, `stale_generation` + `current` |
| `ack(generation, through)` | `advanced` + `through`, `unchanged` + `through`, `beyond_sent` + `next_sequence`, `stale_generation` + `current` |
| `fail(generation, sequence)` | `retrying` + retry, `exhausted` + retry, `unknown_sequence`, `stale_generation` + `current` |
| `retry_now(generation, sequence)` | `scheduled` + `sequence`, `unknown_sequence`, `stale_generation` + `current` |
| `reconnect(generation)` | `advanced` + `generation` + `replayed`, `unchanged` + `generation`, `stale_generation` + `current` |

`ack` checks the generation fence first, then the sequence boundary, then the
watermark: a stale attachment's beyond-boundary ACK reports `stale_generation`.

## Send-side generation fence

Every transport Effect captures the generation current when it attaches. Every
send-side transition supplies that generation to the core. A mismatched
generation is rejected without changing state or invalidating a reader.

`reconnect(new_generation)` must strictly advance the generation. It:

1. fences the old Effect;
2. preserves `next_sequence` and `acked_through`;
3. moves every unacknowledged in-flight or retry-parked record back to pending
   in sequence order; and
4. rewrites all pending envelopes to the new generation.

The old Effect remains attached but inert. The replacement transport receives
one new Effect, which replays the retained pending projection under the new
incarnation.

Step 4 changes the `pending` projection whenever any record is retained, not
only when an in-flight or parked record is replayed: a never-claimed pending
envelope still carries the old generation until it is rewritten. A legitimate
reconnect therefore invalidates `pending` whenever `replayed > 0` or the pending
queue is non-empty. `replayed` counts only the in-flight and retry-parked
records moved back to pending.

## Retry

`retry_budget` counts retries after the first send attempt. A failed in-flight
record is parked until the derived backoff elapses:

```text
backoff(attempt) =
  min(retry_ceiling, retry_base * 2^(attempt - 1))
```

While budget remains, `retry_now` returns the parked record to pending in
sequence order. Once exhausted, the record is terminal and cannot be scheduled
again. Parking is explicit so a failed send cannot cause the attachment Effect
to spin in an immediate reactive retry loop.

## Reader kinds and invalidation

| Reader | Type | Invalidated by |
|---|---|---|
| `pending` | `Vec<EgressEnvelope<T>>` | enqueue, claim, retry scheduling, reconnect retaining any record (replay or generation rewrite), cumulative ACK pruning |
| `inflight` | `Vec<EgressEnvelope<T>>` | claim, failure, replay, cumulative ACK pruning |
| `acked_through` | `Option<u64>` | advancing ACK only |
| `retry` | `Option<EgressRetry>` | failure, retry claim/scheduling, replay, ACK pruning |

No-op, stale-generation, and refused (`beyond_sent`) transitions invalidate
nothing. The async shell uses
synchronous Computeds for the delivery state; only the transport attachment is
async-coloured.

## Composition boundaries

Egress does not duplicate existing storage or flow-control primitives:

- use `RelayCell` / `Outbox` ahead of enqueue for conflation and backpressure;
- use [`LatestDurableProjectionCore`](durable-sinks.md#latest-durable-projection-core-lzlatestdurableprojection)
  when only the latest keyed projection must reach a durable sink with
  single-flight claims, monotone epochs, and stale-actor fencing;
- use `SpillStore` for overflow-to-storage;
- use `DurableOutbox` for durable recovery; and
- use transport framing outside the core.

Those adapters feed or persist the egress state machine. They do not move
sequence assignment, acknowledgement authority, or the generation fence into an
Effect.

## Conformance and formal obligations

The canonical corpus in `conformance/egress/` covers ordered cumulative ACK,
the beyond-boundary ACK refusal, window reopening, bounded retry, reconnect
fencing, and the pending invalidation of a reconnect that replays nothing. Binding runners must
assert both returned outcomes and the full projected state after every step.

The Lean model proves:

- sequence assignment is monotone;
- acknowledgement progress is monotone;
- an ACK at or beyond `next_sequence` is refused without changing state or
  invalidating a reader, so the watermark-integrity invariant (watermark inside
  the assigned sequence space, every retained record above it) holds for every
  operation;
- stale-generation send-side transitions preserve state;
- reconnect strictly advances generation while preserving the ACK watermark;
- every reader whose projection a step changes is reported invalidated
  (including `pending` on a reconnect that only rewrites generations); and
- permitted retry attempts are bounded by the configured budget.
