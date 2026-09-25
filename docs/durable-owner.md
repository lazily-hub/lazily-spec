# Durable Owner Contract (`#lzdurablespec`)

The durable-owner contract is the backend-neutral boundary for a host whose
accepted transitions survive process loss. It is distinct from the live
[durable effect-sink](durable-sinks.md) pattern: an effect sink projects a live
graph outward, while a durable owner commits the accepted transition first and
reconstructs a fresh graph from that durable image after restart.

No core type names SQL tables, broker subjects, or cache keys. A database
adapter implements the boundary; transport acknowledgement and publication run
after it.

## Identity and version types

Every owner, inbox item, outbox effect, and receipt has a non-empty stable
identity. Reusing an identity with byte-identical content is idempotent. Reusing
it with different content, schema version, codec version, or terminal outcome is
an identity conflict and MUST NOT overwrite the first record.

Every durable payload carries independent, positive `schema_version` and
`codec_version` values. A binding MUST preserve both. Unsupported versions fail
before decode or mutation; neither field may default, normalize, or stand in for
the other.

## Position and fence

Each owner starts at position zero. A new commit names the exact current
position and current fence token. The store assigns the next event position or
snapshot position with checked arithmetic. A stale or future position is a
compare-and-swap conflict. A fence mismatch is stale authority—even a greater
token cannot promote itself through a state write. Fence advancement is a
separate lease/authority operation.

Completed inbox deduplication runs before position and fence checks. Therefore,
a redelivery of a committed message returns the original committed position
even after later transitions or a fence handoff. It performs no new mutation.

## Atomic unit of work

One accepted commit makes all of these records visible together:

- the completed inbox identity and immutable input fingerprint;
- appended domain events or the replacement snapshot;
- outbox effect intents with stable effect identities;
- transaction-local terminal effect receipts.

A crash before the commit exposes none of them. A crash after the commit exposes
all of them. Only `Committed` or an exact completed `Duplicate` makes ingress
acknowledgement safe. External effect publication occurs after commit; a crash
after publication reuses the same effect identity, and its terminal receipt is
recorded idempotently as another durable fact.

## State modes

`EventHistory` and `Snapshot` are immutable per-owner modes:

- **Event history** preserves every accepted event in exact position order. Its
  complete-history fingerprint binds the owner, every positioned/versioned
  source record, the durable frontier, and the projected observation.
- **Snapshot state** replaces older state bytes while advancing the durable
  position. It proves recoverable current state, not complete history.

`LatestDurableProjection` is a third and deliberately separate egress protocol.
It may supersede pending intermediate values and therefore advertises only
`latest_state_only`. It MUST NOT implement, be accepted as, or be relabeled as a
complete-history source.

Two different valid histories may settle to the same projected state. Their
projection-content fingerprints may compare equal, while their history/source
fingerprints MUST differ. This is why a final-value comparison alone cannot
certify replay completeness.

## Canonical evidence

The `conformance/durable-owner/` corpus fixes four independent proof surfaces:

- `atomic_crash_boundary.json` — all-or-none commit visibility, commit-before-ACK,
  fresh reconstruction, and redelivery;
- `ordered_replay.json` — monotone positions, exact CAS, exact fences, history
  order, snapshot replacement, and independent schema/codec versions;
- `inbox_outbox_deduplication.json` — exact-repeat idempotency and identity
  conflict behavior for inboxes, effects, and receipts;
- `projection_fingerprint.json` — equal projections from unequal histories and
  the `complete_history` versus `latest_state_only` capability boundary.

The JSON Schema is `schemas/durable-owner.json`. Every assertion compares a
complete durable image or an explicit fingerprint relation, so an implementation
cannot pass by checking only a final value or a row count.
