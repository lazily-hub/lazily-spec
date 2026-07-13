# RelayCell & Algebra-Backed Backpressure — Analysis and Implementation Plan

**Status:** design proposal (not v1 conformance). Companion to
[`cell-model.md` § Reactive queues](../cell-model.md), the
[distributed-queue PRD](distributed-queue-prd.md), and
[`protocol.md` § DurableOutbox](protocol.md).

**Thesis.** The queue family already has every *piece* of backpressure handling —
`is_full` reactive backpressure, `DurableOutbox.coalesce_to_snapshot` (LWW join, proven
`coalesce_by_join_sound`), the op-log-vs-state-supersede split, and per-subscription
TopicCell policy — but they are scattered across three primitives and the sync driver.
**`RelayCell` factors them into one first-class primitive:** a *conflating relay* that sits
on a stream edge and adapts a fast ingress to a bounded/slow egress by an **algebra-typed
merge**, a **reactive backpressure policy**, and an optional **paged durable spill**. The
merge algebra — not the primitive — decides which overflow behavior is *sound*. This
document analyzes every backpressure case, names the primitives that cover them, and gives a
phased plan.

---

## 1. The conceptual thread (what led here)

1. **Reactive queue ≠ channel.** `QueueCell` is a reactive *value* (len/head/empty/full/closed
   drive recomputation); a channel is a scheduling primitive. Non-blocking `try_push`/`try_pop`
   is the only semantics implementable identically across all bindings, so it is the core.
2. **Backpressure has two forms.** *Blocking* (park a task — Go goroutine, JS `await`) vs
   *reactive* (`is_full` invalidation re-runs a producer effect). Blocking needs a runtime;
   reactive is portable. Blocking is an opt-in per-binding adapter over the reactive signal.
3. **Decompose transport from coalescence.** Message-passing (mechanism: goroutine+channel,
   async task, thread mpsc, shared `ThreadSafeContext`, IPC, websocket) is orthogonal to
   *coalescence* (what happens to ops that accumulate while egress is blocked).
4. **Backpressure *is* the accumulation window** where coalescence applies. `batch()` is the
   explicit window; a blocked egress is the implicit window. Same primitive: *accumulate → merge
   on flush*.
5. **The coalescence algebra.** The irreducible requirement is **associativity** (fold a run of
   ops into one). **Commutativity** and **idempotency** are *independent branches* selected by the
   transport's guarantees. Full CRDT (semilattice) is only the worst-transport corner.
6. **Bounded + lossless ⇒ merge or spill.** Raw FIFO at a bounded egress forces block-or-drop;
   an accumulating semilattice bounds to O(keys) losslessly; durable **pagination** (hot merged
   head + cold paged tail) bounds memory losslessly for any algebra.

---

## 2. The coalescence algebra (refined theorem)

A merge `⊕ : T × T → T` folds accumulated ops. The properties required are selected by the
**transport contract**, not fixed:

| Transport guarantee | Required algebra | Structure | Example ops | Sound overflow |
|---|---|---|---|---|
| ordered + exactly-once | **associative** | semigroup | concat, sum, keep-latest, max | Conflate (adjacent) |
| ordered + **at-least-once** | assoc **+ idempotent** | band | keep-latest, max | Conflate, **Spill** (crash-replay) |
| **unordered** + exactly-once | assoc **+ commutative** | comm. semigroup | sum, max | Conflate (any grouping) |
| **unordered + at-least-once** | assoc + comm + idem | **semilattice join** | max, set-union, OR-Set, LWW-register | Conflate + replicate (full CRDT) |
| (none — order & multiplicity are meaning) | — | raw FIFO | events, commands | Block or Drop or Spill only |

**Consequences that drive the design:**

- **Associativity licenses variable flush points.** State-driven backpressure (flush when the
  post-merge buffer crosses a watermark) changes the *grouping* of coalesced ops; associativity
  guarantees the converged state is unchanged. This is *why* dynamic, reactive watermarks are
  sound.
- **Idempotency is the durability tax.** Durable spill ⇒ crash-replay ⇒ at-least-once ⇒ the merge
  must be idempotent, or the spill must carry dedup keys. (Matches `protocol.md`: op-log outboxes
  decline snapshot-coalesce and dedup by epoch; state outboxes coalesce by join.)
- **Commutativity is the reordering tax.** Needed only when producers/replicas/pages may merge
  out of order. A single ordered relay does not need it.
- **"LWW" is two things.** Timestamped LWW-register = `max` over a total order = semilattice
  (commutative). Positional keep-latest = right-zero band (assoc+idem, **not** commutative). Both
  conflate; they differ only on commutativity — this is the CRDT-vs-LWW branch.
- **Raw FIFO cannot conflate.** Order + multiplicity are meaning (`protocol.md` §176). Its only
  bounded-lossless option is Spill; otherwise Block (lossless, propagates) or Drop (lossy).

`MergePolicy` (see §5.3) carries these three property flags; a relay validates its
(overflow, transport) choice against them at construction.

---

## 3. Backpressure case matrix (complete)

Axes: **ordering** (FIFO / unordered), **loss** (lossless / lossy-ok), **algebra** (raw / semigroup
/ band / comm-monoid / semilattice), **bound dimension** (count / bytes / keys / age), **locality**
(in-proc / cross-thread / cross-proc / cross-net), **runtime** (sync / stackful / stackless).
`✔` = explored in conversation; `＋` = added here for completeness.

| # | Case | Ordering | Loss | Overflow action | Primitive + policy |
|---|---|---|---|---|---|
| ✔1 | Reactive backpressure (poll-free) | FIFO | lossless | Block via `is_full` effect | `QueueCell` bounded |
| ✔2 | Blocking backpressure (task park) | FIFO | lossless | `await`/goroutine block | `AsyncRelay` adapter over `is_full` |
| ✔3 | Keep-latest conflation (state) | ordered | lossy-intermediate | Conflate (band) | `RelayCell<LWW/keep-latest>` |
| ✔4 | Accumulating conflation (counter/set) | unordered | **lossless** | Conflate (semilattice) | `RelayCell<GCounter/OrSet>` |
| ✔5 | Durable paged spill | FIFO | lossless | Spill (hot head + cold tail) | `RelayCell` + `SpillStore` |
| ✔6 | State-driven ingress gating | FIFO | lossless | Block ingress on post-merge size | `RelayCell` + `BackpressurePolicy` |
| ✔7 | Per-egress policy in a chain | any | mixed | per-hop Block/Drop/Conflate/Spill | chained `RelayCell`s |
| ＋8 | Time-windowed coalescence (debounce/throttle) | ordered | lossy-intermediate | Conflate on time window, not just fullness | `RelayCell` + `WindowPolicy` |
| ＋9 | Rate-limited egress (token bucket) | FIFO | lossless | pace egress; ingress backpressures | `RelayCell` + `RatePolicy` |
| ＋10 | TTL / deadline expiry (drop stale) | any | lossy-by-age | Drop elements older than deadline | `RelayCell` + `ExpiryPolicy` |
| ＋11 | Priority / reordering egress | **not FIFO** | lossless | egress by priority, not arrival | `QueueCell` + `PriorityStorage` |
| ＋12 | Broadcast w/ slow-consumer isolation | per-sub FIFO | per-sub policy | conflate(state)/drop/evict per subscriber | `TopicCell` w/ per-sub `RelayCell` |
| ＋13 | Competing consumers (work) | assign-FIFO | at-least-once | route to idle worker; no single-slow-stall | `WorkQueueCell` |
| ＋14 | Cross-thread MPSC | per-producer FIFO | lossless | batch-serialize or shared context | `QueueCell` on `ThreadSafeContext` |
| ＋15 | Cross-process / cross-net egress | FIFO/op-log | lossless | op-log fuse + outbox spill + ack | `RelayCell` + `Transport` + `DurableOutbox` |
| ＋16 | Cycle in the graph (deadlock hazard) | any | must be lossy | a lossy firewall hop breaks the cycle | `RelayCell` lossy (Drop/Conflate) |
| ＋17 | Credit-based flow control | FIFO | lossless | explicit credits meter rehydration | `RelayCell` + `CreditPolicy` |
| ＋18 | Keyed sharding (parallel relays) | per-key FIFO | lossless | N relays by key; merge needs commutativity across shards | `RelayCell[]` keyed + semilattice |

Cases 1–7 are the conversation. 8–18 are the completeness set; every one is either an existing
primitive (11 priority, 12 topic, 13 work) or a **policy** on `RelayCell` (8,9,10,15,16,17) or a
threading tier (14) or a wiring pattern (18).

---

## 4. Primitives — new and reinforced

### 4.0 Reactive primitives — Reactive / Cell / MergeCell / Slot (± eager) / Effect

`RelayCell` is **not a new node category**; it is a *composite* built from the primitives
already pinned in [`reactive-graph.md` § The reactive family](reactive-graph.md). Restating the
settled definitions, plus the generalizations this design needs:

**`Reactive<T>` — the read supertype.** `get()` + `subscribe()`/`subscribers` only (no write).
Every node below is a `Reactive`; **writability is a sub-interface** `Source<T>: Reactive<T>` (adds
`set`/`merge`) so non-settable Slots are correctly typed. The payoff: a composite reader-kind is
declared `Reactive<T>` and the **backend chooses the impl** (pull-Slot / push-Cell / polling-Slot —
see § invalidation sourcing) behind one interface. Cross-language cost is low — `get()` + a
subscriber set is a trivial interface in every target, and most bindings already have it via handles.

| Primitive | `Reactive`? | Definition | Write? |
|---|---|---|---|
| **Slot** (with `eager` mode) | yes (derived) | lazily-computed, memoized *derived* value; computes on first read, recomputes on read-after-invalidation. **`eager` mode** = arm an internal puller **Effect** to materialize on write instead of first read; **consumer-gated** (fires only with real downstream consumers, so an eager Slot nobody observes behaves lazy). Eagerness is *self-determined* (a dependency cannot force it) and **pulls its ancestor cone** on invalidation (materializing ancestors without changing their policy) — it never propagates to descendants/siblings | no |
| ~~**Signal**~~ *(retired as a primitive)* | — | `Signal ≡ Slot + puller Effect`, so it is now just **`Slot.eager`** — one fewer primitive. The word "Signal" is left unclaimed: it has a **split meaning** — *reactive value* (SolidJS/FRP) vs *data event/notification* (Qt Signals&Slots, OS signals, EE/DSP, pub/sub). If ever reintroduced, the *event* sense (aligned with the event-vs-state split: RawFifo events vs coalescible `MergeCell` state) is the better anchor; boundary/handler roles are already `Inbox`/`Outbox`/`Effect` | — |
| **`Source<T>`** | yes | `Reactive` + `set`/`merge` | — |
| **Cell** | via `Source` | mutable *source*; `set_cell` updates + invalidates, **no-op on `==`** | yes (replace) |
| **`MergeCell<T,M>`** *(generalizes Cell)* | via `Source` | a source whose write is a **merge** `⊕`; `Cell ≡ MergeCell<KeepLatest>` | yes (merge / PATCH) |
| **Effect** | — | the eager reactor; runs on invalidation. An eager Slot's puller is one; a general Effect may **merge into a `MergeCell`** (the eager relay driver) | writes as side-effect |

**MergeCell instances** (all wire the existing `#lzsync` CRDT units): plain `Cell` = `KeepLatest`
band; CRDT register = `Lww` semilattice; counter = `Sum` comm-monoid; set = `OrSet` semilattice.
The `==` no-op guard generalizes to *"no-op when `⊕(old,v) == old"*; for an **idempotent** `⊕` this
gives free dedup — the PartialEq guard and merge-idempotency are the same mechanism one layer up.

**Merge cost law (the perf model, activity-gated).** `MergeCell.merge(v)` always computes `⊕(old,v)`;
if the result equals `old`, it no-ops. Otherwise it stores and propagates **lazily**. The cost tiers
by dependent kind:

| MergeCell dependents | Cost of `merge(v)` | Eager propagation tax |
|---|---|---|
| none | `⊕` + store | none (store-without-cascade) |
| **lazy only** (Slots, no downstream Effect) | `⊕` + store + O(deps) dirty-mark | none — no recompute, no flush |
| **active** (an Effect transitively downstream) | `⊕` + store + dirty + **flush** | the tax = schedule + run effects |

"Active" = *an Effect exists transitively downstream*; a bare Slot dependent is lazy (needs only a
dirty bit). The dirty flags live on the **dependent Slots**, not the source (a source is always
authoritative, never "dirty"). Dirty-marking is **idempotent and monotonic** — `mark_dirty` on an
already-dirty Slot returns without recursing — so the transitive walk is paid **once** per
clean→dirty transition; a **burst of N merges with no interleaved active read pays
dirty-propagation once**: `N·⊕` + 1 transitive-dirty + ≤1 materialization. (An optional per-source
"already-signaled-since-clean" flag, cleared when a dependent reads through, drops even the
immediate-dependent notification to O(1) during a burst.) **The gap between two active reads
is a Cell-level coalescence window, and `⊕` is the coalescence.** `RelayCell`'s bounded/durable
conflation is exactly this mechanism at composite scale (hot-head `MergeCell` + policy + spill) —
the primitive and the composite are the same idea at two scales. The measured 327 ns → ~10 ns
collapse (§5) is just this law: *no active subscriber → no tax.*

**Invalidation sourcing — the reader-kind impl follows what you own.** A `Reactive<T>` reader-kind
(`len`/`head`/…) needs an invalidation source; who owns the mutation decides which of the three impls
it is:

| We own… | Reader-kind impl | Invalidation source |
|---|---|---|
| the mutation (VecDeque, or a channel *our* code sends/recvs on) | **Slot** | `push`/`pop` bump a `generation: Cell<u64>` the Slot subscribes to |
| only the **actor** fronting a foreign queue | **push-fed `MergeCell`** | the operation result/message *carries* the value (**the pop message contains the len**) — set the Cell from it; no re-pull, no poll |
| neither queue nor its mutation site (foreign sender) | **TTL Slot** (lazy) or **poll** (eager) | lazy consumer → TTL-versioned Slot (bounded staleness, freshness on read, no timer); eager consumer that must react → poll (no push-reactivity is free from a non-notifying source) |

So "reactive over a queue we don't own" is achieved by owning the **operation boundary**, not the
queue; prefer the push-fed `MergeCell` (regime 2) over re-pulling a slow backend, and for a fully
foreign source use a TTL Slot for lazy reads (poll only when an eager consumer must react). Same
storage-vs-transport seam as §4.6; §5 is this rule applied to `QueueCell` (and corrects the earlier
over-broad "len is always a Slot"). The TTL Slot is a `version()`-based mechanism — see the separate
[version-based invalidation plan](version-based-invalidation-plan.md), which also specs the optional
revision engine that trades the push write-walk for O(1) writes.

### 4.1 `QueueCell` (reinforce) — implementation-agnostic FIFO, lazy reader-kinds

`QueueCell` stays the **FIFO delivery-semantics primitive** (Axis 1, `cell-model.md` §526). Two
reinforcements:

- **Implementation-agnostic.** FIFO can be provided three ways, all behind `QueueStorage`:
  (a) the default `VecDequeStorage`; (b) a **native construct** wrapped as a backend — a Go
  channel, a Rust `crossbeam` mpsc, a JS array, a disruptor ring buffer, a library queue;
  (c) **bypass** `QueueCell` and use the native construct directly when no reactive reader-kind
  is needed. The shell never assumes a storage type (already normative, §634).
- **Minimal contract — `peek` removed.** Required `QueueStorage`: `try_push` / `try_pop` / `len` /
  `is_closed` / `close`. **Optional capabilities** advertised by the backend: `capacity()` (gates the
  `is_full` reader, as today) and — newly optional — `peek()` (gates the `head` reader). The
  normative MUST-reactive set is `{is_empty, len, is_full}` (`cell-model.md` §741) — **`head` was
  never in it** — so `len`/`is_empty`/`is_full` (all derived from `len()`/`capacity()`) need no peek.
  A backend that cannot peek is fully conforming; it simply has no `head` reader, exactly as an
  unbounded backend has no `is_full`. *Footnote:* a backend MAY still expose a reactive `peek`/`head`
  natively, or a caller MAY opt into a shell-level `LookaheadShim` (prefetch one element) — **SPSC-local
  only** (early-pop is wrong for consensus/competing backends). This makes a raw Go channel satisfy
  the minimal contract directly (the peek shim was the *only* gap).
- **Lazy reader-kinds** (§5 below): the `is_full`/`len`/`is_empty`/`head` reads are **demand-driven** —
  maintained only while subscribed. An unsubscribed `QueueCell` costs its raw storage (~10 ns),
  not the full reactive shell (~327 ns measured). This makes wrapping a native queue in
  `QueueCell` nearly free until a reader-kind is actually observed.

### 4.2 `RelayCell` (new) — the algebra-typed conflating relay

A `RelayCell<T, M: MergePolicy<T>>` is a **stream transform** on an edge: it pulls from an
ingress, holds an accumulating **hot head**, and pushes to an egress under a policy. It is *not*
a new Axis-1 delivery semantics, and *not* a new node category — it decomposes into the §4.0
primitives: the **hot head is a `MergeCell<T,M>`** (write = `⊕`), its reactive reads
(`depth`/`is_full`/`head`) are **Slots**, and an ingress **Effect** drives the merge. It composes
onto `QueueCell`/`TopicCell`/`WorkQueueCell` edges. Per the merge cost law (§4.0), a high-throughput
relay whose reads are unobserved costs `N·⊕` + amortized nothing; the tax turns on only along a path
an Effect actually observes.

```
        ingress            ┌──────────── RelayCell ─────────────┐          egress
  ─────(Transport)────────►│ hot head : accumulating merge (⊕)  │────────►(Transport)──►
     ops arrive fast       │ BackpressurePolicy (watermarks)    │   drained on egress
                           │ overflow: Block|Drop|Conflate|Spill │   readiness (credit)
                           │ SpillStore (paged durable tail)     │
                           │ reactive reads: depth/bytes/keys    │
                           └────────────────────────────────────┘
```

Observable reactive reads (all lazy): `depth`, `bytes`, `pending_keys`, `is_full`, `is_spilling`,
`is_draining`, `lag`. The **converged egress state** is invariant across runtime/mechanism as long
as `M` is at least associative — this is the property fixtures pin (§9).

`RelayCell` **subsumes** today's scattered logic: `DurableOutbox.coalesce_to_snapshot` becomes a
`RelayCell<_, LWW>` with a `SpillStore`; TopicCell per-subscriber conflation becomes a per-sub
`RelayCell`; op-log outbox fusion becomes a `RelayCell<_, RawFifo>` with Spill (no conflate).

### 4.3 `MergePolicy` (new) — the algebra trait

```rust
trait MergePolicy<T> {
    fn merge(&self, acc: T, next: T) -> T;      // ⊕ — MUST be associative
    const ASSOCIATIVE: bool = true;             // required; enforced by law-tests
    const COMMUTATIVE: bool;                     // may reorder / merge shards out of order
    const IDEMPOTENT:  bool;                     // safe under at-least-once / crash-replay
    fn key(&self, _v: &T) -> Option<Key> { None } // keyed conflation → bound = O(distinct keys)
}
```

Reference impls wire the **existing CRDT units** (`#lzsync`): `KeepLatest` (band), `LwwRegister`
(semilattice), `GCounter`/`PnCounter` (comm-monoid), `OrSet` (semilattice), `RawFifo` (no merge —
Spill/Block/Drop only). A `RelayCell` rejects an `(overflow, transport)` pair the policy's flags
forbid (e.g. `Conflate` on `RawFifo`, `Drop` on a lossless `GCounter`, reordered pages on a
non-commutative band).

### 4.4 `BackpressurePolicy` (new) — reactive limits

All limits are **reactive cells**, so an operator or adaptive controller retunes them live and
every dependent relay reacts (hysteresis via high/low watermark avoids thrash):

```rust
struct BackpressurePolicy {
    dimension:  Cell<BoundDim>,   // Count | Bytes | Keys | Age
    high_water: Cell<u64>,        // gate ingress at/above
    low_water:  Cell<u64>,        // re-open ingress at/below
    overflow:   Cell<Overflow>,   // Block | DropOldest | DropNewest | Conflate | Spill
}
```

### 4.5 `SpillStore` (reinforce — generalize `DurableOutbox`)

Paged durable tail: hot page in RAM (actively merged), overflow pages immutable on durable store,
a bounded **manifest** (`page_id → location, watermark, bytes`), an egress **cursor**, and
ack-before-reclaim. Memory = `O(hot page) + O(manifest)`. Retrieval is pull-metered by the egress
credit; associativity lets a lagging consumer receive *conflated* catch-up. This is
`DurableOutbox` (`protocol.md` §979) generalized with a conflation head and made a `RelayCell`
backend. Crash recovery replays the last-acked page; idempotency (band tier) makes replay safe.

### 4.6 `Transport` (new seam) — message-passing mechanism

Abstracts ingress/egress delivery so mechanism is pluggable and per-binding:
`InProc` (direct), `CrossThread` (native mpsc **or** shared `ThreadSafeContext`), `IpcTransport`,
`WsTransport` (websocket). `RelayCell` is written once against `Transport`; Go drives it on a
goroutine, JS/Dart on an async task, Zig 0.16 on the evented `Io` interface. The merge algebra —
not the transport — guarantees converged state, so transports may differ across bindings.

**A channel is a `Transport`, not a `QueueStorage`.** With `peek` now optional (§4.1), a Go channel
satisfies the **minimal `QueueStorage` contract directly** — no shim; it just has no `head` reader
(opt into `LookaheadShim` only if you want one, SPSC-local). But the reason to keep channels at the
transport seam is no longer a contract gap — it's **cross-goroutine delivery**: the idiomatic form is
`CrossThread`, where a **goroutine owns the channel (its mailbox), drains it, and merges into the
state `MergeCell`s** (the eager relay driver of §4.0; regime 2 of § invalidation sourcing — the pop
message carries `len`). This crosses a thread boundary, so it requires `ThreadSafeContext`; the
channel then serves its actual strength (cross-goroutine MPSC + blocking) rather than being forced
into the storage slot.

### 4.7 `Inbox` / `Outbox` — directional roles over `RelayCell`

`RelayCell` is direction-neutral. Two **role facades** (typed constructors with direction-appropriate
defaults), *not* separate reimplementations — mirroring "MPSC is a *usage* of `QueueCell`, not a
subtype":

| Role | Edge | Backpressure target | Default overflow |
|---|---|---|---|
| **`Outbox`** | app → transport (send) | the **local producer** (directly blockable via `is_full`) | Conflate(state) / Spill(event) — generalizes `DurableOutbox` |
| **`Inbox`** | transport → app (receive) | the **remote peer** — *not* directly blockable; only via transport flow control (withhold credits/acks, TCP window) | Conflate(inbound) / Drop / Credit-meter |

These earn names (unlike the rejected fan-in/fan-out) because they differ **semantically in the
backpressure-propagation contract** — *who* you can backpressure and *how* — not merely in wiring.
A network link is `Outbox → Transport → Inbox`, and **end-to-end backpressure is a chain of
relays**: local producer's `is_full` ← Outbox fullness ← (credits / TCP window) ← remote Inbox
fullness ← remote app's consumption. Both ends share one `RelayCell` core precisely so the signal
propagates through the link as one continuous reactive edge (unifies cases #7 and #15).

---

## 5. Lazy-writable reader-kinds (demand-driven derivation)

**Problem (measured).** Today every successful `try_push`/`try_pop` calls `sync_content()`, which
opens a `batch()` and `Set`s four cells (head/len/empty/full) unconditionally: **~327 ns, 616 B,
7 allocs** per op even with **zero subscribers** — vs **~10 ns, 1 alloc** for the bare storage.
The reactive shell is charged whether or not anyone observes it.

**Fix — reader-kinds become demand-driven `Reactive<T>` (Slot when we own the mutation).** A
reader-kind is maintained iff it has subscribers; otherwise the op only marks it dirty (O(1)), and
it is recomputed lazily on first `Get`. This is the **owned-mutation regime** (§4.0 invalidation
sourcing): `push`/`pop` bump a `generation` cell the Slot subscribes to. For actor-fronted or foreign
backends the reader-kind is instead a push-fed `MergeCell` or a polling Slot per that table — *"len
is a Slot"* holds only when we instrument the mutation:

```
on op (push/pop):
  for k in {head, len, empty, full}:
     if k.has_dependents():  k.invalidate_and_recompute()   // eager, as today
     else:                   k.mark_dirty()                  // O(1); skip Len()/Peek()/Set/batch
on Get(k):
  if k.dirty: k.value = derive_from_storage(); k.dirty = false
  subscribe(current_effect); return k.value
```

This is nothing more than **using the right §4.0 primitive**: a derived reader-kind *is* a **Slot**,
not a `Cell`. Today `queue.go` mis-types them as `*Cell` and `Set`s them eagerly; converting
`Cell → Slot` is the fix, and the 327 ns → ~10 ns collapse is the merge cost law (§4.0) with no
active subscriber → no tax. An unsubscribed `QueueCell` collapses toward raw-storage cost; you pay
for a reader-kind only when an Effect observes it. It **preserves the observable contract** —
`is_empty`/`len`/`is_full` are still "reactive when their conditions can change" (§741); *reactive*
becomes *demand-driven reactive*. Same optimization applies to `RelayCell`'s reads.

**Write-side dual — store-without-cascade.** When a reader-kind is *not* derivable but **push-held**
(a goroutine draining an opaque channel deposits state — §4.6), it is a `MergeCell`, and the same
gating applies to the *write*: `merge(v)` stores the value but skips the eager cascade when there is
no active (Effect-bearing) dependent — it still stores the latest so a *future* subscriber reads
current state glitch-free (late-subscribe correctness), it just does not flush. Read-side
(demand-driven Slots) and write-side (activity-gated `MergeCell`) together make an unobserved
reactive node — pull-derived or push-populated — cost ≈ raw storage.

**Normative refinement to propose for the spec:** "A reader-kind MUST be observable-consistent; a
binding MAY defer its derivation until it has a subscriber, provided a subsequent `Get` returns the
value consistent with all preceding ops." Conformance stays green (fixtures read the values); the
fast path just skips derivation nobody watches.

---

## 6. Reactive policy design

Everything that bounds or shapes a relay is itself a reactive value, so policy is a *graph*, not a
config struct — it can adapt at runtime and be driven by observed load.

- **Binding limits (memory).** `BackpressurePolicy` cells (§4.4). An **adaptive controller** is a
  `computed` cell: observe `depth`/`lag`/downstream latency → set `high_water`. The control loop is
  reactive policy driving reactive limits. Hysteresis (high≠low) prevents flapping.
- **Coalescence / merge mechanism.** `MergePolicy` is a value; it MAY be swapped only at a safe
  point (empty hot head) since changing `⊕` changes semantics — the relay exposes `can_reconfigure`
  (true when head empty). Property flags gate legal overflow/transport at swap time.
- **Pagination mechanism.** `SpillPolicy { page_size, mode: CompactOnWrite | AppendCompact,
    retention: BoundedDisk | UnboundedLog | Ttl, rehydrate: Sequential | Parallel }` — all reactive.
  `CompactOnWrite` (keep-latest) minimizes disk; `AppendCompact` (LSM-style) preserves increments
  for accumulating semilattices. `Parallel` rehydrate requires a commutative merge.
- **Rate / window / expiry.** `RatePolicy` (token bucket, reactive rate), `WindowPolicy`
  (debounce/throttle interval), `ExpiryPolicy` (TTL) are optional reactive stages composed onto the
  relay egress.

---

## 7. Example systems

### 7.1 Embedded WebSocket server (state broadcast + command ingest)

An app embeds a WS server; browsers subscribe to live state and send commands.

```
             ┌────────────────── application process ──────────────────┐
 clients ───►│  WsTransport (ingress: commands)                        │
   (N)       │      │                                                   │
             │      ▼   Inbox<Command, RawFifo>  (FIFO, exactly-once,   │
             │   command inbox  order is meaning; Block = stop reading) │
             │      │        merge into app state (ThreadSafeContext)   │
             │      ▼                                                    │
             │   app state cells ──► TopicCell<StateDelta> (broadcast)  │
             │                          │ per-subscriber                │
             │        ┌─────────────────┼───────────────────┐          │
             │        ▼                 ▼                    ▼          │
             │  Outbox<KeepLatest>   Outbox<KeepLatest>    Outbox       │  ← one per connection
             │  bound=Bytes, over-    ...                   <RawFifo>   │
             │  flow=Conflate         (slow client)         Spill (audit│
             │        │                 │                    channel)   │
             │        ▼ WsTransport egress (network backpressure)       │
 clients ◄───┤   socket send; is_full → pause socket read (TCP window)  │
             └─────────────────────────────────────────────────────────┘
```

- **Ingress (commands) — an `Inbox<Command, RawFifo>`** (§4.7): commands must preserve order and not
  merge, so `RawFifo`; bounded, overflow `Block`. Because an Inbox cannot block the remote directly,
  "block" here means *stop reading the socket* → TCP window closes → the flooding client's own send
  throttles (transport flow control to the remote). Under `WsTransport` this is exactly the Inbox's
  backpressure contract.
- **State egress — a per-connection `Outbox<StateDelta, KeepLatest>`**, bound by **bytes**, overflow
  **Conflate**.
  A slow client receives the *latest* state per key, never a growing backlog — memory bounded to
  O(keys), producer feels nothing (matches TopicCell "state topic" policy, §780). This is the
  classic live-dashboard / market-data conflation.
- **Lossless channels (e.g. audit/event stream):** per-connection `Outbox<RawFifo>` + **Spill** —
  events cannot conflate, so overflow pages to a durable tail; the slow client rehydrates on credit,
  nothing lost, memory bounded.
- **Abusive client:** `Overflow::Drop` + evict on sustained lag (liveness lease, §791).
- **Runtime:** Go = goroutine per connection (stackful relay loop); Node = async per connection;
  Zig 0.16 = evented `Io`. Converged client state identical (KeepLatest is associative).

### 7.2 High-volume telemetry pipeline (bounded, lossless)

`ingest → RelayCell<GCounter>(rate-limited, TTL-drop cold) → SpillStore(AppendCompact) → batch
egress to sink`. Counters accumulate (lossless, O(keys)); spill bounds memory; rate policy paces the
sink; TTL drops only cold aged data. Lossless for live counters, bounded RAM.

### 7.3 Cross-thread work pool

`N producers → WorkQueueCell (competing) → worker pool`, FIFO backend = native mpsc wrapped as
`QueueStorage` (`QueueCell` impl-agnostic). One slow worker doesn't stall (items route elsewhere,
§861). MPSC serialization via `ThreadSafeContext` or `batch()`.

### 7.4 Reactive document sync (the reliable-sync / `#lzsync` use case)

Document edits → `RelayCell<LWW>` keyed per cell → `Transport` to plugins, with `SpillStore` =
`DurableOutbox`. This *is* the agent-doc reliable-sync plane; `RelayCell` generalizes the
`DurableOutbox` + `ResyncCoordinator` conflation into the catalog primitive, so the sync driver
becomes a `RelayCell` wiring rather than bespoke code.

---

## 8. Implementation plan (phased)

Discipline (per refactor-spiral guardrails): **spike one binding → prove converged-state
determinism against a second, stackless binding (JS) → port → add conformance fixtures + formal
pin.** `RelayCell` and `QueueCell` stay **distinct types**; no rewrite of `QueueCell`.

- **Phase 0 — Activity-gated reactivity + minimal storage contract (prereq, low risk).** Three
  changes: **(a read)** convert `QueueCell` derived reader-kinds from `Cell` to memoized **Slot** +
  `generation`-cell dirty-marking (§5) — a typing correction; **(b write)** add **store-without-cascade**
  to the `Cell`/`MergeCell` fast path (`if no active dependent { store; skip flush }`); **(c contract)**
  **remove `peek` from the required `QueueStorage` contract**, make `peek`/`head` an optional
  capability (like `capacity`/`is_full`), footnote the opt-in `LookaheadShim`. Reference in Rust;
  benchmark the ~327 ns → ~10 ns collapse + burst-merge "dirty-once"; confirm a raw channel now
  conforms; existing fixtures stay green. Propose the demand-driven, store-without-cascade, and
  optional-`peek` normative refinements. Port to all bindings.
- **Phase 1 — `Reactive` supertype + `MergeCell` + `MergePolicy` + law-tests.** Introduce the read
  supertype `Reactive<T>` (get + subscribe) with `Source<T>: Reactive<T>` adding set/merge, so a
  reader-kind can be a Slot / push-`Cell` / polling-Slot behind one interface. `MergeCell<T,M>` as the
  generalization of `Cell` (`Cell ≡ MergeCell<KeepLatest>`); trait + property flags wiring existing
  CRDT units (`KeepLatest`/`Lww`/`GCounter`/`OrSet`/`RawFifo`). Property-based law-tests (associativity
  always; commutativity/idempotency per flag; idempotent-`⊕` no-op = the `==` guard). Fixtures per tier.
- **Phase 2 — `RelayCell` core (in-proc).** Hot head + `BackpressurePolicy` + overflow
  Block/Drop/Conflate; reactive reads. **Spike in Go (stackful), prove determinism in JS
  (stackless)** — the case most likely to expose a timing dependency. Fixtures: same op stream →
  same converged egress regardless of flush points.
- **Phase 3 — `SpillStore` / paged durable tail.** Generalize `DurableOutbox`: manifest + cursor +
  ack-before-reclaim + crash recovery. `CompactOnWrite` and `AppendCompact` modes. Crash-replay
  fixtures assert idempotent convergence.
- **Phase 4 — `Transport` seam.** InProc → CrossThread (native mpsc + `ThreadSafeContext`) → IPC.
  `RelayCell` over `Transport`; converged state invariant across transports.
- **Phase 5 — Fan-out reuse.** Wire per-subscriber `RelayCell` into `TopicCell` (state-vs-event
  policy becomes a `MergePolicy` choice); `WorkQueueCell` unchanged (competing, no conflate).
- **Phase 6 — Extra policies.** `WindowPolicy` (debounce/throttle), `RatePolicy` (token bucket),
  `ExpiryPolicy` (TTL), `PriorityStorage` (case 11), keyed sharding (case 18, commutative merge).
- **Phase 7 — Example systems as integration tests.** Embedded WS server (§7.1) drives the whole
  stack; telemetry, work pool, doc-sync as smaller integ tests.
- **Phase 8 — Port + pin.** Port to remaining bindings; full conformance parity; formal pins
  (`RelayCell.lean`: `conflate_by_join_sound` generalized — any associative grouping converges;
  idempotent replay equivalence; the existing `coalesce_by_join_sound` becomes a corollary).

---

## 9. Non-goals, risks, invariants

- **Non-goal:** replacing `QueueCell` FIFO with channel semantics, or a distributed `RelayCell`
  backend in v1 (consensus queues remain the PRD's scope; CRDT relays are the merge path).
- **Risk — merge-swap mid-stream:** changing `⊕` changes meaning; only allowed at empty head. Guard
  with `can_reconfigure`.
- **Risk — silent lossy defaults:** `Conflate`/`Drop` lose intermediates; the relay MUST `log` its
  overflow action and expose `dropped`/`conflated` counters (no silent truncation).
- **Invariant to protect above all:** policy and transport are *local mechanism*; the **converged
  egress state is binding-independent** whenever `⊕` is associative. Every fixture asserts this.
  Break it (a non-lattice merge on a reordering transport) and portability, determinism, and the
  formal pin all fail together.
