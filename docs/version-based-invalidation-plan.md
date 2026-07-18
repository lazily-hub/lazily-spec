# Version-Based (Revision) Invalidation — Plan

**Status:** ratified — the `get_equiv_push` formal pin shipped
(`lazily-formal/LazilyFormal/RevisionEngine.lean`), and lazily-rs v0.43.0
implements the engine (`Context::with_revision_engine()`, accepted by the full
existing reactive conformance suite). An **optional, Context-level**
invalidation engine. Companion to
[`reactive-graph.md`](reactive-graph.md) (default push engine) and
[`relaycell-backpressure-analysis.md`](relaycell-backpressure-analysis.md) (merge cost law).

**Thesis.** lazily's default invalidation is **push / tree-walk**: a `Source` change walks its
dependents marking them dirty — **O(1) reads**, **O(dirty-cone) writes** (amortized "dirty-once" per
clean→dirty transition). For **write-heavy / high-fan-out / bursty-write** workloads a **pull /
revision** engine gives **O(1) writes** at the cost of read-time verification. This plan specs
revision invalidation as an **optional engine behind the same observable contract**, plus a unifying
`version()` extension point that also covers TTL/foreign sources. It is **not the default** and
**not per-node configurable** — engine choice is per-`Context`, never mixed within one graph.

---

## 1. The tradeoff (why)

| Strategy | Write cost | Read cost | Wins when |
|---|---|---|---|
| **push / tree-walk** (default) | O(dirty cone), amortized once per clean→dirty | **O(1)** (own dirty flag) | read-heavy · shallow · rare/rare-fanout writes (UI, sync) |
| **revision / pull** (this plan) | **O(1)** (bump a counter, no walk) | O(1) if unchanged since last read, else O(changed-subpath) verify | write-heavy · huge fan-out · bursty writes · foreign/TTL sources |

**The naive-epoch pitfall to avoid.** A per-`Source` epoch that a Slot re-scans on every read pushes
**O(#source-ancestors)** — and on *deep* graphs, O(depth) — onto reads. That is worse than push for
read-heavy graphs. The production form (below) fixes this with a global revision + last-verified +
value early-cutoff, so an unchanged graph verifies in O(1).

---

## 2. The scheme (salsa-style — the correct form)

Per `Context`:

- **Global revision counter `R`** — bumped once on any `Source` write. O(1), no propagation.
- Each **node** stores: `verified_at: Revision`, `value_version: u64`, cached value, and the
  `(input, input_value_version)` snapshot seen at its last compute.

**`verify(node, R)`** (called by `get`):
1. If `node.verified_at == R` → **clean**, return cache. *(O(1) — the common case when nothing wrote
   since the last read.)*
2. Else, for each input: `verify(input, R)` recursively.
3. **Value early-cutoff (red-green):** if every input's `value_version` matches the snapshot (inputs'
   *values* did not change), the node is still valid → set `verified_at = R`, return cache **without
   recomputing**.
4. Otherwise recompute, bump `node.value_version` (guarded by `==` / memo — an equal recompute does
   *not* bump, stopping the cascade), refresh the input snapshot, set `verified_at = R`, return.

Early-cutoff is the same role the `==`/memo guard plays in push mode — an unchanged value stops
propagation. Complexity: **O(1) write**; read **O(1)** when `verified_at == R`; else O(changed
subpath) with cutoff — never a full-tree walk unless the whole path actually changed.

---

## 3. Unifying `version()` — push / revision / TTL are one question

Add an optional `version() -> u64` (or opaque token) to `Reactive<T>`. Staleness detection then has
three interchangeable mechanisms behind one interface:

| Mechanism | How a consumer learns staleness | Source |
|---|---|---|
| **push** | version bump triggers a dirty-walk (eager notify) | default |
| **revision** | version compared lazily on read (§2) | this plan |
| **TTL** | `version = floor(now / ttl)` — no notification needed | foreign / non-notifying sources |

This folds in the **foreign-`len`** case (regime 3 of the RelayCell doc): a **TTL-versioned Slot**
serves *lazy* consumers with bounded staleness and no background timer (freshness paid on read); a
*poll* is still required only for an **eager** consumer that must *react* to a non-notifying source
(no push-reactivity is free from a source that does not notify). TTL is just a time-epoch `version()`.

---

## 4. Interaction with the primitives

- **Cell / MergeCell (Sources):** on a value-changing `set`/`merge`, bump `Context.R` and the node's
  `value_version` (guarded by `==` / idempotent `⊕`). No dependent walk.
- **Slot:** carries `verified_at` + input-version snapshot.
- **Eager Slot (`Slot.eager`, the retired "Signal"):** its puller re-verifies on `R` bump, still
  **consumer-gated** (fires only with real downstream consumers). Works under both engines unchanged.
- **`QueueCell` / `RelayCell` reader-kinds:** the **merge cost law's write cost changes** — revision
  makes a `merge`/`push` **O(1) regardless of the subscriber cone** (no dirty walk), moving the cost
  to read-time verify. For a **high-fan-out relay** (many subscribers to `is_full`/`depth`), revision
  can materially cut write cost; for a read-heavy reader-kind, push wins. This is the crossover to
  benchmark (§8-P2).

---

## 5. Concurrency / `ThreadSafeContext`

- `Context.R` is an **atomic** counter.
- Per-node `verified_at` / `value_version` under concurrency reuses the existing async machinery:
  `reactive-graph.md` § Thread-safe conformance already pins **"an in-flight recompute is parked on a
  per-slot generation/condvar sidecar; a stale completion is discarded"** — the revision engine layers
  `verified_at` on that same sidecar. Concurrent `verify` of the same node memoizes once and parks the
  rest; a completion stale w.r.t. a newer `R` is discarded and re-verified. No new locking model.

---

## 6. Observable equivalence (the invariant + formal pin)

Both engines **MUST** produce **identical observable value sequences** — every `get` returns the
same value it would under push, glitch-free. Only the perf profile differs; the engine is a **drop-in
substitution, not a semantics change**.

- **Conformance:** the *existing* reactive conformance fixtures MUST pass **unchanged** under the
  revision engine (that is the acceptance test — no new observable behavior).
- **Formal pin:** `RevisionEngine.get_equiv_push` — for any op sequence, revision-`get` ≡ push-`get`
  (extends the glitch-free / memo-equal lemmas already in the formal model).
- **Perf characterization** (not conformance): crossover benchmarks (§8-P2) — write:read ratio and
  fan-out where revision overtakes push.

---

## 7. Scope / non-goals

- **Per-`Context` engine choice** (a whole `Context` is push **or** revision). **Not per-node.**
  **No mixed-engine graphs** — that is where correctness bugs breed.
- **Push + dirty-once remains the default.** Revision is opt-in.
- **Not per-tree-shape configurable in v1** — premature; measure first (§8-P2).
- **No new observable semantics** — equivalence (§6) is the hard invariant.
- A binding **MAY** ship push-only; revision is optional per binding.

---

## 8. Phased plan

- **P0 — `version()` extension point.** Add optional `version()` to `Reactive<T>`; default impl is a
  monotonic counter bumped by push invalidation. Non-breaking; lets both engines and TTL coexist behind
  one interface. Reference in Rust.
- **P1 — Revision engine (Rust).** Global `R` + `verified_at` + value early-cutoff (§2). **Acceptance:
  run the full existing reactive conformance suite under the revision engine — must be green** (proves
  observable equivalence, §6).
- **P2 — Crossover benchmarks.** Write-heavy / high-fan-out (revision expected to win) vs read-heavy /
  shallow (push wins). Publish the crossover so operators can choose per-`Context`.
- **P3 — `ThreadSafeContext` revision.** Atomic `R` + concurrent verify on the existing generation/
  condvar sidecar (§5).
- **P4 — TTL-versioned Slot.** Foreign-source lazy path (regime 3); unify under `version()` (§3).
- **P5 — Context-level opt-in API + formal pin + optional port.** `Context::with_engine(Revision)`;
  pin `get_equiv_push`; port to bindings that want it.

---

## 9. Decision guide

Pick **revision** when: write:read ratio is high · fan-out is large · writes are bursty · sources are
foreign/TTL (no push notification). Otherwise keep **push** (the default) — O(1) reads and dirty-once
already handle the common read-heavy, bursty-write-then-read pattern.
