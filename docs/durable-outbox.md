# Durable Outbox Stores (`#lzdurableoutbox`)

Reliable sync separates protocol from persistence:

```text
OutboxStore (ordered byte CRUD) → Outbox<S> (ack/prune/replay protocol) → SyncDriver
```

`OutboxStore` owns only `put`, `delete_through`, `scan_after`, `load_cursor`, and
`save_cursor`. `Outbox<S>` owns serialization and the invariants:

1. append before send;
2. retain every frame until the peer acknowledges its epoch;
3. keep the acknowledgment cursor monotone, including when a stale storage
   handle writes after a newer handle;
4. prune only epochs at or below that cursor; and
5. replay epochs above the cursor in ascending order after restart.

Persistent `save_cursor(epoch)` implementations MUST serialize
`max(stored_cursor, epoch)` atomically. A process-local maximum is insufficient:
two handles can both open at cursor zero, then write 9 and 3 in that order. The
serialized result must remain 9, and a subsequent protocol read must observe 9.

Bindings may provide platform stores without duplicating this protocol. Rust
ships `InMemoryStore` and feature-gated `SqliteStore`; Kotlin ships a
SQLite/Room-shaped store; browser JS ships `IndexedDbStore`; other native
bindings ship append-only file journals. SQLite is never a default/WASM feature.

[`conformance/reliable-sync/outbox_store_protocol.json`](../conformance/reliable-sync/outbox_store_protocol.json)
pins the storage-independent behavior. `LazilyFormal.Replication` proves cursor
monotonicity and that replay never contains a pruned epoch.

An append-only journal is a versioned durable wire surface: a later process, and
possibly a different build of the same binding, reads records written earlier.
Readers MUST reject a complete record whose opcode they do not recognize. They
MUST NOT skip it as though it were a cursor marker, because an ignored pruning
operation can resurrect acknowledged frames and redeliver them while reporting a
successful scan.

The sole recovery exception is a torn trailing record. A crash may interrupt the
last append, so a reader MUST forgive one incomplete final record and preserve
every complete record before it. The same malformed bytes in an interior record
are corruption and MUST be rejected. The logical, encoding-neutral cases are
pinned by
[`conformance/reliable-sync/outbox_journal_decode.json`](../conformance/reliable-sync/outbox_journal_decode.json);
bindings encode them into their native JSON-lines or binary journal format before
replay.
