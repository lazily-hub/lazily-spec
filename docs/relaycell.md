# RelayCell — Algebra-Backed Backpressure

`RelayCell` is the **algebra-typed conflating relay**: a stream transform that
sits on an edge, adapts a fast ingress to a bounded/slow egress by an
**algebra-typed merge**, a **reactive backpressure policy**, and an optional
**paged durable spill**. This chapter is the normative surface of the phased plan
in [`relaycell-backpressure-analysis.md`](relaycell-backpressure-analysis.md); the
[merge algebra](reactive-graph.md#the-merge-algebra-and-sourcecellt-m-relaycell)
(Phase 1) is its foundation and the
[`lazily-formal`](https://github.com/lazily-hub/lazily-formal) Lean model
(`LazilyFormal.Merge`, `LazilyFormal.Relay`) is the executable reference for the
invariants below.

> **Status.** Phases 1–8 are complete across all eight bindings. The
> **lazily-rs reference implementation** and Lean pins validate the API shapes:
> Phase 1–4 (merge algebra, RelayCell core, SpillStore, Transport — `merge.rs`,
> `relay.rs`, `spill.rs`, `relay_transport.rs`), Phase 5 (Inbox/Outbox role
> facades — `relay_roles.rs`), Phase 6 (the extra
> `Rate`/`Window`/`Expiry`/`Priority`/keyed policies — `relay_policy.rs`), and
> Phase 7 (example systems as integration tests — `relay_examples.rs`). The
> Phase 6 policies are formally corollaries of the core theorems (window →
> flush-grouping, priority/sharding → reorder), and every binding exercises the
> Phase 2–6 behavior in its relay tests.

> **Invariant above all else (§9).** Policy and transport are *local mechanism*;
> the **converged egress state is independent of binding and mechanism whenever
> the merge `⊕` is associative**. Every RelayCell fixture asserts this, and the
> Lean `relay_converges` theorem pins it. Break it — a non-associative merge, or a
> non-lattice merge on a reordering transport — and portability, determinism, and
> the formal pin all fail together.

## 1. Not a new node — a composite (Phase 2)

`RelayCell<T, M>` is **not** a new Axis-1 delivery primitive and **not** a new
reactive node category. It decomposes into the [reactive family](reactive-graph.md):

- the **hot head is a `SourceCell<T, M>`** (write = `⊕` under policy `M`);
- its reactive reads (`depth` / `bytes` / `pending_keys` / `is_full` /
  `is_spilling` / `is_draining` / `lag`) are **`FormulaCell`s** — demand-driven, so an
  unobserved relay costs `N·⊕` and nothing more (the [merge cost
  law](reactive-graph.md#invalidation-propagation));
- an ingress **Effect** drives the merge from the transport.

It composes onto `QueueCell` / `TopicCell` / `WorkQueueCell` edges and
**subsumes** today's scattered backpressure logic:
`DurableOutbox.coalesce_to_snapshot` is a `RelayCell<_, CrdtJoin<Lww>>` + a
`SpillStore`; per-subscriber TopicCell conflation is a per-sub `RelayCell`;
op-log outbox fusion is a `RelayCell<_, RawFifo>` + Spill (no conflate).

```
      ingress          ┌──────────── RelayCell ─────────────┐         egress
 ───(Transport)───────►│ hot head : accumulating merge (⊕)  │───────►(Transport)──►
    ops arrive fast    │ BackpressurePolicy (watermarks)     │  drained on egress
                       │ overflow: Block|Drop|Conflate|Spill │  readiness (credit)
                       │ SpillStore (paged durable tail)     │
                       │ reactive reads: depth/bytes/keys     │
                       └─────────────────────────────────────┘
```

## 2. BackpressurePolicy — reactive limits (Phase 2)

Every limit is a **reactive cell**, so an operator or an adaptive controller
retunes it live and every dependent relay reacts:

| Field | Type | Meaning |
|-------|------|---------|
| `dimension` | `Cell<BoundDim>` | `Count` \| `Bytes` \| `Keys` \| `Age` — what the bound measures |
| `high_water` | `Cell<u64>` | gate ingress at/above this level |
| `low_water` | `Cell<u64>` | re-open ingress at/below this level |
| `overflow` | `Cell<Overflow>` | `Block` \| `DropOldest` \| `DropNewest` \| `Conflate` \| `Spill` |

**Hysteresis is required:** `high_water ≠ low_water` so a relay riding the bound
does not flap open/closed. An **adaptive controller** is an ordinary `formula`
cell that observes `depth`/`lag`/downstream latency and drives `high_water` — the
control loop is reactive policy driving reactive limits, not a config struct.

## 3. Overflow actions and policy-flag validation (Phase 2)

The **merge algebra**, not the relay, decides which overflow is *sound*. A
`RelayCell` MUST reject an `(overflow, transport)` pair the policy's flags forbid,
at construction:

| Overflow | Loss | Requires | Rejected when |
|----------|------|----------|---------------|
| `Block` | lossless | — (propagates backpressure via `is_full`) | never |
| `Conflate` | lossless *for converged state* | `⊕` associative (always) | `RawFifo` (order/multiplicity are meaning) |
| `Spill` | lossless | `⊕` idempotent **or** dedup keys (crash-replay is at-least-once) | non-idempotent `⊕` without spill dedup |
| `DropOldest`/`DropNewest` | **lossy** | caller opts into loss | a lossless policy (e.g. `Sum`, `GCounter`) declares Drop forbidden |

A relay MUST additionally reject **reordered pages / shards** for a
non-commutative policy (the reordering tax), and MUST **`log`** its overflow
action and expose `dropped` / `conflated` counters — no silent truncation.

**Merge swap** (`can_reconfigure`): `M` MAY be swapped only when the hot head is
empty (changing `⊕` mid-stream changes meaning); the relay exposes
`can_reconfigure` (true iff head empty), and re-validates overflow/transport
against the new policy's flags at swap time.

## 4. SpillStore — paged durable tail (Phase 3)

`SpillStore` generalizes [`DurableOutbox`](protocol.md): a **hot page** in RAM
(actively merged) plus **immutable cold pages** on durable store, a bounded
**manifest** (`page_id → location, watermark, bytes`), an egress **cursor**, and
**ack-before-reclaim**. Memory is `O(hot page) + O(manifest)` for any algebra.
Retrieval is pull-metered by egress credit; associativity lets a lagging consumer
receive a *conflated* catch-up. Reconstruction (cold pages in order, then hot
head) reproduces the flat fold — **paged spill loses nothing** (Lean
`spill_lossless`). Crash recovery replays the last unacked page; because a page is
one coalesced summary op at the egress, replay is a no-op for an idempotent policy
(Lean `spill_replay_idempotent`) — at-least-once delivery converges.

`SpillPolicy` (all reactive): `page_size`; `mode` = `CompactOnWrite` (keep-latest,
minimizes disk) \| `AppendCompact` (LSM-style, preserves increments for
accumulating semilattices); `retention` = `BoundedDisk` \| `UnboundedLog` \|
`Ttl`; `rehydrate` = `Sequential` \| `Parallel`. **`Parallel` rehydrate requires a
commutative merge** (pages merge out of order).

## 5. Transport seam (Phase 4)

`Transport` abstracts ingress/egress delivery so the mechanism is pluggable and
per-binding: `InProc` (direct) \| `CrossThread` (native mpsc **or** shared
`ThreadSafeContext`) \| `IpcTransport` \| `WsTransport`. `RelayCell` is written
once against `Transport`; a binding drives it on a goroutine, an async task, or an
evented IO interface. **The merge algebra — not the transport — guarantees
converged state** (Lean `transport_independent`), so transports may differ across
bindings and still converge to the same egress.

A **channel is a `Transport`, not a `QueueStorage`.** With `peek` optional
([QueueCell](cell-model.md#storage-backend-contract)) a native channel satisfies
the minimal storage contract directly, but its real role is **cross-thread
delivery**: the idiomatic form is `CrossThread`, where a worker owns the channel
(its mailbox), drains it, and merges into the hot-head `SourceCell` (the push-fed
regime — the pop message carries the value). Crossing a thread boundary requires
the `thread-safe` context.

## 6. Inbox / Outbox — directional roles (Phase 5)

`RelayCell` is direction-neutral. `Inbox` and `Outbox` are **role facades** (typed
constructors with direction-appropriate defaults), *not* reimplementations —
mirroring "MPSC is a *usage* of `QueueCell`, not a subtype". They earn names
because they differ in the **backpressure-propagation contract** — *who* you can
backpressure and *how*:

| Role | Edge | Backpressure target | Default overflow |
|------|------|---------------------|------------------|
| `Outbox` | app → transport (send) | the **local producer** (directly blockable via `is_full`) | Conflate(state) / Spill(event) |
| `Inbox` | transport → app (receive) | the **remote peer** — only via transport flow control (withhold credits/acks, TCP window) | Conflate(inbound) / Drop / Credit-meter |

A network link is `Outbox → Transport → Inbox`, and **end-to-end backpressure is
a chain of relays**: the local producer's `is_full` ← Outbox fullness ←
(credits / TCP window) ← remote Inbox fullness ← remote app's consumption. Both
ends share one `RelayCell` core so the signal propagates through the link as one
continuous reactive edge. Fan-out reuse: per-subscriber `RelayCell`s wire into
[`TopicCell`](cell-model.md#topiccell-broadcast) (the state-vs-event choice
becomes a `MergePolicy` choice); `WorkQueueCell` stays as-is (competing
consumers, no conflate).

## 7. Extra reactive policies (Phase 6)

Optional reactive stages composed onto the relay egress, each covering a row of
the [backpressure case matrix](relaycell-backpressure-analysis.md#3-backpressure-case-matrix-complete):

| Policy | Case | Behavior | Soundness |
|--------|------|----------|-----------|
| `WindowPolicy` | 8 (debounce/throttle) | coalesce on a time window, not just fullness | associativity (a window is a flush group — `flushGroupingIrrelevant`) |
| `RatePolicy` | 9 (token bucket) | pace egress; ingress backpressures | pacing re-chunks flushes; converged state unchanged |
| `ExpiryPolicy` | 10 (TTL) | drop elements older than a deadline | lossy-by-age (explicit) |
| `PriorityStorage` | 11 | egress by priority, not arrival | reordering — requires `Commutative` (Lean `reorder_adjacent`) |
| keyed sharding | 18 | N relays by key; merge across shards | commutative merge across shards |

`WindowPolicy` and `RatePolicy` only change *where* the relay flushes, so the
converged state is invariant (`relay_converges`). `PriorityStorage` and keyed
sharding *reorder* ops, so they are sound exactly when the policy is commutative.

## 8. Conformance

A RelayCell implementation conforms when:

1. **Composite, not a new node.** The relay is built from a `SourceCell` hot head,
   demand-driven `FormulaCell` reads, and an ingress Effect — no new node category.
2. **Converged-egress invariance (§9).** For an associative `M`, the egress state
   after any flush schedule equals the lossless flat fold of the delivered ops.
   Pinned per-binding by replaying `mergecell_algebra.json` through a relay and by
   the Lean `relay_converges` / `transport_independent` theorems.
3. **Overflow validation.** An `(overflow, transport)` pair the policy's flags
   forbid is rejected at construction; `Conflate` on `RawFifo`, `Drop` on a
   lossless policy, and reordered pages/shards on a non-commutative policy all
   fail fast. Lossy actions `log` and increment `dropped`/`conflated` counters.
4. **Spill losslessness + idempotent replay.** Reconstruction from cold pages +
   hot head reproduces the flat fold; crash-replay of the last unacked page
   converges (idempotent policy or spill dedup). Lean `spill_lossless` /
   `spill_replay_idempotent`.
5. **Reordering tax.** A commutative policy is invariant under reordering
   (priority egress, keyed sharding, out-of-order pages); a non-commutative one
   preserves arrival order. Lean `reorder_adjacent`.
6. **Reactive policy.** `BackpressurePolicy`/`SpillPolicy` limits are reactive
   cells with hysteresis; retuning a limit live re-drives dependent relays.

> **Verification form.** The converged-state and algebra invariants are pinned by
> the Lean model (`LazilyFormal.Relay`) and the `mergecell_algebra.json` compute
> fixture; per-binding behavior (overflow validation, spill, transport) is
> exercised by each binding's relay tests. Concurrency/transport interleaving is
> not a deterministic replay, so — like the thread-safe context — it is verified
> by each binding's model checker / stress harness, not a portable fixture.
