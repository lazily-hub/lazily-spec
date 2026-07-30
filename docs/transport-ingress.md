# Transport-agnostic reactive ingress (`#designimplementtransport`)

Status: **specified, implemented, and projected into all nine bindings** (Rust,
Python, Kotlin, JS, Dart, Zig, Go, C++, C#), each in all three execution flavors.
The corpus in `conformance/ingress/` is replayed by every binding against every
flavor it ships; the three `coverage.json` ingress rows are green across the
board.

## The problem this replaces

A client that consumes a remote stream usually grows the same four accidental
mechanisms, one per subsystem:

1. an imperative `refresh()` / `poll()` loop that re-reads whether the connection
   is healthy;
2. a hand-rolled "is this message still relevant?" check, usually a timestamp
   comparison that a reconnect quietly breaks;
3. a reconnect path that forgets which messages were already applied, so it
   either double-applies or silently skips;
4. transport-shaped consumer code — the WebSocket path and the polling path each
   grow their own copy of 1–3, and they disagree.

Every one of those is a *derive* being simulated with a call. The ingress family
makes them derives, and makes the transport a value the primitive never touches.

## Vocabulary

| Term | Meaning |
|------|---------|
| **scope** | A keyed, lifecycle-bearing admission plane. Scopes are independent: closing one never touches another. |
| **envelope** | One decoded inbound message plus its provenance: `key`, `generation`, `sequence`, `stamped_at`, `payload`. |
| **generation** | Producer incarnation. Monotone per scope. A higher generation *fences* every lower one. |
| **sequence** | Position within a generation, from 0. |
| **stamped_at** | Producer logical time. Freshness is measured against it, never against arrival time. |
| **window** | The scope's coalesced hot head: the merge (`⊕`) of delivered-but-undrained payloads. |
| **watermark** | `delivered_through` — the highest in-order sequence delivered in the current generation. |
| **receipt** | A durable record of one admission decision, on one of three channels. |

## Phase 1 — the specified contract

### Keyed lifecycle-scoped event sources

Each scope is in exactly one lifecycle position:

```
Opening ──deliver──▶ Live ──suspend──▶ Suspended ──reconnect──▶ Live│Opening
   │                   │                   │
   └────────────── close ──────────────────┴──────────────▶ Closed ──open──▶ Opening
```

- **Opening** — open, nothing delivered.
- **Live** — delivering.
- **Suspended** — disconnected but *retained*: window, watermark, and generation
  survive, which is what makes replay possible instead of a full resync.
- **Closed** — terminal until reopened. Admits nothing, claims no authority.

Reopening a **suspended** scope preserves the watermark. Reopening a **closed**
scope resets it: a closed scope's producer is gone, and its sequence space is not
resumable.

### The admission order is normative

An envelope is tested in this order, and the order is part of the contract:

1. **lifecycle** — a closed scope drops (`ScopeClosed`).
2. **generation fence** — `generation < scope.generation` drops
   (`StaleGeneration`).
3. **freshness** — `now - stamped_at > freshness_horizon` drops (`Expired`).
4. **generation handoff** — `generation > scope.generation` resets the sequence
   space, the reorder buffer, *and the window* (see below), then continues.
5. **dedupe** — `sequence < expected` drops (`DuplicateSequence`); a sequence
   already in the reorder buffer drops (`DuplicateBuffered`).
6. **ordering** — `sequence > expected` buffers, or drops
   (`ReorderWindowOverflow`) when the buffer is at `reorder_window`.
7. **backpressure** — at `high_water`, the overflow policy applies.
8. **merge** — the payload folds into the window under `⊕`, then every buffered
   successor the delivery unblocked flushes in sequence order.

Two orderings matter especially:

- **The fence outranks dedupe.** A zombie producer replaying old sequences under
  an old generation must be distinguishable from a legitimate retry. Testing the
  sequence first would report `DuplicateSequence` and hide the zombie.
- **Freshness outranks ordering.** An expired envelope must never occupy a
  reorder slot, or a slow zombie can exhaust the buffer and starve live data.

### Generation handoff is a baseline reset, not a continuation

A handoff discards the old incarnation's buffered successors **and its undrained
window**. The new incarnation's first envelope is authoritative; folding a
superseded delta into a fresh baseline is exactly the build-skew corruption the
fence exists to prevent. This is also why `reconnect` at a higher generation
behaves identically — one rule, two entry points.

### Envelope provenance vs. transport

`IngressTransportKind` is `EventChannel | RpcTriggered | BoundedPolling`. It
influences **one** derived value, the schedule:

```
schedule(kind, interval) =
  { kind, poll_interval: kind == BoundedPolling ? max(1, interval) : none }
```

A poll interval exists only where event delivery is unavailable, and never zero —
"we polled a transport that pushes" and "we polled in a tight loop" are both
unrepresentable rather than merely discouraged. Nothing else in the primitive
consults the transport; a WebSocket frame, an RPC response, and a polled page are
the same input once decoded.

### Receipt sources — three channels, not one log

| Channel | Carries | Consumer |
|---------|---------|----------|
| `Accepted` | `{ delivered_through, conflated }` | projections, watermark tracking |
| `Dropped` | an `IngressDropReason` | operator dashboards, drop-rate alarms |
| `Error` | an `IngressError` | supervisors, retry policy |

They are three *separate reader kinds* because they have three separate consumers.
A dropped envelope must not invalidate a projection that only reads accepts.

Receipts are bounded by `receipt_capacity` (oldest evicted first) and carry a
**monotone offset that survives eviction**, so a consumer can tell "I have seen
everything" from "the log wrapped".

## Phases 2–3 — the reference implementation

### Core / shell split

```
IngressCore<K, T, M>          ← admission algebra. No context, no handles,
                                 nothing awaited, no interior mutability.
   ├── IngressCell            ← single-threaded shell (Rc/RefCell)
   ├── ThreadSafeIngressCell  ← Send + Sync shell (Arc/Mutex, batch())
   └── AsyncIngressCell       ← AsyncContext shell (Arc/Mutex, clear_slots)
```

This is the same split `TopicCore` makes for the broadcast family and
`KeyedOrder` makes for the map family, for the same reason: **invalidation is a
graph write**, so the core must not perform it. Every core mutator returns an
`IngressChange` — the set of reader kinds the transition dirtied — and each shell
clears exactly that set on its own graph.

**Admission is not async-coloured.** Whether an envelope is admissible is a
function of the fence, the watermark, the reorder buffer, and the observed clock —
state the graph does not own and nothing has to await. The async flavor therefore
uses a synchronous compute on the async graph and returns plain values, exactly
like the other two. Awaiting belongs to the transport, and the transport is
outside the primitive by construction.

### Four reader kinds per scope

| Reader | Type | Invalidated by |
|--------|------|----------------|
| `value` | `Option<T>` | delivery, drain, handoff, close |
| `readiness` | `IngressReadiness` | lifecycle change, first delivery, a freshness-horizon *crossing* |
| `authority` | `Option<IngressAuthority>` | delivery, handoff, open, close |
| `retry` | `Option<IngressRetry>` | error, delivery, reconnect, close |

Collapsing these into one reader would make an error deepen a backoff *and*
re-render a value that did not change. The negative cases are the contract:

- a **buffered** out-of-order envelope invalidates **nothing** and mints **no
  receipt** — nothing a reader can observe moved;
- a `tick` **inside** the freshness horizon invalidates **nothing**, which is what
  keeps a polling shell from re-rendering on every tick;
- an **empty drain** invalidates nothing;
- a **suspend** invalidates readiness only.

Conversely, one admission that dirties several kinds clears them in **one frontier
walk**, so no reader observes `new value, old authority` — the partial fan-out a
generation handoff must never expose.

### The derives

```
readiness =
  Closed    → Closed
  Suspended → Suspended
  Opening   → Warming
  Live      → watermark is none        → Warming
               now - stamped_at ≤ H    → Ready
               otherwise               → Stale

authority = Closed → none
            else   → { generation, delivered_through, stamped_at }

resume_from = watermark + 1, or 0

retry     = consecutive_errors == 0 → none
            else { attempt, backoff = min(ceiling, base·2^(attempt-1)), resume_from }
```

A scope that has never delivered is `Warming`, not `Stale`: there is no stamp to
be old.

### Replay, not resync

`suspend` returns a `ReplayRequest { generation, from_sequence = resume_from }`;
so does `reconnect`. `pump` asks the transport to replay whenever the algebra
reports a surviving gap, and `IngressTransport::request_replay` returns whether
the transport *could* carry the request — a bounded-polling transport has no
addressable history and answers `false`, which makes "this gap will never close"
observable rather than silent.

A **drain is an egress, not an ack**: it never moves the watermark, so a replay
after a drain resumes from the same sequence.

### Backpressure reuses the relay algebra

`IngressPolicy.overflow` is `relay::Overflow`, and construction validates it
against `M::CONFLATES` exactly as `RelayCell::new` does — `Conflate` bounds
nothing for a non-conflating `⊕`. At `high_water`:

| Overflow | Behaviour | Loss |
|----------|-----------|------|
| `Block` | refuse, outcome `Blocked`, window intact, watermark unmoved | none — the producer retries after a drain |
| `DropNewest` | refuse, window intact | the incoming op |
| `DropOldest` | window restarts at the incoming op | the accumulated window |
| `Conflate` | keep merging — the coalescence *is* the bound | none for converged state |
| `Spill` | degrades to `Conflate` until a durable tail is wired | none for converged state |

`Block` refuses *without* advancing the watermark, which is what makes the
producer's retry in-order rather than a duplicate.

## Phase 4 — conformance schedules

`conformance/ingress/` carries the cross-language corpus. One fixture per named
schedule:

| Fixture | Pins |
|---------|------|
| `ingress_ordered_delivery.json` | in-order delivery, conflation, drain, receipt channel isolation, negative invalidation on empty drain |
| `ingress_reorder_and_duplication.json` | buffer→flush in sequence order, both duplicate classes, reorder-window overflow, buffered envelopes invalidate nothing |
| `ingress_disconnect_replay.json` | suspend retains window+watermark, replay request, reconnect clears the error streak |
| `ingress_backpressure.json` | `Block` refuses losslessly and the retry is in-order |
| `ingress_generation_handoff.json` | build skew: stale fenced before dedupe, newer generation resets the baseline |
| `ingress_freshness_and_retry.json` | expired arrival never takes a reorder slot, horizon crossing is readiness-only, backoff doubles and clamps |

The **flavor axis lives in the runner, not the corpus**: fixtures carry a `model`
naming the primitive and no execution-model field, and one `IngressModel` trait
replays the same JSON against each shell. `invalidates` is asserted through a
cache-validity probe on each reader kind, in **both** directions — a fixture step
that expects `false` fails if the shell invalidated anyway, which is how
over-invalidation stays visible.

### What the nine-binding projection settled

Projecting the corpus into every binding turned three things that read like
implementation detail into contract:

**`invalidates` is a claim about observability, not about a mechanism.** Three
different probes satisfy it, because three graphs expose different things: a
cache-validity read (`is_set` / `isCacheValid`), a recompute counter, and a
version-source delta. All three are bidirectional and all three kill the same
mutations. What is *not* acceptable is asserting receipt **counts** in place of
per-channel invalidation — a stale cache recomputes to the right count, so a
count-only gate reports green. Bindings that assert counts before invalidation
also report the wrong *thing*: the count mismatch is the symptom, the uncleared
channel is the defect.

**"One frontier walk" must be stated as "no torn observation", not as an effect-run
count.** Effect-run counts are not portable: at least one kernel legitimately
re-runs an effect when it lazily refreshes a second dirty dependency during its
own run, so "two runs for one admission" is true there with no ingress defect
present, and a gate phrased that way passes either way. What a second walk
actually costs is a reader observing `new value, old authority` — a post-handoff
value under the superseded generation's fence. That is the invariant; the run
count is one binding's proxy for it.

**Admission is not async-coloured; *reads* may be.** Nothing in the algebra
awaits — the decision is a function of the fence, the watermark, the reorder
buffer, and the observed clock, so every mutator is synchronous in all nine
bindings and no runner has a `settle` step. But a binding whose async graph offers
no synchronous compute constructor will project the four scope derives as
`Task`/`Promise`/pending-queue reads. That is a property of the graph, not of the
primitive, and it does not weaken the row: the requirement is that **admission**
is synchronous and that one admission is one walk.

## Formal model

`lazily-formal/LazilyFormal/Ingress.lean` pins:

- `fence_monotone` — a scope's generation never decreases.
- `watermark_monotone` — the watermark never decreases within a generation.
- `buffered_is_invisible` — a `Buffered` outcome changes neither window nor
  watermark.
- `stale_generation_rejected` / `duplicate_rejected` — the two refusal classes.
- `handoff_resets_baseline` — a handoff's window is the new envelope alone.
- **`reorder_needs_no_commutativity`** — the interesting one. `Relay.reorder_adjacent`
  needs `Commutative` to tolerate reordering, because a relay merges ops in
  arrival order. Ingress does not: the reorder buffer replays in *sequence* order,
  so a merely associative `⊕` converges to the in-order fold under
  reordering. The buffer buys what the algebra would otherwise have to pay for.
