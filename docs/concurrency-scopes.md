# Concurrency scopes

Thread safety, durability, database atomicity, and replica fencing are separate
capabilities. A surface MUST publish one scope from
[`concurrency-scopes.json`](../concurrency-scopes.json); callers MUST NOT infer a
stronger scope from words such as “async”, “queue”, or “durable”.

| Scope | Coordination boundary | What it does not imply |
|---|---|---|
| `single_goroutine` | One owner goroutine or equivalent single-threaded executor. | Safe concurrent calls, persistence, or exclusion outside that owner. |
| `single_process_serialized` | Goroutines serialized by one process-local lock or owner-goroutine channel. | Database atomicity, crash durability, or exclusion from another process. |
| `durable_cross_process` | Cooperating processes coordinate through one durable authority, such as PostgreSQL transaction advisory locks. | Protection from a participant that bypasses the authority, or a distributed lease fence. |
| `distributed_fenced` | Replicas present an authority-issued monotone fence or epoch and stale actors are refused. | Database transaction semantics unless that is separately declared. |

`Context`, synchronous queues, and `LatestDurableProjectionCore` are
`single_goroutine`. `ThreadSafeContext`, `AsyncContext`, their queue surfaces,
and thread-safe/async latest-durable projections are
`single_process_serialized`. They coordinate memory within one process only;
none provides database atomicity or cross-replica exclusion. In particular,
“durable” in latest-durable projection describes the acknowledgement frontier
of an external sink, not an in-memory lock surviving a process crash.

`PostgresProjectionBarrier` is `durable_cross_process`: source writers and full
rebuilders use the same transaction-scoped advisory keys, and source mutation
plus projection replacement share a database transaction. It is the only
current capability allowed to advertise `projection_maintenance_barrier` in the
registry. A future distributed/fenced capability needs an explicit fence or
epoch; process serialization cannot be relabeled as fencing.

The registry is validated by JSON Schema and negative conformance tests. Go
mirrors the same four identifiers through `ConcurrencyScope` and tests every
in-process surface against `DatabaseProjectionMaintenanceBarrier`. Adding a
marker method to one of those surfaces therefore turns the gate red.

Terminology follows the public [Go memory
model](https://go.dev/ref/mem), [`sync` package](https://pkg.go.dev/sync), and
PostgreSQL documentation for [advisory
locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)
and [transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html).
