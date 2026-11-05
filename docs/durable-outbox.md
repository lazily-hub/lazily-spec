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

## SQLite stores: busy timeout and write-lock acquisition (`#lazilysqlitestoreopen`)

A SQLite-backed `OutboxStore` routinely shares its database file with other
writers (agent-doc keeps the outbox tables in its `state.db`). Every operation
the store performs either acquires the write lock or fails, and a failed append
or cursor save is a lost epoch or a regressed acknowledgement. Two rules keep a
contended write waiting instead of failing:

1. **Explicit busy timeout.** A store that opens its own connection MUST install
   a busy timeout of exactly **30 000 ms** (lazily-rs `SQLITE_STORE_BUSY_TIMEOUT`).
   It MUST NOT rely on the driver's implicit default, which differs by driver
   (rusqlite: 5 s; Python `sqlite3`: 5 s; SQLite itself: 0). A store that adopts
   a caller-configured connection leaves the caller's busy handler unchanged and
   documents that the caller owns this obligation.
2. **No deferred read-then-write transactions.** Every store operation is one
   autocommit statement, or a transaction that takes the write lock up front
   (`BEGIN IMMEDIATE` or `BEGIN EXCLUSIVE`). SQLite consults the busy handler
   only when a statement acquires the write lock from no open transaction. A
   DEFERRED transaction that has already read holds a snapshot, and its first
   write must upgrade it; SQLite refuses that upgrade with an immediate
   `SQLITE_BUSY` (`database is locked`) that no busy timeout waits out. This is
   why `save_cursor`'s `max(stored_cursor, epoch)` above is a single upsert
   statement.

Each binding with a store that owns its connection MUST carry:

- a test that reads the installed busy timeout back from the connection
  (`PRAGMA busy_timeout`) and compares it with the contract value;
- a two-writer regression test, in rollback-journal and WAL mode: the first
  writer holds the write lock (`BEGIN IMMEDIATE` plus an uncommitted append), the
  second appends meanwhile and must stay blocked, then land once the first
  commits. The test MUST fail when the busy timeout is zero;
- a guard, wherever the language allows one, that rejects a deferred
  transaction (lazily-rs bans `rusqlite::Connection::{transaction,
  unchecked_transaction}` in `clippy.toml`; lazily-py scans `src/lazily` for a
  `sqlite3.connect` without `isolation_level=None` and the contract timeout, and
  for any statement-initial `BEGIN` that is not `IMMEDIATE`/`EXCLUSIVE`).

[`sqlite-stores.json`](../sqlite-stores.json) is the machine-checked form of this
section: the contract value plus one declaration per binding — a store that owns
its connection (with the file that declares the timeout, the two-writer tests,
and the guard), a store over a host-owned connection (the binding opens no
connection; the declared file states the host's obligation), or `"none"`.
`scripts/check-sqlite-stores.py` verifies every declaration against the sibling
checkouts, and fails a binding declared `"none"` that grows a SQLite driver
import, so a new SQLite path cannot land without this contract. Spec CI runs it
with `--require-all`.
