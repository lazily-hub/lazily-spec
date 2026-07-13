# PRD: Native Distributed Queue Support

**Status:** Active — TopicCell semantic core shipped; distributed storage remains post-v1
**Created:** 2026-07-08
**Depends on:** v1 [QueueCell](cell-model.md#queuecell) + `QueueStorage` adapter seam

## Problem

Applications using lazily need distributed queue semantics — producer/consumer across
process boundaries, work distribution, event delivery — but face a dilemma:

1. **External brokers** (Kafka, RabbitMQ, NATS, Redis Streams, SQS) are production-grade
   but require provisioning and operating a separate service. This is heavy for embedded,
   edge, small-to-medium-scale, or prototype deployments where the operational overhead
   of a broker exceeds the application's complexity budget.

2. **CRDT-replicated queues** (via lazily's existing `CrdtPlaneRuntime`) converge without
   coordination but cannot provide the semantics production queues need: destructive pop
   requires *agreement* (not merge), FIFO order requires a single sequencer, and
   exactly-once delivery requires a leader. CRDT is the right tool for collaborative
   editing (`TextCrdt`, `SeqCrdt`) and the wrong tool for queues. See
   [§ Background: Why Consensus, Not CRDT](#background-why-consensus-not-crdt).

### The embeddability advantage

lazily is embeddable as a library/app. Its advantage: a distributed queue can be built
**into** the application — no external service to provision, no broker to operate, no ops
team required — while still providing consensus-based strong consistency. This is the same
value proposition as SQLite vs PostgreSQL: trade raw performance and operational features
for zero-provisioning embedded simplicity.

## Positioning

> **Use an external broker when one is already available.** Established distributed
> queues have years of production hardening, tooling, client libraries, and operational
> experience. Until lazily's native distributed queue reaches feature parity, the
> external broker is the better choice for production-scale workloads. The v1
> `QueueStorage` adapter seam enables this today — a `KafkaStorage` or
> `RedisStreamStorage` backend plugs into the same reactive shell.

> **Use lazily's native distributed queue when embeddability matters.** For embedded,
> edge, small-to-medium scale, zero-provisioning, or prototype deployments, a
> library-embedded distributed queue eliminates the operational cost of provisioning
> and managing a broker. When the application is already shipping lazily, the native
> queue adds zero new dependencies.

The native distributed queue is **not** a Kafka replacement. It is the right choice when
provisioning a broker is more expensive than the problem it solves.

## Target Use Cases

| Use case | Why native (not external broker) |
|----------|----------------------------------|
| Embedded / edge deployment | No ops team, no broker to provision |
| Small-to-medium scale work distribution | Broker overhead exceeds app complexity |
| Prototyping / development | Zero-provisioning; promote to broker later via adapter |
| Single-binary distributed apps | Ship one artifact, not app + broker |
| Applications already using lazily | No new dependency; reuses reactive substrate |
| Partition-tolerant control planes | In-process queue with Raft-level consistency |

## Goals

- **Consensus-based** distributed queue (Raft replicated log), not CRDT.
- **Zero external service dependencies** — the queue is embedded in the application
  process; peers are other application instances.
- **Builds on v1** — the `QueueStorage` adapter seam is the integration point. The native
  distributed queue is a new backend (`RaftQueueStorage`), not a new primitive.
- **Path to parity** — phased delivery that converges toward feature-comparability with
  established distributed queues for the embeddable niche.
- **Cross-language** — consistent semantics across every lazily binding via the shared
  conformance fixtures, same as every other lazily primitive.

## Non-Goals (v1)

- **Not replacing external brokers** for production-scale workloads. The adapter seam
  (`KafkaStorage`, `RedisStreamStorage`, `SqsStorage`) is the recommended path when a
  broker is available.
- **Not CRDT-based.** CRDT is the wrong algebra for destructive pop.
- **Not implementing Raft from scratch.** Use an existing, proven Raft library per
  binding (or a Rust core + FFI for other languages).
- **Not partitioning / consumer groups / exactly-once transactions in Phase 1.** These
  are Phase 4 parity features.

## Background: Why Consensus, Not CRDT

A queue's defining operation is **destructive pop** — "I claim this element exclusively;
no one else may have it." This is an *agreement* problem, not a *merge* problem.

| Property needed | CRDT provides? | Consensus provides? |
|-----------------|:-:|:-:|
| Concurrent writes all survive merge | ✅ | N/A (serialized by leader) |
| Exclusive destructive pop (exactly-once) | ❌ (at-least-once) | ✅ |
| FIFO order matching push order | ❌ (fractional-index, may reorder) | ✅ (log index = total order) |
| Immediate capacity rejection (no overcommit) | ❌ (convergent `is_full` lags) | ✅ (leader rejects) |
| Single delivery ID for ack/dedup | ❌ | ✅ (leader assigns) |
| No tombstone growth under high churn | ❌ (head-pointer optimization needed) | ✅ (log compaction) |

CRDT is excellent when all operations are commutative and non-destructive (collaborative
text editing, counters, sets, shared maps). Queues are none of these. This is why every
production distributed queue (Kafka, RabbitMQ, NATS, Redis Streams, SQS) uses consensus,
not CRDT — and why lazily uses CRDT for `TextCrdt`/`SeqCrdt` but uses consensus for the
native distributed queue.

For the full analysis (CRDT tombstone growth under load, head-pointer vs tombstone GC,
resurrection safety), see the design discussion captured in
[the distributed queue pressure-test](#) (session document).

## Architecture

### Core insight: the Raft log IS the queue

A replicated log (via Raft) provides everything a distributed queue needs:

- **Total order**: log entries are committed with monotonically-increasing indices →
  FIFO is free.
- **Leader-based writes**: all pushes go through the leader → no concurrent-write
  conflicts, no fractional-index reordering.
- **Durability**: committed log entries survive leader failure → queue state is durable.
- **GC**: log compaction (snapshot + truncate below the lowest consumer cursor) reclaims
  consumed entries → bounded memory.

The queue is a **cursor over the replicated log**:

```
  ┌──────────────────────────────────────────────────────┐
  │               Replicated Log (Raft)                   │
  │                                                       │
  │  [Push A] [Push B] [Push C] [Push D] [Push E] ...    │
  │     1        2        3        4        5            │
  │                                                       │
  │  committed ──────────────────────────── ▲ ── tail    │
  │                                  consumer cursor      │
  └──────────────────────────────────────────────────────┘
                     │
                     ▼
  Queue contents = entries (consumer_cursor, tail]
  GC: entries ≤ consumer_cursor are compactable
```

- **Push** = append `Entry { value }` to the Raft log (leader serializes).
- **Pop** = read entry at `consumer_cursor + 1`, advance cursor (replicated via Raft
  state machine).
- **GC** = log compaction below the lowest cursor (or a TTL/expiry floor).

This is architecturally closer to Kafka (log + consumer offset) than to RabbitMQ
(AMQP delivery model). The log is append-only; destructive semantics live in the cursor,
not in tombstones.

### `RaftQueueStorage` as a `QueueStorage` backend

The native distributed queue is **not a new primitive.** It is a `QueueStorage` backend —
the same adapter seam that v1 defines for `VecDequeStorage`, `KafkaStorage`, etc.

```
  ┌─────────────────────────────────────────────────┐
  │            QueueCell reactive shell              │
  │  (head/tail/closed version cells, invalidation)  │
  └───────────────────┬─────────────────────────────┘
                      │ QueueStorage trait
                      │
   ┌──────────────────┼──────────────────┐
   │                  │                  │
   ▼                  ▼                  ▼
 VecDeque        RaftQueue          KafkaStorage
 (local,         (embedded          (external broker,
  default)       consensus)          via adapter)
```

This means:
- The reactive shell (invalidation, backpressure, closure) is shared across all backends.
- The consensus logic lives entirely in `RaftQueueStorage`.
- Users switch between local / native-distributed / external-broker by swapping the
  storage backend, with no change to the reactive API.

### Transport

`RaftQueueStorage` reuses lazily's existing transport infrastructure:
- **IPC** (in-process, cross-thread) — same machine.
- **WebSocket** — cross-machine, cloud/edge.
- **WebRTC** — peer-to-peer, NAT traversal.

No new transport layer. The Raft RPCs (RequestVote, AppendEntries, etc.) ride the same
`DataChannel` abstraction that the CRDT plane and command plane already use.

### Consensus implementation

Use an existing, proven Raft library — do not implement Raft from scratch.

| Binding | Candidate |
|---------|-----------|
| lazily-rs | [openraft](https://github.com/databendlabs/openraft) or [raft-rs](https://github.com/tikv/raft-rs) |
| lazily-py | FFI to Rust `RaftQueueStorage` core |
| lazily-zig | FFI to Rust core, or native Zig Raft if available |
| lazily-js | WASM-compiled Rust core, or WebSocket client to a remote leader |
| lazily-go | Native Go Raft ([etcd/raft](https://github.com/etcd-io/raft)) — idiomatic for Go |
| lazily-kt | FFI to Rust core, or native JVM Raft ([copy-cat](https://github.com/atomix/copycat)) |

The Rust core is the reference implementation; other bindings either FFI to it or use a
native Raft library in their language. The `QueueStorage` trait guarantees semantic parity
regardless of the underlying Raft implementation.

## Relationship to v1

The v1 deliverables are the **foundation** for native distributed queue support:

| v1 deliverable | Role in the distributed queue |
|----------------|-------------------------------|
| `QueueCell` reactive shell | The API surface — unchanged whether storage is local or distributed |
| `QueueStorage` adapter trait | The integration point — `RaftQueueStorage` is a new backend |
| `VecDequeStorage` default | The local reference; `RaftQueueStorage` must match its observable FIFO contract |
| FIFO-order spec clause | The cross-backend invariant — consensus-backed or broker-backed, FIFO must hold |
| Closure observable contract | Shared across backends — close semantics are shell-level |

No v1 spec/formal work is blocked by the distributed queue PRD. The adapter seam carries
the distributed story: v1 ships the seam; this PRD ships the consensus backend.

## Phased Delivery

### Phase 0 — v1 foundation (current scope)

- Local `QueueCell` (SPSC primitive + MPSC usage rule).
- `QueueStorage` adapter trait + `VecDequeStorage` default.
- `TopicCell` local semantic contract + conformance + Lean reference.
- `WorkQueueCell` portable local-authority lifecycle + conformance + Lean safety reference;
  distributed/HA claim serialization remains a Phase 2 integration.
- Reactive shell: closure, bounded/backpressure, ordering contract.

**Deliverable:** a local queue primitive with a pluggable backend seam, ready for
distributed backends.

### Phase 1 — Consensus core

- `RaftQueueStorage`: Raft replicated log + consumer cursor.
- Single-partition, single-consumer distributed queue.
- Log compaction (GC below consumer cursor).
- Transport over existing `DataChannel` (IPC / WebSocket / WebRTC).
- Conformance fixtures for distributed FIFO, durability under leader failover, GC safety.

**Deliverable:** an embeddable distributed queue with strong consistency, no external
dependencies. This is the milestone that delivers the PRD's core value proposition.

### Phase 2 — `WorkQueueCell` (exactly-once handoff)

- Reuse the shipped local `push` / `claim` / `ack` / `nack` / `reap_expired` lifecycle and
  cross-language fixtures unchanged.
- Leader-based exclusive handoff over the Raft log.
- Pop = advance cursor **with ack**; unacked entries are redelivered.
- Pending entries list (consumer failure recovery).
- Dead-letter queue (poison-message handling).
- `Receipt` integration for at-most-once effect authority.

**Deliverable:** distributed exactly-once assignment authority for the shipped competing-consumer
shell — the semantic that CRDT cannot provide and the reason production queues use consensus.

### Phase 3 — `TopicCell` (multi-cursor broadcast)

- Each subscriber maintains its own cursor over the Raft log.
- Cursor persistence (survives subscriber restart).
- Log GC bounded by the slowest subscriber's cursor.
- Fan-out semantics (one push → all subscribers receive).

**Deliverable:** pub/sub broadcast — the event-delivery use case.

**Status:** the storage-independent semantic contract, replay fixtures, and universal
Lean proofs shipped in v0.31.0. Wiring those cursors to a Raft-backed durable log remains
part of the post-v1 distributed-storage implementation.

### Phase 4 — Parity features

| Feature | Parity target | Source |
|---------|---------------|--------|
| Partitioning | Key-based routing across multiple Raft groups | Kafka partitions |
| Consumer groups | Shared cursor among group members; rebalance on join/leave | Kafka consumer groups |
| Exactly-once delivery | Transactional consumer (consume + ack + commit in one Raft round) | Kafka transactions |
| Persistence | Durable log (fsync on commit); WAL recovery | Kafka / RabbitMQ durability |
| Visibility timeout / lease | Consumer lease with TTL; redelivery on expiry | SQS |
| Priority | Priority-weighted cursor advancement | RabbitMQ priority queues |
| Monitoring | Depth / lag / throughput / consumer-position metrics | Kafka / RabbitMQ dashboards |
| Flow control | Bounded queue with quota; push rejection with backpressure signal | Kafka quota / RabbitMQ prefetch |

**Deliverable:** feature-comparability with established distributed queues for the
embeddable niche.

## Parity Boundary

lazily's native distributed queue will **not** match established brokers on:

- **Raw throughput** — dedicated brokers (Kafka) are optimized for millions of ops/sec
  with zero-copy kernel-bypass. lazily targets the embeddable niche, not the hyperscale
  niche.
- **Operational tooling** — Kafka's ecosystem (Connect, Streams, Schema Registry,
  KSQL) is decades of engineering. lazily provides the queue, not the platform.
- **Language-specific client libraries** — Kafka has clients in 30+ languages. lazily
  has its own bindings; external-broker integration uses the adapter seam.

The parity target is **semantic** (FIFO, exactly-once, persistence, ack/nack, dead-letter,
consumer groups) and **embedding-grade operational** (zero-provisioning, in-process,
no external services) — not hyperscale performance.

## Risks / Open Questions

| Risk | Mitigation |
|------|------------|
| Raft library correctness / maturity | Use proven libraries (openraft, etcd/raft); conformance fixtures validate semantics |
| Performance vs dedicated brokers | Explicitly non-goal for hyperscale; target embeddable niche |
| Multi-language Raft divergence | Rust core + FFI for bindings that can't host a native Raft; conformance fixtures enforce parity |
| Log compaction correctness under failover | Formal model + conformance fixture for GC safety under leader crash |
| Partitioning strategy (Phase 4) | Defer to Phase 4 design; single-partition is sufficient for embeddable niche in Phase 1 |
| When to recommend native vs external broker | Clear decision criteria in docs: scale threshold, existing infrastructure, operational capacity |
| Raft group membership changes | Use the Raft library's built-in membership change protocol; don't reinvent |
| Cross-backend snapshot interop | `RaftQueueStorage` defines its own snapshot format; cross-backend interop requires explicit format agreement (per v1 wire/snapshot clause) |

## Decision Criteria: Native vs External Broker

| Criterion | Native (`RaftQueueStorage`) | External (`KafkaStorage` etc.) |
|-----------|:-:|:-:|
| No external service to provision | ✅ | ❌ |
| Zero new dependencies (already using lazily) | ✅ | ❌ |
| Embeddable / single-binary deployment | ✅ | ❌ |
| Edge / resource-constrained environment | ✅ | ❌ |
| Production-scale throughput (>100K ops/sec) | ❌ | ✅ |
| Mature operational tooling / monitoring | ❌ | ✅ |
| Rich client ecosystem (30+ languages) | ❌ | ✅ |
| Existing infrastructure / team expertise | ❌ | ✅ |
| Exactly-once transactions (until Phase 4) | ❌ | ✅ |

**Rule of thumb:** if you already have a broker, use it. If provisioning one is more
expensive than the problem, use the native queue.

## References

- v1 [QueueCell spec](cell-model.md#queuecell) — local primitive + `QueueStorage` adapter
- [Cell Model § Merge mechanisms](cell-model.md#merge-mechanisms) — `lease` and `ot`
  reserved mechanisms relevant to consensus/authority-based queues
- [Command / RPC Message Plane](message-passing.md) — `command-plane-v1` transport reused
  by `RaftQueueStorage`
- [Wire Protocol § Distributed](protocol.md#distributed-crdt-cell-plane) — existing
  distributed plane (CRDT); the consensus plane is its sibling, not its replacement
- [Reactive Graph](reactive-graph.md) — the shell that wraps every `QueueStorage` backend
- [Conformance Fixtures](conformance.md) — the cross-language parity enforcement layer
