# Durable Outbox Stores (`#lzdurableoutbox`)

Reliable sync separates protocol from persistence:

```text
OutboxStore (ordered byte CRUD) → Outbox<S> (ack/prune/replay protocol) → SyncDriver
```

`OutboxStore` owns only `put`, `delete_through`, `scan_after`, `load_cursor`, and
`save_cursor`. `Outbox<S>` owns serialization and the invariants:

1. append before send;
2. retain every frame until the peer acknowledges its epoch;
3. keep the acknowledgment cursor monotone;
4. prune only epochs at or below that cursor; and
5. replay epochs above the cursor in ascending order after restart.

Bindings may provide platform stores without duplicating this protocol. Rust ships
`InMemoryStore` and feature-gated `SqliteStore`; Kotlin ships a SQLite/Room-shaped
store; browser JS ships `IndexedDbStore`. SQLite is never a default/WASM feature.

[`conformance/reliable-sync/outbox_store_protocol.json`](../conformance/reliable-sync/outbox_store_protocol.json)
pins the storage-independent behavior. `LazilyFormal.Replication` proves cursor
monotonicity and that replay never contains a pruned epoch.
